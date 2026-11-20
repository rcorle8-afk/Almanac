"""Room registry, state machine, timers, and snapshot builder.

Room is synchronous game logic with an injected clock. Hub owns sockets and timer tasks.
"""

import asyncio
import logging
import math
import random
import re
import secrets
import string
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from typing import Any

from pydantic import BaseModel, ValidationError

from server import achievements, anticheat, social
from server.db import Database, EndlessResult, FillRecord, GameResult, QuoteRecord, RoundRecord, SeatRecord
from server.engine.models import (
    BookSnapshot,
    EngineError,
    Fill,
    InvalidPriceError,
    NotFoundError,
    NotOwnerError,
    Order,
    PositionLimitError,
    Question,
    Quote,
    SelfTradeError,
    Side,
)
from server.engine.orderbook import OrderBook
from server.engine.scoring import POINTS_PRECISION, best_quote, buyer_points, round_points
from server.protocol import (
    AnswerGroupInvite,
    BestQuoteView,
    CancelOrder,
    EarnedAchievement,
    ErrorMessage,
    GameAward,
    GroupRoom,
    HostView,
    HintView,
    HostAdvance,
    HostBots,
    HostConfigure,
    HostCreate,
    HostDemo,
    HostGroupInvite,
    HostRestart,
    InviteTally,
    LiveView,
    Notice,
    TableInvite,
    MAX_BOTS,
    ROOM_CAPACITY,
    HostEnd,
    HostSkipRound,
    Hosted,
    HostResume,
    HostStart,
    Join,
    Joined,
    PlaceOrder,
    PlayerView,
    QuestionView,
    RoomConfig,
    State,
    SubmitQuote,
    TapeEntry,
    You,
    YourFill,
)
from server.room_codes import ROOM_WORDS

log = logging.getLogger("almanac")

ROOM_CODE_ALPHABET = "".join(c for c in string.ascii_uppercase if c not in "IO")
ROOM_CODE_LENGTH = 4
MIN_PLAYERS = 2
MAX_PLAYERS = ROOM_CAPACITY  # a club meeting of up to 100, with slack (Ryan, Nov 3, 2026)
MAX_NAME_LENGTH = 16
QUOTE_SIZE = 1
TAPE_LENGTH = 20
SEND_TIMEOUT_SECONDS = 5
EMPTY_ROOM_TTL_MS = 30 * 60 * 1000
# Big rooms: a phone gets the leaders plus itself, not every player, and a room's snapshots
# go out at most this often, each built once. The host screen still gets everyone.
PLAYERS_SHOWN = 10
PUBLISH_INTERVAL_SECONDS = 0.25
BROADCAST_WAIT_SECONDS = 1.0  # a slow phone must not hold up the other ninety-nine

ENGINE_ERRORS = {
    SelfTradeError: ("self_trade", "That order would trade with your own resting order."),
    PositionLimitError: ("position_limit", "That order would take you past your position limit."),
    InvalidPriceError: ("invalid_price", "Price must be positive and a multiple of the tick."),
    NotFoundError: ("not_found", "That order is no longer resting."),
    NotOwnerError: ("not_owner", "You can only cancel your own orders."),
}


def now_ms() -> int:
    return int(time.time() * 1000)


class Phase(str, Enum):
    LOBBY = "LOBBY"
    QUESTION = "QUESTION"
    QUOTING = "QUOTING"
    TRADING = "TRADING"
    REVEAL = "REVEAL"
    SCORES = "SCORES"
    GAME_OVER = "GAME_OVER"


class RoomError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(eq=False)
class Player:
    id: str
    name: str
    token: str
    total_points: Decimal = Decimal("0.00")
    round_points: Decimal | None = None
    session: Any = None
    user_id: int | None = None  # set when the player signed in
    avatar: dict | None = None  # the account's look when it joined; guests have none
    coins_awarded: int | None = None  # set once the finished game is saved
    xp_awarded: int | None = None
    prestige_awarded: int | None = None
    level_up: int | None = None  # the new level, when the game crossed one
    level: int | None = None  # the account's standing when it joined; None for guests and bots
    prestige: int | None = None
    drinks: int | None = None  # this round's drinks, in drinks mode, once settled
    drinks_total: int = 0
    bot_level: int = 0  # 0 for a person; 1-3 for a bot (easy, medium, hard)
    plays_from: int = 0  # the first round this seat may act in; a late joiner sits out one
    left_at: int | None = None  # when the last connection dropped; the endless table frees the seat later
    achievements: list[dict] = field(default_factory=list)  # tiers earned by this game, at GAME_OVER
    public_id: str | None = None  # the account's link id, for its profile and Add friend (M5)

    @property
    def is_bot(self) -> bool:
        return self.bot_level > 0

    @property
    def connected(self) -> bool:
        return self.session is not None or self.is_bot


@dataclass
class TableInviteState:
    """The host's offer of one of their groups to the table: what the card on each phone shows,
    who still has it up, and how it's going."""

    group: str  # public id
    name: str
    host: str
    icon: dict | None = None  # the group as a stranger sees it, for the card
    member_count: int = 0
    prestige: int = 0
    seats: set[str] = field(default_factory=set)  # the card is up, waiting for an answer
    # Said Not now. Left alone until the room's next lobby or game over, when the host may
    # offer again (Ryan, Nov 17, 2026: invite before the game, and again after it).
    declined: set[str] = field(default_factory=set)
    joined: set[str] = field(default_factory=set)
    asked: set[str] = field(default_factory=set)  # every seat that has had the card


# Bots quote around the true answer with log-normal noise and trade when a price looks wrong
# to them. Their skill is the noise: an easy bot's belief is often off by a factor of two, a
# hard bot's by 15%. They never earn coins or the Best Quote bonus.
BOT_NOISE = {1: 0.8, 2: 0.4, 3: 0.15}  # sigma of ln(belief / answer)
BOT_SPREAD = {1: (2.5, 4.0), 2: (1.6, 2.5), 3: (1.2, 1.6)}  # ask / bid of a bot's quote
BOT_TRADES = {1: 1, 2: 2, 3: 3}  # orders per trading phase
# End-of-game superlatives (Room.awards), in the order the screens show them.
GAME_AWARDS = (
    ("best_quotes", "Sharpest quoter"),
    ("biggest_round", "Biggest round"),
    ("most_trades", "Busiest trader"),
)

BOT_NAMES = (
    "Ada", "Turing", "Hopper", "Knuth", "Dijkstra", "Shannon", "Noether", "Curie",
    "Euler", "Gauss", "Lovelace", "Hamilton", "Fermat", "Bayes", "Pascal", "Babbage",
    "Ramanujan", "Hypatia", "Kepler", "Galois",
)
BOT_AVATAR = {
    "skin": "skin_1", "hair": "hair_none", "hair_color": "hair_black", "eyes": "eyes_blue",
    "mouth": "mouth_flat", "top": "top_armour", "head": None, "eyewear": "eye_visor",
    "ears": None, "effect": None,
}


def _to_tick(value: float, tick: Decimal, down: bool) -> Decimal:
    steps = math.floor(value / float(tick)) if down else math.ceil(value / float(tick))
    return Decimal(max(1, steps)) * tick


def bot_belief(level: int, answer: Decimal, rng: random.Random) -> float:
    return float(answer) * math.exp(rng.gauss(0, BOT_NOISE[level]))


def bot_quote(level: int, answer: Decimal, tick: Decimal, rng: random.Random) -> tuple[Decimal, Decimal]:
    belief = bot_belief(level, answer, rng)
    ratio = rng.uniform(*BOT_SPREAD[level])
    bid = _to_tick(belief / math.sqrt(ratio), tick, down=True)
    ask = _to_tick(belief * math.sqrt(ratio), tick, down=False)
    if ask <= bid:
        ask = bid + tick
    return bid, ask


def bot_order(
    level: int, answer: Decimal, book: BookSnapshot, tick: Decimal, rng: random.Random
) -> tuple[Side, Decimal, int]:
    """Takes a resting price that looks wrong by more than the bot's own uncertainty,
    otherwise rests an order a little inside its belief."""
    belief = bot_belief(level, answer, rng)
    size = rng.randint(1, 2)
    edge = math.exp(BOT_NOISE[level])
    if book.asks and float(book.asks[0].price) * edge < belief:
        return Side.BUY, book.asks[0].price, size
    if book.bids and float(book.bids[0].price) > belief * edge:
        return Side.SELL, book.bids[0].price, size
    side = rng.choice([Side.BUY, Side.SELL])
    skew = 0.9 if side is Side.BUY else 1.1
    return side, _to_tick(belief * skew, tick, down=side is Side.BUY), size


# The endless table (M6, Nov 10, 2026): one room that never ends, open to anyone at any time.
# Rounds follow each other at a quick pace, house bots keep it liquid, points pay out every
# round, and it idles when nobody is connected so no question is spent on an empty room.
ENDLESS_CODE = "OPEN"  # never a word code, and random codes have no O
ENDLESS_TIMERS = {"question": 4, "quoting": 15, "trading": 30, "reveal": 6, "scores": 5}
ENDLESS_HINT_SECONDS = 10
HOUSE_TRADERS = 6  # house bots fill the table up to this many traders, and step back as people come
HOUSE_BOT_LEVEL = 3  # the tightest quoting style; the house's error comes from its shared view
# The house never knows the answer. Each question gets one shared view, the answer times
# e^N(0, HOUSE_BIAS_SIGMA) (typically 25-60% off), and each house bot sits close to that view.
# So the house's average price points at the wrong number, and copying the bots loses.
HOUSE_BIAS_SIGMA = 0.45
HOUSE_NOISE_SIGMA = 0.10
HOUSE_REQUOTE_SECONDS = (3.0, 6.0)  # how often a house bot pulls and reposts its quotes
HOUSE_SPREAD = (1.15, 1.4)  # ask / bid of a house bot's market
HOUSE_LEARN = 0.3  # how far a house bot moves its belief toward each new trade price
HOUSE_SKEW = 0.06  # how far it shades its prices per lot it holds, to get flat again
SEAT_GRACE_MS = 90_000  # a dropped player keeps their seat (and session score) this long
RECENT_SHARE = 0.5  # a question can't come back until at least this share of the pool has played


def house_view(answer: Decimal, rng: random.Random) -> float:
    return float(answer) * math.exp(rng.gauss(0, HOUSE_BIAS_SIGMA))


def house_market(belief: float, position: int, tick: Decimal, rng: random.Random) -> tuple[Decimal, Decimal]:
    """A house bot's two-sided market: around its belief, shaded against what it already
    holds (long means it quotes lower, to sell), at a modest spread."""
    mid = belief * math.exp(-HOUSE_SKEW * position)
    ratio = rng.uniform(*HOUSE_SPREAD)
    bid = _to_tick(mid / math.sqrt(ratio), tick, down=True)
    ask = _to_tick(mid * math.sqrt(ratio), tick, down=False)
    if ask <= bid:
        ask = bid + tick
    return bid, ask


def learn(belief: float, price: float, hint: HintView | None) -> float:
    """A house bot's belief after seeing a trade at `price`, and the hint once it's out."""
    belief = belief * (price / belief) ** HOUSE_LEARN
    if hint is not None and hint.low is not None and hint.high is not None:
        low, high = float(hint.low), float(hint.high)
        if not low <= belief <= high:
            belief = math.sqrt(min(max(belief, low), high) * math.sqrt(low * high))
    return belief


# Drinks mode: a round's losses become drinks. One drink per (POINTS_PER_DRINK / strength)
# points lost, so strength 1 is a drink per 100 points and strength 5 a drink per 20.
POINTS_PER_DRINK = 100
MAX_DRINKS_PER_ROUND = 6


def drinks_for(round_points: Decimal, strength: int) -> int:
    lost = max(Decimal(0), -round_points)
    return min(MAX_DRINKS_PER_ROUND, int(lost * strength / POINTS_PER_DRINK))


# Most questions a single game may draw from a category. Ryan wants geography to be rare.
CATEGORY_CAPS = {"places": 1}
# Questions for drinks mode only: cruder, boozier, never drawn in a normal game.
SPICY_CATEGORY = "spicy"


# Case questions (Ryan, Nov 10, 2026). The host's switch: "extra" lets them land in any round,
# "default" makes them the last CASE_ROUNDS rounds, "off" leaves them out.
CASE_ROUNDS = 3
# A game's case rounds are worth more, rising evenly from the first to the last of them.
CASE_MULTIPLIER_FIRST = Decimal("1.5")
CASE_MULTIPLIER_LAST = Decimal("2.5")
MULTIPLIER_STEP = Decimal("0.1")
# How long a question takes to read and take in, the same measure for every question: words
# at a steady reading pace, plus time to hold on to each figure it gives.
WORDS_PER_SECOND = 3.5
SECONDS_PER_FIGURE = 1.0
_WORD = re.compile(r"\S+")
_FIGURE = re.compile(r"\d[\d,.]*")


def reading_seconds(question: Question) -> float:
    """Seconds to read and understand a question's setup and text. Case questions are played
    in this order, shortest first, so the longest (and best-paid) come last."""
    words = f"{question.context} {question.text}"
    figures = len(_FIGURE.findall(question.context))
    return len(_WORD.findall(words)) / WORDS_PER_SECOND + SECONDS_PER_FIGURE * figures


def round_multipliers(questions: list[Question]) -> list[Decimal]:
    """Each round's points multiplier: 1 for a standard question, and for the game's case
    questions in the order they're played, an even rise from 1.5 to 2.5 (2.0 when there is
    only one), to a tenth."""
    cases = [index for index, question in enumerate(questions) if question.kind == "case"]
    multipliers = [Decimal(1)] * len(questions)
    span = CASE_MULTIPLIER_LAST - CASE_MULTIPLIER_FIRST
    for rank, index in enumerate(cases):
        share = Decimal(rank) / (len(cases) - 1) if len(cases) > 1 else Decimal("0.5")
        multipliers[index] = (CASE_MULTIPLIER_FIRST + span * share).quantize(MULTIPLIER_STEP, ROUND_HALF_UP)
    return multipliers


def playable(questions: list[Question], case_mode: str) -> list[Question]:
    """The questions an ordinary (not drinks) game can draw from under a case mode."""
    tame = [question for question in questions if question.category != SPICY_CATEGORY]
    return [question for question in tame if case_mode != "off" or question.kind != "case"]


def pick_questions(
    questions: list[Question],
    rounds: int,
    rng: random.Random,
    spicy: bool = False,
    categories: list[str] | None = None,
    case_mode: str = "extra",
) -> list[Question]:
    """A game's questions in the order they're played.

    "off" draws standard questions only. "default" draws them for every round but the last
    CASE_ROUNDS, which are case questions (fewer if the bank runs short of either). "extra"
    draws from everything, so cases can land anywhere. In every mode the case questions drawn
    are put in reading order across the rounds they hold, the longest last."""
    standard = [question for question in questions if question.kind != "case"]
    cases = [question for question in questions if question.kind == "case"]
    if case_mode == "off":
        return _draw(standard, rounds, rng, spicy, categories)
    if case_mode == "default":
        tail = _draw(cases, min(CASE_ROUNDS, rounds, len(cases)), rng, categories=categories)
        head = _draw(standard, rounds - len(tail), rng, spicy, categories)
        if len(head) < rounds - len(tail):  # too few standard questions: more cases instead
            spare = [question for question in cases if question not in tail]
            tail += _draw(spare, rounds - len(tail) - len(head), rng, categories=categories)
        return head + sorted(tail, key=reading_seconds)
    picked = _draw(questions, rounds, rng, spicy, categories)
    slots = [index for index, question in enumerate(picked) if question.kind == "case"]
    for index, question in zip(slots, sorted((picked[i] for i in slots), key=reading_seconds)):
        picked[index] = question
    return picked


def _draw(
    questions: list[Question],
    rounds: int,
    rng: random.Random,
    spicy: bool = False,
    categories: list[str] | None = None,
) -> list[Question]:
    """A random set that respects CATEGORY_CAPS, breaking a cap only if the bank runs short.

    Spicy questions stay out unless asked for; then they all come first and tame ones pad.
    With categories chosen, those come first and the other tame ones pad."""
    tame = [question for question in questions if question.category != SPICY_CATEGORY]
    wanted = [question for question in tame if not categories or question.category in categories]
    others = [question for question in tame if question not in wanted]
    shuffled = rng.sample(wanted, len(wanted)) + rng.sample(others, len(others))
    if spicy:
        hot = [question for question in questions if question.category == SPICY_CATEGORY]
        shuffled = rng.sample(hot, len(hot)) + shuffled
    chosen: list[Question] = []
    counts: Counter[str] = Counter()
    for question in shuffled:
        cap = CATEGORY_CAPS.get(question.category)
        if cap is None or counts[question.category] < cap:
            chosen.append(question)
            counts[question.category] += 1
    chosen_ids = {question.id for question in chosen}
    leftovers = [question for question in shuffled if question.id not in chosen_ids]
    return (chosen + leftovers)[:rounds]


HINT_RANGE_RATIO = 2.0  # high / low before rounding outward
HINT_POSITION = (0.2, 0.8)  # where the answer may sit in the range, on a log scale


def _round_outward(value: float, up: bool) -> Decimal:
    """Rounds to two significant figures, away from the answer, so the range still holds it."""
    step = 10 ** (math.floor(math.log10(value)) - 1)
    steps = math.ceil(value / step) if up else math.floor(value / step)
    # Plain digits, never exponent form: phones display this string as-is.
    return Decimal(f"{steps * step:.10f}".rstrip("0").rstrip("."))


def make_hint(answer: Decimal, rng: random.Random) -> HintView:
    """A range about 2x wide that contains the answer somewhere other than its middle."""
    position = rng.uniform(*HINT_POSITION)
    low = float(answer) / HINT_RANGE_RATIO**position
    high = low * HINT_RANGE_RATIO
    return HintView(low=_round_outward(low, up=False), high=_round_outward(high, up=True))


def _on_tick(price: Decimal, tick: Decimal) -> bool:
    try:
        return price % tick == 0
    except InvalidOperation:  # too large for Decimal's context to divide
        return False


class Room:
    def __init__(
        self,
        code: str,
        config: RoomConfig,
        questions: list[Question],
        clock: Callable[[], int] = now_ms,
        rng: random.Random | None = None,
    ):
        self.code = code
        self.config = config
        self.clock = clock
        self.rng = rng or random.SystemRandom()
        self.bank = questions  # kept so a lobby setting can redraw the game's questions
        # Not seeded by the code: word codes repeat, and each game needs fresh questions.
        self.questions = self._draw_questions()
        self.next_seat = 1  # seat ids never repeat, even after bots come and go
        self.quote_log: list[QuoteRecord] = []  # every signed-in quote, for M6's anti-cheat
        self.bot_tasks: list[asyncio.Task] = []
        self.bots_seen = -1  # the transition the bots last acted on
        self.host_token = secrets.token_urlsafe(16)
        self.host_session: Any = None
        # The account signed in on the host screen, read each time that screen connects. It
        # hosts as itself and is never a seat, so the same account can also join and play
        # from a phone (Ryan, Nov 17, 2026).
        self.host_user: dict | None = None
        self.players: list[Player] = []
        self.phase = Phase.LOBBY
        self.round_no = 0
        self.timer_ends_at: int | None = None
        self.phase_seconds: float | None = None  # this phase's full length, for the timer bar
        self.empty_since: int | None = None
        self.timer_task: asyncio.Task | None = None
        self.publish_task: asyncio.Task | None = None
        self.publish_pending = False
        self.transitions = 0  # counts phase changes; deadlines alone can repeat
        self.scheduled_transition = 0
        self.settled = False
        # Whole-game tallies for saved results. They survive _reset_round on purpose.
        self.trade_counts: Counter[str] = Counter()
        self.best_quote_counts: Counter[str] = Counter()
        self.positive_points: dict[str, Decimal] = defaultdict(Decimal)
        self._clear_feats()
        self.rounds_scored = 0
        self.recorded = False
        # M5: a members-only room for one group (id, public_id, name), the accounts allowed in,
        # refreshed by the Hub before each join, and the host's invites of the table to a group.
        self.group: dict | None = None
        self.member_ids: set[int] = set()
        self.table_invites: dict[str, TableInviteState] = {}
        # M6 live mode: the server opens and starts this room itself at `starts_at` (epoch ms);
        # only signed-in accounts may sit, and too few by the start cancels the game.
        self.live = False
        self.signed_in_only = False
        self.starts_at: int | None = None
        self.cancelled = False
        # The endless table: never over, its deck refilled as it goes, a house view per question.
        self.endless = False
        self.house_view: float | None = None
        self.saved_round = 0  # the last round whose points were paid out
        self._reset_round()

    def _clear_feats(self) -> None:
        """Whole-game records that achievements read when the game is saved (game_facts)."""
        self.round_wins: Counter[str] = Counter()
        self.win_streak: Counter[str] = Counter()  # rounds won in a row, up to the last one
        self.best_streak: Counter[str] = Counter()
        self.best_round: dict[str, Decimal] = {}
        self.tightest: dict[str, Decimal] = {}  # the narrowest ask / bid that held the answer
        self.exact: set[str] = set()  # quoted the answer itself as bid or ask
        self.last_at_halfway: set[str] = set()
        self.game_fills: list[FillRecord] = []  # every round's trades, for the game log

    @property
    def question(self) -> Question | None:
        return self.questions[self.round_no - 1] if self.round_no else None

    @property
    def multiplier(self) -> Decimal:
        """This round's points multiplier: above 1 only for a case question."""
        if self.endless or not self.round_no:  # the endless deck holds no case questions
            return Decimal(1)
        return round_multipliers(self.questions)[self.round_no - 1]

    def _reset_round(self) -> None:
        tick = self.question.tick if self.question else Decimal(1)
        self.book = OrderBook(tick=tick, max_position=self.config.position_limit)
        self.quotes: dict[str, Quote] = {}
        self.fills: list[Fill] = []
        self.best: Quote | None = None
        self.hint: HintView | None = None
        self.hint_at: int | None = None
        self.quoting_opened_at: int | None = None  # when QUOTING began, for each quote's timing
        self.settled = False
        self.next_seq = 1
        for player in self.players:
            player.round_points = None
            player.drinks = None
            if getattr(self, "endless", False):  # the endless table pays per round
                player.coins_awarded = None
                player.xp_awarded = None

    def _log(self, event: str) -> None:
        log.info("room=%s round=%d %s", self.code, self.round_no, event)

    def _enter(self, phase: Phase) -> None:
        self.phase = phase
        self.transitions += 1
        seconds = self._phase_seconds(phase)
        self.phase_seconds = seconds
        self.timer_ends_at = self.clock() + int(seconds * 1000) if seconds else None
        self._log(f"phase={phase.value}")
        if phase in (Phase.LOBBY, Phase.GAME_OVER):
            for invite in self.table_invites.values():
                invite.declined.clear()  # a Not now lasts one lobby or one game-over screen
        if phase is Phase.QUOTING:
            self.quoting_opened_at = self.clock()
        lead = self._hint_lead()
        if phase is Phase.TRADING and lead and self.timer_ends_at is not None:
            self.hint_at = max(self.clock(), self.timer_ends_at - int(lead * 1000))

    @property
    def _is_case(self) -> bool:
        return self.question is not None and self.question.kind == "case"

    def _phase_seconds(self, phase: Phase) -> float | None:
        """How long a phase runs. A case question reads and trades on its own, longer timers."""
        timers = self.config.timers
        if self._is_case and phase is Phase.QUESTION:
            return timers.case_question
        if self._is_case and phase is Phase.TRADING:
            return timers.case_trading
        return getattr(timers, phase.value.lower(), None)

    def _hint_lead(self) -> float:
        """Seconds before trading closes that the hint appears. A case question's hint is a
        sentence to read and reason from, so it comes at the same point of the longer round
        (25s before the close at the standard pace), never later than a plain hint would."""
        lead = self.config.hint_seconds_left
        if self._is_case:
            lead *= max(1.0, self.config.timers.case_trading / self.config.timers.trading)
        return lead

    @property
    def hint_pending(self) -> bool:
        return self.phase is Phase.TRADING and self.hint_at is not None and self.hint is None

    @property
    def next_event_at(self) -> int | None:
        """When the timer should next fire: the hint first, then the phase deadline."""
        return self.hint_at if self.hint_pending else self.timer_ends_at

    def on_timer(self) -> None:
        if self.phase is Phase.LOBBY and self.live:
            self.start_live()
        elif self.hint_pending:
            self.reveal_hint()
        else:
            self.advance()

    def schedule_live(self, starts_at: int) -> None:
        """Makes this the live room: signed-in players only, starting on its own at `starts_at`."""
        self.live = True
        self.signed_in_only = True
        self.starts_at = starts_at
        self.timer_ends_at = starts_at  # the lobby counts down, and its timer starts the game
        self.transitions += 1
        self._log(f"live scheduled starts_at={starts_at}")

    def start_live(self) -> None:
        """The live game's start time: play with whoever is seated, or call it off."""
        if len(self.humans) >= MIN_PLAYERS:
            self._log(f"live start players={len(self.humans)}")
            self.start()
        else:
            self.cancelled = True
            self._log(f"live cancelled players={len(self.humans)}")
            self._enter(Phase.GAME_OVER)

    def reveal_hint(self) -> None:
        if self._is_case and self.question.hint_text:
            # A case question's hint is its own related figure, not a range around the answer.
            self.hint = HintView(text=self.question.hint_text)
            self._log("hint figure")
        else:
            self.hint = make_hint(self.question.answer, self.rng)
            self._log(f"hint low={self.hint.low} high={self.hint.high}")
        self.transitions += 1

    def _begin_round(self) -> None:
        if self.endless:
            self._prune_seats()
            self._balance_house()
            self._fill_deck()
        self.round_no += 1
        self._reset_round()
        if self.endless:
            self.house_view = house_view(self.question.answer, self.rng)
        self._enter(Phase.QUESTION)

    # The endless table.

    def make_endless(self) -> None:
        """Turns this room into the endless table: no game over, no host, anyone may sit."""
        self.endless = True
        self.questions = []
        self._log("endless table opened")

    @property
    def connected_humans(self) -> list[Player]:
        return [player for player in self.humans if player.session is not None]

    def wake(self) -> None:
        """Someone is at the idle table: start the next question."""
        if self.endless and self.phase is Phase.LOBBY and self.connected_humans:
            self._log("endless wake")
            self._begin_round()

    def _fill_deck(self) -> None:
        """Makes sure the next question exists. The deck is the standard pool, shuffled, with
        every question played recently held back, so nothing repeats until a good share of the
        pool has gone by."""
        if len(self.questions) > self.round_no:
            return
        pool = [question for question in playable(self.bank, "off") if question.kind != "case"]
        window = int(len(pool) * RECENT_SHARE)
        recent = {question.id for question in self.questions[-window:]} if window else set()
        fresh = [question for question in pool if question.id not in recent] or pool
        self.questions.extend(self.rng.sample(fresh, len(fresh)))

    def _prune_seats(self) -> None:
        """Frees the seats of people who left more than SEAT_GRACE_MS ago."""
        now = self.clock()
        gone = [
            player
            for player in self.humans
            if player.session is None and player.left_at is not None and now - player.left_at > SEAT_GRACE_MS
        ]
        if gone:
            self.players = [player for player in self.players if player not in gone]
            self._log(f"endless freed seats={len(gone)}")

    def _balance_house(self) -> None:
        """Keeps HOUSE_TRADERS traders at the table: house bots fill in for missing people and
        step back as people arrive. They're labeled as bots, like any other."""
        wanted = max(0, HOUSE_TRADERS - len(self.connected_humans))
        bots = [player for player in self.players if player.is_bot]
        if len(bots) > wanted:
            leaving = set(map(id, bots[wanted:]))
            self.players = [player for player in self.players if id(player) not in leaving]
        taken = {player.name.casefold() for player in self.players}
        names = [name for name in BOT_NAMES if f"bot {name}".casefold() not in taken]
        for name in names[: max(0, wanted - len(bots))]:
            self.players.append(
                Player(
                    id=self._new_seat(),
                    name=f"Bot {name}",
                    token=secrets.token_urlsafe(16),
                    bot_level=HOUSE_BOT_LEVEL,
                    avatar=dict(BOT_AVATAR),
                    plays_from=self.round_no + 1,
                )
            )

    def bot_center(self) -> Decimal:
        """What bots build their prices around: the answer at a host's table (where bot skill
        is how close they get), the house's shared wrong view at the endless table."""
        if self.endless and self.house_view is not None:
            return Decimal(str(self.house_view))
        return self.question.answer

    def _require_phase(self, phase: Phase) -> None:
        if self.phase is not phase:
            raise RoomError("wrong_phase", f"That isn't allowed during {self.phase.value}.")

    def join(self, name: str, token: str | None = None, user: dict | None = None) -> Player:
        if token:
            for player in self.players:
                if secrets.compare_digest(player.token, token):
                    if user is not None:
                        self._link_account(player, user)
                    return player
        if user is not None:
            for player in self.players:  # an account reclaims its seat from any device
                if player.user_id == user["id"]:
                    return player
        if self.signed_in_only and user is None:
            raise RoomError("sign_in", "The live game is for signed-in players. Sign in, then join.")
        if self.group is not None:
            if user is None:
                raise RoomError("group_only", f"This room is for {self.group['name']}. Sign in with a member's account to join.")
            if user["id"] not in self.member_ids:
                raise RoomError("group_only", f"This room is only for members of {self.group['name']}.")
        if len(self.players) >= self.config.max_players:
            raise RoomError("room_full", "This room is full.")
        # Anyone can join mid-game. Someone arriving once quoting has begun sits out the rest
        # of that round and plays from the next question; during QUESTION they play at once.
        late = self.phase not in (Phase.LOBBY, Phase.QUESTION)
        name = name.strip()
        if not name and user is not None:
            name = user["name"].strip()[:MAX_NAME_LENGTH]
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise RoomError("bad_name", f"Names must be 1 to {MAX_NAME_LENGTH} characters.")
        if any(player.name.casefold() == name.casefold() for player in self.players):
            raise RoomError("name_taken", "Someone in this room already has that name.")
        player = Player(
            id=self._new_seat(),
            name=name,
            token=secrets.token_urlsafe(16),
            user_id=user["id"] if user is not None else None,
            avatar=user.get("avatar") if user is not None else None,
            level=user.get("level") if user is not None else None,
            prestige=user.get("prestige") if user is not None else None,
            public_id=user.get("public_id") if user is not None else None,
            plays_from=self.round_no + 1 if late else self.round_no,
        )
        self.players.append(player)
        self._log(f"join player={player.id}" + (f" late plays_from={player.plays_from}" if late else ""))
        return player

    def _require_playing(self, player: Player) -> None:
        if player.plays_from > self.round_no:
            raise RoomError("sitting_out", "You joined during this round; you play from the next question.")

    def _new_seat(self) -> str:
        seat = f"p{self.next_seat}"
        self.next_seat += 1
        return seat

    def _draw_questions(self) -> list[Question]:
        return pick_questions(
            self.bank,
            self.config.rounds,
            self.rng,
            spicy=self.config.drinks,
            categories=self.config.categories,
            case_mode=self.config.case_mode,
        )

    @property
    def humans(self) -> list[Player]:
        return [player for player in self.players if not player.is_bot]

    def set_bots(self, count: int, level: int) -> None:
        """Seats `count` bots of one level, replacing any already there. Lobby only."""
        self._require_phase(Phase.LOBBY)
        self.players = self.humans
        room_left = max(0, self.config.max_players - len(self.players))
        taken = {player.name.casefold() for player in self.players}
        names = [name for name in BOT_NAMES if f"bot {name}".casefold() not in taken]
        for name in names[: min(count, room_left, MAX_BOTS)]:
            self.players.append(
                Player(
                    id=self._new_seat(),
                    name=f"Bot {name}",
                    token=secrets.token_urlsafe(16),
                    bot_level=level,
                    avatar=dict(BOT_AVATAR),
                )
            )
        self._log(f"bots count={count} level={level} seated={len(self.players) - len(self.humans)}")

    def demo(self) -> None:
        """Fills the room with bots and starts, so the host can show the game to a crowd."""
        self.set_bots(6, 2)
        self.start()

    def restart(self) -> None:
        """Play again: same seats, scores to zero, fresh questions, back to the lobby."""
        self._require_phase(Phase.GAME_OVER)
        self.round_no = 0
        self.questions = self._draw_questions()
        for player in self.players:
            player.total_points = Decimal("0.00")
            player.round_points = None
            player.drinks = None
            player.drinks_total = 0
            player.coins_awarded = None
            player.xp_awarded = None
            player.prestige_awarded = None
            player.level_up = None
            player.achievements = []
        self.trade_counts.clear()
        self.best_quote_counts.clear()
        self.positive_points.clear()
        self._clear_feats()
        self.rounds_scored = 0
        self.recorded = False
        self.quote_log = []
        self._reset_round()
        self._enter(Phase.LOBBY)

    def _link_account(self, player: Player, user: dict) -> None:
        """A seat reconnecting with a session: a guest seat takes the account (signing in from
        the lobby), and a seat that already has it picks up the account's current avatar."""
        if player.user_id == user["id"]:
            player.avatar = user.get("avatar")
            player.level = user.get("level")
            player.prestige = user.get("prestige")
            player.public_id = user.get("public_id")
        elif player.user_id is None:
            if any(other.user_id == user["id"] for other in self.players):
                self._log(f"link refused player={player.id}: account already seated")
                return
            player.user_id = user["id"]
            player.avatar = user.get("avatar")
            player.level = user.get("level")
            player.prestige = user.get("prestige")
            player.public_id = user.get("public_id")
            self._log(f"link player={player.id} user={user['id']}")

    def invite_table(self, group: dict, host: str, skip: Collection[int] = ()) -> list[Player]:
        """Puts the group's card on the phone of everyone at the table, guests included, except
        the accounts in `skip` (already members, or blocked), anyone who has the card up or
        joined through it, and anyone who said Not now since this lobby or game over began.
        `group` is the group as a stranger sees it. Returns the players newly asked."""
        invite = self.table_invites.setdefault(
            group["public_id"], TableInviteState(group=group["public_id"], name=group["name"], host=host)
        )
        invite.name, invite.host = group["name"], host
        invite.icon = group.get("icon")
        invite.member_count = group.get("member_count", 0)
        invite.prestige = group.get("prestige", 0)
        # A card still up for someone who has since joined another way (their bell, the link).
        invite.seats -= {player.id for player in self.humans if player.user_id in skip}
        settled = invite.seats | invite.declined | invite.joined
        fresh = [player for player in self.humans if player.user_id not in skip and player.id not in settled]
        invite.seats.update(player.id for player in fresh)
        invite.asked.update(player.id for player in fresh)
        self._log(f"table invite group={group['public_id']} seats={len(fresh)}")
        return fresh

    def require_invite(self, player: Player, group: str) -> TableInviteState:
        invite = self.table_invites.get(group)
        if invite is None or player.id not in invite.seats:
            raise RoomError("no_invite", "That invite isn't open any more.")
        return invite

    def answer_invite(self, player: Player, group: str, accepted: bool) -> None:
        invite = self.require_invite(player, group)
        invite.seats.discard(player.id)
        (invite.joined if accepted else invite.declined).add(player.id)
        if accepted:
            invite.member_count += 1  # so the cards still up show the group as it now is
        self._log(f"table invite group={group} player={player.id} {'joined' if accepted else 'declined'}")

    def configure(self, **changes: object) -> None:
        """Lobby settings from the host. A None leaves that setting as it is. Switching drinks
        mode redraws the game's questions, since only drinks mode gets the spicy ones."""
        changes = {key: value for key, value in changes.items() if value is not None}
        if "rounds" in changes:
            if self.phase is not Phase.LOBBY:
                raise RoomError("wrong_phase", "Rounds can only change before the game starts.")
            tame = playable(self.bank, changes.get("case_mode", self.config.case_mode))
            if len(tame) < changes["rounds"]:
                raise RoomError(
                    "not_enough_questions",
                    f"The bank has {len(tame)} questions, not enough for {changes['rounds']} rounds.",
                )
        if "case_mode" in changes and self.phase is not Phase.LOBBY:
            raise RoomError("wrong_phase", "Case questions can only change before the game starts.")
        if changes.get("case_mode") == "off" and len(playable(self.bank, "off")) < self.config.rounds:
            raise RoomError("not_enough_questions", "Without case questions the bank is too small for this many rounds.")
        if "timers" in changes:  # a partial change merges into the current timers
            partial = changes["timers"]
            fields = partial.model_dump(exclude_none=True) if hasattr(partial, "model_dump") else dict(partial)
            changes["timers"] = self.config.timers.model_copy(update=fields)
        before = self.config
        self.config = self.config.model_copy(update=changes)
        redraw = (self.config.drinks, self.config.categories, self.config.rounds, self.config.case_mode) != (
            before.drinks,
            before.categories,
            before.rounds,
            before.case_mode,
        )
        if self.phase is Phase.LOBBY and redraw:
            self.questions = self._draw_questions()
        self._log("configure " + " ".join(f"{key}={value}" for key, value in changes.items()))

    def start(self) -> None:
        self._require_phase(Phase.LOBBY)
        if len(self.players) < MIN_PLAYERS:
            raise RoomError("not_enough_players", f"You need at least {MIN_PLAYERS} players.")
        self._begin_round()

    def advance(self) -> None:
        match self.phase:
            case Phase.QUESTION:
                self._enter(Phase.QUOTING)
            case Phase.QUOTING:
                self._open_book()
                self._enter(Phase.TRADING)
            case Phase.TRADING:
                self._settle()
                self._enter(Phase.REVEAL)
            case Phase.REVEAL:
                self._enter(Phase.SCORES)
            case Phase.SCORES:
                if self.endless:
                    if self.connected_humans:
                        self._begin_round()
                    else:  # nobody here: idle without spending questions until someone comes
                        self._log("endless idle")
                        self._enter(Phase.LOBBY)
                elif self.round_no < self.config.rounds:
                    self._begin_round()
                else:
                    self._enter(Phase.GAME_OVER)
            case _:
                raise RoomError("wrong_phase", f"Nothing follows {self.phase.value}.")

    def skip_round(self) -> None:
        """The host's Skip question: finish this question where it stands and go straight to
        its scores. Every phase left still runs in order, without waiting: sealed quotes open
        the book (crossing quotes fill), and the fills settle against the answer."""
        if self.phase not in (Phase.QUESTION, Phase.QUOTING, Phase.TRADING, Phase.REVEAL):
            raise RoomError("wrong_phase", "There's no question to skip.")
        self._log(f"skip round from={self.phase.value}")
        while self.phase is not Phase.SCORES:
            self.advance()

    def end(self) -> None:
        if self.phase is Phase.GAME_OVER:
            raise RoomError("wrong_phase", "The game is already over.")
        self._enter(Phase.GAME_OVER)

    def submit_quote(self, player: Player, bid: Decimal, ask: Decimal) -> None:
        self._require_phase(Phase.QUOTING)
        self._require_playing(player)
        try:
            quote = Quote(player_id=player.id, bid=bid, ask=ask, submitted_at=self.clock())
        except ValidationError:
            raise RoomError("invalid_quote", "A quote needs a positive bid below the ask.") from None
        tick = self.question.tick
        if not (_on_tick(bid, tick) and _on_tick(ask, tick)):
            raise RoomError("invalid_quote", f"Bid and ask must be multiples of {tick}.")
        self.quotes[player.id] = quote
        self._log(f"quote player={player.id}")

    def place_order(self, player: Player, side: Side, price: Decimal, size: int) -> None:
        self._require_phase(Phase.TRADING)
        self._require_playing(player)
        self._submit(player.id, side, price, size)

    def cancel_order(self, player: Player, order_id: str) -> None:
        self._require_phase(Phase.TRADING)
        self.book.cancel(order_id, player.id)

    def _submit(self, player_id: str, side: Side, price: Decimal, size: int) -> None:
        seq = self.next_seq
        self.next_seq += 1
        order = Order(
            id=f"{self.round_no}-{seq}",
            player_id=player_id,
            side=side,
            price=price,
            size=size,
            seq=seq,
        )
        for fill in self.book.submit(order):
            self.fills.append(fill)
            self.trade_counts[fill.buyer_id] += 1
            self.trade_counts[fill.seller_id] += 1
            self._log(
                f"fill seq={fill.seq} price={fill.price} size={fill.size} "
                f"buyer={fill.buyer_id} seller={fill.seller_id}"
            )

    def _open_book(self) -> None:
        orders = []
        for player_id in sorted(self.quotes):
            quote = self.quotes[player_id]
            orders.append((player_id, Side.BUY, quote.bid))
            orders.append((player_id, Side.SELL, quote.ask))
        random.Random(f"{self.code}:{self.round_no}").shuffle(orders)
        for player_id, side, price in orders:
            try:
                self._submit(player_id, side, price, QUOTE_SIZE)
            except EngineError as error:
                # Reachable when a low position limit is hit by fills earlier in the open.
                self._log(f"open_reject player={player_id} error={type(error).__name__}")

    def _settle(self) -> None:
        answer = self.question.answer
        # Bots' quotes seed the book like anyone's, but only people can win Best Quote.
        bots = {player.id for player in self.players if player.is_bot}
        quotes = [quote for quote in self.quotes.values() if quote.player_id not in bots]
        points = round_points(self.fills, quotes, answer, self.config.scoring, self.multiplier)
        for player in self.humans:
            quote = self.quotes.get(player.id)
            if quote is not None:
                self.quote_log.append(
                    QuoteRecord(
                        round_no=self.round_no,
                        user_id=player.user_id,
                        name=player.name,
                        bid=quote.bid,
                        ask=quote.ask,
                        answer=answer,
                        mid_error=math.log(math.sqrt(float(quote.bid) * float(quote.ask)) / float(answer)),
                        question_id=self.question.id,
                        # How long after quoting opened this quote was sealed (its last change).
                        quote_ms=quote.submitted_at - self.quoting_opened_at if self.quoting_opened_at else None,
                        fills=sum(1 for fill in self.fills if player.id in (fill.buyer_id, fill.seller_id)),
                    )
                )
        for player in self.players:
            player.round_points = points.get(player.id, Decimal(0)).quantize(POINTS_PRECISION)
            player.total_points += player.round_points
            self.positive_points[player.id] += max(Decimal(0), player.round_points)
            if self.config.drinks:
                player.drinks = drinks_for(player.round_points, self.config.drink_strength)
                player.drinks_total += player.drinks
        self.best = best_quote(quotes, answer)
        if self.best is not None:
            self.best_quote_counts[self.best.player_id] += 1
        self.rounds_scored += 1
        self._note_feats(quotes, answer)
        # Every trade of the round, kept for the game log.
        for fill in self.fills:
            self.game_fills.append(
                FillRecord(
                    round_no=self.round_no,
                    seq=fill.seq,
                    price=fill.price,
                    size=fill.size,
                    buyer=fill.buyer_id,
                    seller=fill.seller_id,
                    buyer_points=buyer_points(fill, answer, self.config.scoring, self.multiplier),
                )
            )
        self.settled = True

    def game_log(self) -> tuple[list[SeatRecord], list[RoundRecord], list[FillRecord]]:
        """The table, the rounds played and every trade, for the saved game's log."""
        ranks = self.ranks()
        seats = [
            SeatRecord(
                seat=player.id,
                name=player.name,
                user_id=player.user_id,
                bot=player.is_bot,
                rank=ranks[player.id],
                points=player.total_points,
            )
            for player in self.players
        ]
        rounds = [
            RoundRecord(round_no=index + 1, question=question.text, unit=question.unit, answer=question.answer)
            for index, question in enumerate(self.questions[: self.rounds_scored])
        ]
        return seats, rounds, list(self.game_fills)

    def _note_feats(self, quotes: list[Quote], answer: Decimal) -> None:
        """What this round adds to the achievements' game records."""
        # The round goes to the one player with its top score, above zero; a tie wins nobody.
        top = max((player.round_points for player in self.players), default=Decimal(0))
        leaders = [player for player in self.players if player.round_points == top]
        winner = leaders[0].id if top > 0 and len(leaders) == 1 else None
        for player in self.players:
            if player.id == winner:
                self.round_wins[player.id] += 1
                self.win_streak[player.id] += 1
                self.best_streak[player.id] = max(self.best_streak[player.id], self.win_streak[player.id])
            else:
                self.win_streak[player.id] = 0
            best = self.best_round.get(player.id)
            if best is None or player.round_points > best:
                self.best_round[player.id] = player.round_points
        for quote in quotes:
            if quote.bid <= answer <= quote.ask:
                ratio = quote.ask / quote.bid
                if quote.player_id not in self.tightest or ratio < self.tightest[quote.player_id]:
                    self.tightest[quote.player_id] = ratio
            if answer in (quote.bid, quote.ask):
                self.exact.add(quote.player_id)
        # Who was last at the halfway mark, for a comeback (a table of three or more). Last means
        # behind somebody: a table still level at zero has nobody in last place.
        if len(self.players) >= 3 and self.rounds_scored == self.config.rounds // 2:
            totals = [player.total_points for player in self.players]
            bottom = min(totals)
            if bottom < max(totals):
                self.last_at_halfway = {p.id for p in self.players if p.total_points == bottom}

    def game_facts(self, player: Player, rank: int) -> dict[str, float]:
        """This game's achievement facts for one player (server/achievements.py)."""
        facts: dict[str, float] = {
            "game_round_streak": self.best_streak[player.id],
            "game_clean_sweep": float(
                self.rounds_scored >= 7 and self.round_wins[player.id] == self.rounds_scored
            ),
            "game_best_round": float(self.best_round.get(player.id, Decimal(0))),
            "game_trades": self.trade_counts[player.id],
            "game_exact_quote": float(player.id in self.exact),
            "game_room_size": len(self.humans),
            "game_sober_win": float(self.config.drinks and rank == 1 and player.drinks_total == 0),
            "game_comeback": float(rank == 1 and player.id in self.last_at_halfway),
        }
        if player.id in self.tightest:
            facts["game_quote_ratio"] = float(self.tightest[player.id])
        return facts

    def ranks(self) -> dict[str, int]:
        """Every seat's place at the table; ties share a rank."""
        ranked = sorted(self.players, key=lambda player: player.total_points, reverse=True)
        ranks: dict[str, int] = {}
        for index, player in enumerate(ranked):
            tied = index > 0 and player.total_points == ranked[index - 1].total_points
            ranks[player.id] = ranks[ranked[index - 1].id] if tied else index + 1
        return ranks

    def awards(self) -> list[GameAward]:
        """The end-of-game superlatives: most Best Quotes, biggest single round, most trades.
        Ties share an award; one nobody earned (no Best Quote all game, say) is left out."""
        if self.phase is not Phase.GAME_OVER or self.rounds_scored == 0:
            return []
        tallies = {
            "best_quotes": {p.id: Decimal(self.best_quote_counts[p.id]) for p in self.players},
            "biggest_round": {p.id: self.best_round.get(p.id, Decimal(0)) for p in self.players},
            "most_trades": {p.id: Decimal(self.trade_counts[p.id]) for p in self.players},
        }
        awards = []
        for award_id, title in GAME_AWARDS:
            tally = tallies[award_id]
            top = max(tally.values(), default=Decimal(0))
            if top <= 0:
                continue
            winners = [player for player in self.players if tally[player.id] == top]
            count = int(top)
            detail = {
                "best_quotes": f"{count} Best Quote{'' if count == 1 else 's'}",
                "biggest_round": f"+{top.quantize(POINTS_PRECISION)} in one round",
                "most_trades": f"{count} trade{'' if count == 1 else 's'}",
            }[award_id]
            awards.append(
                GameAward(
                    id=award_id,
                    title=title,
                    detail=detail,
                    winners=[player.id for player in winners],
                    names=[player.name for player in winners],
                )
            )
        return awards

    def results(self) -> list[GameResult]:
        """Signed-in players' results, ranked against everyone at the table (ties share a rank)."""
        ranks = self.ranks()
        return [
            GameResult(
                user_id=player.user_id,
                name=player.name,
                points=player.total_points,
                positive_points=self.positive_points[player.id],
                rank=ranks[player.id],
                best_quotes=self.best_quote_counts[player.id],
                trades=self.trade_counts[player.id],
            )
            for player in self.players
            if player.user_id is not None
        ]

    def snapshot(self, viewer: Player | None = None) -> State:
        names = {player.id: player.name for player in self.players}
        question = None
        if self.question:
            question = QuestionView(
                text=self.question.text,
                unit=self.question.unit,
                tick=self.question.tick,
                kind=self.question.kind,
                context=self.question.context or None,
                multiplier=self.multiplier,
            )
            if self.settled:
                question.answer = self.question.answer
                question.source_url = self.question.source_url
                question.source_note = self.question.source_note
        return State(
            room_code=self.code,
            phase=self.phase.value,
            round_no=self.round_no,
            rounds_total=0 if self.endless else self.config.rounds,  # 0: the endless table has no last round
            timer_ends_at=self.timer_ends_at,
            phase_seconds=self.phase_seconds,
            hint_at=self.hint_at if self.hint_pending else None,
            server_now=self.clock(),
            question=question,
            hint=self.hint,
            book=self.book.snapshot(),
            tape=[
                TapeEntry(
                    seq=fill.seq,
                    price=fill.price,
                    size=fill.size,
                    buyer=names[fill.buyer_id],
                    seller=names[fill.seller_id],
                )
                for fill in reversed(self.fills[-TAPE_LENGTH:])
            ],
            you=self._you(viewer) if viewer else None,
            player_count=len(self.players),
            players=[
                PlayerView(
                    id=player.id,
                    name=player.name,
                    drinks=player.drinks,
                    drinks_total=player.drinks_total,
                    bot=player.is_bot,
                    level=player.level,
                    prestige=player.prestige,
                    public_id=player.public_id,
                    connected=player.connected,
                    quoted=player.id in self.quotes,
                    signed_in=player.user_id is not None,
                    avatar=player.avatar,
                    total_points=player.total_points,
                    round_points=player.round_points,
                )
                for player in self.players
            ],
            best_quote=(
                BestQuoteView(
                    name=names[self.best.player_id],
                    bid=self.best.bid,
                    ask=self.best.ask,
                )
                if self.best
                else None
            ),
            config=self.config,
            awards=self.awards(),
            group=GroupRoom(public_id=self.group["public_id"], name=self.group["name"]) if self.group else None,
            host=self._host_view(),
            invites=[
                InviteTally(group=i.group, name=i.name, invited=len(i.asked), joined=len(i.joined))
                for i in self.table_invites.values()
            ],
            live=LiveView(starts_at=self.starts_at, cancelled=self.cancelled) if self.live else None,
            endless=self.endless,
        )

    def _host_view(self) -> HostView | None:
        """Who is hosting, for every screen: the account on the host screen, or nobody."""
        user = self.host_user
        if user is None:
            return None
        return HostView(
            name=user["name"],
            avatar=user.get("avatar"),
            level=user.get("level"),
            prestige=user.get("prestige"),
            public_id=user.get("public_id"),
        )

    def view_for(self, player: Player, base: State, leaders: list[PlayerView]) -> State:
        """A phone's copy of the host's snapshot: its own `you`, and the leaders plus itself
        instead of every player, so a hundred phones don't each get a hundred rows."""
        shown = leaders
        if all(view.id != player.id for view in leaders):
            shown = leaders + [view for view in base.players if view.id == player.id]
        return base.model_copy(update={"you": self._you(player), "players": shown})

    def _you(self, player: Player) -> You:
        names = {other.id: other.name for other in self.players}
        return You(
            fills=[
                YourFill(
                    seq=fill.seq,
                    side=Side.BUY if fill.buyer_id == player.id else Side.SELL,
                    price=fill.price,
                    size=fill.size,
                    counterparty=names[fill.seller_id if fill.buyer_id == player.id else fill.buyer_id],
                )
                for fill in self.fills
                if player.id in (fill.buyer_id, fill.seller_id)
            ],
            player_id=player.id,
            position=self.book.position(player.id),
            resting_orders=self.book.resting_orders(player.id),
            quote=self.quotes.get(player.id),
            round_points=player.round_points,
            total_points=player.total_points,
            coins_awarded=player.coins_awarded,
            xp_awarded=player.xp_awarded,
            prestige_awarded=player.prestige_awarded,
            level_up=player.level_up,
            achievements=[EarnedAchievement(**earned) for earned in player.achievements],
            sitting_out=player.plays_from > self.round_no,
            group_invites=[
                TableInvite(
                    group=i.group,
                    name=i.name,
                    host=i.host,
                    sign_in_first=player.user_id is None,
                    icon=i.icon,
                    member_count=i.member_count,
                    prestige=i.prestige,
                )
                for i in self.table_invites.values()
                if player.id in i.seats
            ],
        )


def save_game(db: Database, room: Room) -> None:
    """Writes a finished game for its signed-in players and tells each one their coins."""
    if room.rounds_scored == 0:
        return
    results = room.results()
    if not results:
        return
    seats, rounds, fills = room.game_log()
    awarded = db.record_game(
        room.code, room.rounds_scored, len(room.players), results, room.quote_log, seats, rounds, fills, live=room.live
    )
    ranks = {result.user_id: result.rank for result in results}
    for player in room.players:
        award = awarded.get(player.user_id) if player.user_id is not None else None
        if award is not None:
            player.coins_awarded = award.coins
            player.xp_awarded = award.xp
            player.prestige_awarded = award.prestige
            player.level_up = award.level_up
            # Achievements check the saved record and this game, and pay their rewards now.
            player.achievements = achievements.award(
                db, player.user_id, room.game_facts(player, ranks[player.user_id])
            )
    # M6 anti-cheat: everyone signed in is checked against their whole quote record. A flag is
    # silent; it only appears on /admin/flags for review.
    for result in results:
        if anticheat.review(db, result.user_id) == "flagged":
            room._log(f"accuracy flag user={result.user_id}")
    room._log(
        f"saved players={len(results)} coins={sum(a.coins for a in awarded.values())} "
        f"xp={sum(a.xp for a in awarded.values())} prestige={sum(a.prestige for a in awarded.values())}"
    )


def save_endless_round(db: Database, room: Room) -> None:
    """Pays one settled round at the endless table: each signed-in player who quoted or traded
    gets coins and XP now, their quotes go into the quote log, and anti-cheat checks them."""
    question = room.question
    answer = question.answer
    bots = {player.id for player in room.players if player.is_bot}
    results = []
    for player in room.humans:
        if player.user_id is None or player.plays_from > room.round_no:
            continue
        mine = [fill for fill in room.fills if player.id in (fill.buyer_id, fill.seller_id)]
        if player.id not in room.quotes and not mine:
            continue  # sat the round out: nothing earned
        vs_people = vs_house = Decimal(0)
        for fill in mine:
            earned = buyer_points(fill, answer, room.config.scoring, room.multiplier)
            buying = fill.buyer_id == player.id
            other = fill.seller_id if buying else fill.buyer_id
            signed = earned if buying else -earned
            if other in bots:
                vs_house += signed
            else:
                vs_people += signed
        results.append(
            EndlessResult(
                user_id=player.user_id,
                points=player.round_points or Decimal(0),
                vs_people=vs_people,
                vs_house=vs_house,
                trades=len(mine),
                best_quote=room.best is not None and room.best.player_id == player.id,
            )
        )
    quotes, room.quote_log, room.game_fills = room.quote_log, [], []  # the table never ends: don't hoard
    if not results:
        return
    record = RoundRecord(round_no=1, question=question.text, unit=question.unit, answer=answer)
    paid = db.record_endless_round(room.code, record, len(room.humans), results, quotes)
    for player in room.humans:
        if player.user_id in paid:
            player.coins_awarded, player.xp_awarded = paid[player.user_id]
    for result in results:
        if anticheat.review(db, result.user_id) == "flagged":
            room._log(f"accuracy flag user={result.user_id}")
    room._log(f"endless paid players={len(results)} coins={sum(c for c, _ in paid.values())}")


class Session:
    """One socket. It belongs to at most one room, as the host or as one player."""

    def __init__(self, socket: Any, user: dict | None = None):
        self.socket = socket
        self.user = user  # the signed-in account, if any
        self.room: Room | None = None
        self.player: Player | None = None

    async def send(self, message: BaseModel) -> None:
        try:
            await asyncio.wait_for(
                self.socket.send_json(message.model_dump(mode="json")),
                SEND_TIMEOUT_SECONDS,
            )
        except Exception as error:  # the receive loop notices the dead socket
            log.debug("send failed: %r", error)

    async def close(self) -> None:
        try:
            await self.socket.close()
        except Exception as error:
            log.debug("close failed: %r", error)


class Hub:
    def __init__(
        self,
        questions: list[Question],
        clock: Callable[[], int] = now_ms,
        on_game_over: Callable[[Room], None] | None = None,
        db: Callable[[], Database] | None = None,
        on_round_over: Callable[[Room], None] | None = None,
    ):
        self.questions = questions
        self.clock = clock
        self.on_game_over = on_game_over
        self.on_round_over = on_round_over  # the endless table pays out after every round
        self.db = db  # read on each use, so tests can swap the app's database
        self.publish_interval = PUBLISH_INTERVAL_SECONDS  # tests set 0 to see every snapshot
        self.rooms: dict[str, Room] = {}

    async def handle(self, session: Session, message: BaseModel) -> None:
        try:
            await self._dispatch(session, message)
        except RoomError as error:
            await session.send(ErrorMessage(code=error.code, message=error.message))
        except EngineError as error:
            code, text = ENGINE_ERRORS[type(error)]
            await session.send(ErrorMessage(code=code, message=text))

    async def _dispatch(self, session: Session, message: BaseModel) -> None:
        match message:
            case HostCreate():
                self._require_unattached(session)
                group = self._group_for_room(session, message.group) if message.group else None
                room = self._create_room(message.config)
                if group is not None:
                    room.group = group
                    room.member_ids = social.member_ids(self._db(), group["id"])
                await self._attach_host(session, room)
                if group is not None:
                    told = social.invite_to_room(self._db(), group["id"], room.code, session.user["id"])
                    room._log(f"group room group={group['public_id']} invited={told}")
            case HostResume():
                self._require_unattached(session)
                room = self._find_room(message.room_code)
                if not secrets.compare_digest(room.host_token, message.token):
                    raise RoomError("not_host", "That isn't this room's host.")
                await self._attach_host(session, room)
            case HostConfigure():
                self._host_room(session).configure(
                    recall_on_start=message.recall_on_start,
                    drinks=message.drinks,
                    drink_strength=message.drink_strength,
                    max_players=message.max_players,
                    categories=message.categories,
                    rounds=message.rounds,
                    timers=message.timers,
                    hint_seconds_left=message.hint_seconds_left,
                    position_limit=message.position_limit,
                    case_mode=message.case_mode,
                )
            case HostBots():
                self._host_room(session).set_bots(message.count, message.level)
            case HostDemo():
                self._host_room(session).demo()
            case HostRestart():
                self._host_room(session).restart()
            case HostStart():
                self._host_room(session).start()
            case HostAdvance():
                self._host_room(session).advance()
            case HostEnd():
                self._host_room(session).end()
            case HostSkipRound():
                self._host_room(session).skip_round()
            case HostGroupInvite():
                await self._invite_table(session, self._host_room(session), message.group)
            case Join():
                self._require_unattached(session)
                room = self._find_room(message.room_code)
                if room.group is not None:  # someone may have joined the group since it opened
                    room.member_ids = social.member_ids(self._db(), room.group["id"])
                player = room.join(message.name, message.token, session.user)
                await self._attach_player(session, room, player)
            case AnswerGroupInvite():
                room, player = self._seat(session)
                room.require_invite(player, message.group)
                if message.accept:
                    if player.user_id is None:
                        raise RoomError("sign_in", "Sign in first, then join the group.")
                    user_id = player.user_id
                    self._social(lambda: social.join(self._db(), user_id, message.group, via_room=True))
                room.answer_invite(player, message.group, message.accept)
            case SubmitQuote():
                room, player = self._seat(session)
                room.submit_quote(player, message.bid, message.ask)
            case PlaceOrder():
                room, player = self._seat(session)
                room.place_order(player, message.side, message.price, message.size)
            case CancelOrder():
                room, player = self._seat(session)
                room.cancel_order(player, message.order_id)
        await self.publish(session.room)

    def _db(self) -> Database:
        if self.db is None:
            raise RoomError("unavailable", "Accounts aren't available on this server.")
        return self.db()

    @staticmethod
    def _social(action: Callable[[], Any]) -> Any:
        """Runs a social rule, turning its refusal into an error for the screen that asked."""
        try:
            return action()
        except social.SocialError as error:
            raise RoomError("social", str(error)) from error

    def _group_for_room(self, session: Session, group: str) -> dict:
        """Play now on a group page: the host screen must be signed in as a member."""
        if session.user is None:
            raise RoomError("sign_in", "Sign in on this screen to open a room for your group.")
        user_id = session.user["id"]
        role = self._social(lambda: social.role_in(self._db(), group, user_id))
        if role is None:
            raise RoomError("not_member", "Only the group's members can open a room for it.")
        return social.group_ref(self._db(), group)

    async def _invite_table(self, session: Session, room: Room, group: str) -> None:
        """The host-group invite: a signed-in host screen offers one of its account's groups to
        everyone at the table who isn't in it. Signed-in players get a stored invite (their
        bell, and a push to their devices) and a card that pops up on their phone; guests get
        the card, and accept once they sign in. Any member may offer their group."""
        if session.user is None:
            raise RoomError("sign_in", "Sign in on this screen to invite the table to one of your groups.")
        host = session.user
        db = self._db()
        if self._social(lambda: social.role_in(db, group, host["id"])) is None:
            raise RoomError("not_member", "Only a group's members can invite players to it.")
        accounts = sorted({player.user_id for player in room.humans if player.user_id is not None})
        ref, outcomes = self._social(lambda: social.offer_at_table(db, host["id"], group, accounts))
        skip = {account for account, outcome in outcomes.items() if outcome in ("already_member", "blocked")}
        players = room.invite_table(ref, host["name"], skip)
        guests = sum(player.user_id is None for player in players)
        if not players:
            text = f"Everyone here is already in {ref['name']} or has had the invite."
        else:
            text = f"Invited {len(players)} {'player' if len(players) == 1 else 'players'} to {ref['name']}."
            if guests:
                text += f" {guests} {'guest' if guests == 1 else 'guests'} can accept after signing in."
        await session.send(Notice(message=text))

    def _require_unattached(self, session: Session) -> None:
        if session.room is not None:
            raise RoomError("already_in_room", "This connection is already in a room.")

    def _host_room(self, session: Session) -> Room:
        room = session.room
        if room is None or room.host_session is not session:
            raise RoomError("not_host", "Only the host can do that.")
        return room

    def _seat(self, session: Session) -> tuple[Room, Player]:
        if session.room is None or session.player is None:
            raise RoomError("not_player", "Join a room first.")
        return session.room, session.player

    def _find_room(self, code: str) -> Room:
        code = code.strip().upper()
        room = self.rooms.get(code)
        if room is None and code == ENDLESS_CODE:
            room = self.endless_table()
        if room is None:
            raise RoomError("room_not_found", "No room has that code.")
        return room

    def endless_table(self) -> Room:
        """The endless table, opened the first time anyone comes (and again after it was
        dropped for sitting empty). It idles in LOBBY until someone sits."""
        room = self.rooms.get(ENDLESS_CODE)
        if room is None:
            config = RoomConfig(
                case_mode="off",
                recall_on_start=False,
                timers=ENDLESS_TIMERS,
                hint_seconds_left=ENDLESS_HINT_SECONDS,
            )
            room = Room(ENDLESS_CODE, config, self.questions, self.clock)
            room.make_endless()
            self.rooms[ENDLESS_CODE] = room
            log.info("room=%s round=0 endless created", ENDLESS_CODE)
        return room

    def _create_room(self, config: RoomConfig) -> Room:
        tame = playable(self.questions, config.case_mode)
        if len(tame) < config.rounds:
            raise RoomError(
                "not_enough_questions",
                f"This game needs {config.rounds} verified questions and the bank "
                f"has {len(tame)}.",
            )
        self._drop_expired_rooms()
        code = self._new_code()
        room = Room(code, config, self.questions, self.clock)
        self.rooms[code] = room
        log.info("room=%s round=0 created", code)
        return room

    async def open_live(self, code: str, config: RoomConfig, starts_at: int) -> Room:
        """Opens tonight's live room under its reserved code, replacing last night's, and sets
        its lobby counting down to `starts_at`. Its timers run the whole game; no host needed."""
        old = self.rooms.pop(code, None)
        if old is not None and old.timer_task:
            old.timer_task.cancel()
        room = Room(code, config, self.questions, self.clock)
        room.schedule_live(starts_at)
        self.rooms[code] = room
        log.info("room=%s round=0 live opened", code)
        await self.publish(room)
        return room

    def _new_code(self) -> str:
        words = [word for word in ROOM_WORDS if word not in self.rooms]
        if words:
            return secrets.choice(words)
        while True:  # every word is in use, so fall back to letters that can't be misread
            code = "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))
            if code not in self.rooms:
                return code

    def _drop_expired_rooms(self) -> None:
        now = self.clock()
        for code, room in list(self.rooms.items()):
            if getattr(room, "live", False) and room.phase is not Phase.GAME_OVER:
                continue  # tonight's live room stays open, empty or not, until its game is done
            if room.empty_since is not None and now - room.empty_since > EMPTY_ROOM_TTL_MS:
                if room.timer_task:
                    room.timer_task.cancel()
                del self.rooms[code]
                log.info("room=%s dropped", code)

    async def _attach_host(self, session: Session, room: Room) -> None:
        previous = room.host_session
        room.host_session = session
        room.host_user = session.user  # the screen hosts as whoever is signed in on it now
        session.room = room
        room.empty_since = None
        if previous:
            await self._replace(previous, "This room is now open on another screen.")
        await session.send(Hosted(room_code=room.code, token=room.host_token))

    async def _attach_player(self, session: Session, room: Room, player: Player) -> None:
        previous = player.session
        player.session = session
        player.left_at = None
        session.room = room
        session.player = player
        room.empty_since = None
        if previous:
            await self._replace(previous, "Your seat is now open on another tab or device.")
        await session.send(Joined(room_code=room.code, player_id=player.id, token=player.token))
        room.wake()  # the idle endless table starts its next question

    async def _replace(self, previous: Session, message: str) -> None:
        """Tells a socket it has been superseded before closing it, so it doesn't reconnect and
        take the seat straight back (two tabs would otherwise trade it every second)."""
        await previous.send(ErrorMessage(code="replaced", message=message))
        await previous.close()

    async def disconnect(self, session: Session) -> None:
        room = session.room
        if room is None:
            return
        # A session replaced by a reconnect no longer speaks for its seat.
        if session.player is not None:
            if session.player.session is not session:
                return
            session.player.session = None
            session.player.left_at = self.clock()
        else:
            if room.host_session is not session:
                return
            room.host_session = None
        if room.host_session is None and not any(p.connected for p in room.players):
            room.empty_since = self.clock()
        await self.publish(room)

    async def publish(self, room: Room) -> None:
        if room.phase is Phase.GAME_OVER and not room.recorded:
            room.recorded = True  # once, even if saving fails
            if self.on_game_over is not None:
                try:
                    self.on_game_over(room)
                except Exception:
                    log.exception("room=%s round=%d saving the game failed", room.code, room.round_no)
        if room.endless and room.settled and room.saved_round != room.round_no:
            room.saved_round = room.round_no  # once per round, even if saving fails
            if self.on_round_over is not None:
                try:
                    self.on_round_over(room)
                except Exception:
                    log.exception("room=%s round=%d paying the round failed", room.code, room.round_no)
        self._schedule(room)
        self._run_bots(room)
        # Coalesced: the first change goes out at once, and whatever else happens in the next
        # interval goes out together, so a burst of orders from a hundred phones is a few
        # broadcasts, not a hundred.
        if room.publish_task is None or room.publish_task.done():
            room.publish_task = asyncio.create_task(self._broadcast(room))
        else:
            room.publish_pending = True

    def _run_bots(self, room: Room) -> None:
        """On each phase change, gives every bot a task for that phase: a quote during
        QUOTING, a few orders during TRADING. A phase change cancels what's left."""
        if room.transitions == room.bots_seen:
            return
        room.bots_seen = room.transitions
        for task in room.bot_tasks:
            task.cancel()
        room.bot_tasks = []
        if room.phase not in (Phase.QUOTING, Phase.TRADING):
            return
        for bot in room.players:
            if bot.is_bot:
                room.bot_tasks.append(asyncio.create_task(self._bot_turn(room, bot, room.transitions)))

    async def _bot_turn(self, room: Room, bot: Player, transition: int) -> None:
        rng = room.rng
        question = room.question
        if question is None or question.answer is None:
            return
        if room.phase is Phase.QUOTING:
            await asyncio.sleep(rng.uniform(1, 8))
            if room.transitions != transition:
                return
            bid, ask = bot_quote(bot.bot_level, room.bot_center(), question.tick, rng)
            try:
                room.submit_quote(bot, bid, ask)
            except RoomError:
                return
            await self.publish(room)
            return
        if room.endless:
            await self._make_market(room, bot, transition)
            return
        for _ in range(BOT_TRADES[bot.bot_level]):
            await asyncio.sleep(rng.uniform(2, 25))
            if room.transitions != transition:
                return
            side, price, size = bot_order(bot.bot_level, question.answer, room.book.snapshot(), question.tick, rng)
            try:
                room.place_order(bot, side, price, size)
            except (RoomError, EngineError):
                continue
            await self.publish(room)

    async def _make_market(self, room: Room, bot: Player, transition: int) -> None:
        """A house bot at the endless table keeps a bid and an ask in the book all through
        trading. Every few seconds it pulls them and posts new ones: around its belief, which
        starts near the house view (never the answer), moves toward each new trade price and
        into the hint's range once that's out, and shaded against the lots it already holds."""
        rng = room.rng
        question = room.question
        belief = float(room.bot_center()) * math.exp(rng.gauss(0, HOUSE_NOISE_SIGMA))
        seen = 0
        while True:
            if seen < len(room.fills):
                belief = learn(belief, float(room.fills[-1].price), room.hint)
                seen = len(room.fills)
            elif room.hint is not None:
                belief = learn(belief, belief, room.hint)
            for order in room.book.resting_orders(bot.id):
                try:
                    room.cancel_order(bot, order.id)
                except (RoomError, EngineError):
                    pass
            bid, ask = house_market(belief, room.book.position(bot.id), question.tick, rng)
            for side, price in ((Side.BUY, bid), (Side.SELL, ask)):
                try:
                    room.place_order(bot, side, price, 1)
                except (RoomError, EngineError):
                    continue  # a position limit or another bot's price in the way; next time
            await self.publish(room)
            await asyncio.sleep(rng.uniform(*HOUSE_REQUOTE_SECONDS))
            if room.transitions != transition or room.phase is not Phase.TRADING:
                return

    async def _broadcast(self, room: Room) -> None:
        while True:
            room.publish_pending = False
            try:
                await self._send_snapshots(room)
            except Exception:
                log.exception("room=%s round=%d broadcast failed", room.code, room.round_no)
            await asyncio.sleep(self.publish_interval)
            if not room.publish_pending:
                return

    async def _send_snapshots(self, room: Room) -> None:
        base = room.snapshot()  # built once: the host's view, with everyone and no `you`
        ranked = sorted(base.players, key=lambda view: view.total_points, reverse=True)
        leaders = ranked[:PLAYERS_SHOWN]
        sends = []
        if room.host_session:
            sends.append(room.host_session.send(base))
        for player in room.players:
            if player.session:
                sends.append(player.session.send(room.view_for(player, base, leaders)))
        if sends:
            tasks = [asyncio.create_task(send) for send in sends]
            await asyncio.wait(tasks, timeout=BROADCAST_WAIT_SECONDS)

    def _schedule(self, room: Room) -> None:
        if room.transitions == room.scheduled_transition:
            return
        if room.timer_task and room.timer_task is not asyncio.current_task():
            room.timer_task.cancel()
        room.scheduled_transition = room.transitions
        room.timer_task = None
        if room.next_event_at is not None:
            room.timer_task = asyncio.create_task(self._expire(room, room.transitions))

    async def _expire(self, room: Room, transition: int) -> None:
        await asyncio.sleep(max(0, room.next_event_at - self.clock()) / 1000)
        if room.transitions != transition:
            return
        try:
            room.on_timer()
            await self.publish(room)
        except Exception:
            log.exception("room=%s round=%d timer failed", room.code, room.round_no)
