"""WebSocket message types. Mirrored by hand in client/src/lib/types.ts."""

import os
from decimal import Decimal
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

from server.engine.models import MAX_ORDER_SIZE, BookSnapshot, Order, Quote, Side
from server.engine.scoring import ScoringMode

MIN_ROUNDS = 3
MAX_ROUNDS = 15
DEFAULT_ROUNDS = int(os.environ.get("DEFAULT_ROUNDS", "7"))
POSITION_LIMIT = int(os.environ.get("POSITION_LIMIT", "5"))

Seconds = Annotated[float, Field(gt=0, le=600)]


class Timers(BaseModel):
    # Short on purpose (Ryan, Nov 3, 2026): a 5s read and a 20s quote should cause some panic.
    question: Seconds = 5
    quoting: Seconds = 20
    trading: Seconds = 45
    reveal: Seconds = 10
    scores: Seconds = 10
    # A case question has a few sentences to read and more to reason about, so its QUESTION
    # and TRADING phases run on these instead (Ryan, Nov 9, 2026).
    case_question: Seconds = 15
    case_trading: Seconds = 75


CaseMode = Literal["extra", "default", "off"]

MIN_DRINK_STRENGTH = 1
MAX_DRINK_STRENGTH = 5
ROOM_CAPACITY = 120  # the most seats any room can have; a host may set fewer
MAX_BOTS = 20
BOT_LEVELS = (1, 2, 3)  # easy, medium, hard


class RoomConfig(BaseModel):
    rounds: int = Field(default=DEFAULT_ROUNDS, ge=MIN_ROUNDS, le=MAX_ROUNDS)
    position_limit: int = Field(default=POSITION_LIMIT, ge=1, le=100)
    scoring: ScoringMode = "log"
    timers: Timers = Field(default_factory=Timers)
    # Seconds before trading closes that the hint appears. 0 turns hints off.
    hint_seconds_left: float = Field(default=15, ge=0, le=600)
    # When the host starts the game, phones showing the locker or shop return to the game.
    recall_on_start: bool = True
    # Drinks mode: points lost in a round become drinks, and the game draws spicier questions.
    drinks: bool = False
    # How many drinks a loss costs: 1 drink per (100 / strength) points lost, capped per round.
    drink_strength: int = Field(default=2, ge=MIN_DRINK_STRENGTH, le=MAX_DRINK_STRENGTH)
    # Seats in this room, counting bots. The host layout reads it too.
    max_players: int = Field(default=ROOM_CAPACITY, ge=2, le=ROOM_CAPACITY)
    # Question categories to draw from; None or empty means every category. Spicy is separate.
    categories: list[str] | None = None
    # Case questions: "extra" in any round, "default" as the last three rounds, "off" never.
    case_mode: CaseMode = "default"


# Client -> server


class HostCreate(BaseModel):
    type: Literal["host_create"]
    config: RoomConfig = Field(default_factory=RoomConfig)
    # A group's public id opens a room only its members can join (M5: Play now on the group
    # page). The host screen must be signed in as a member.
    group: str | None = Field(default=None, max_length=40)


class HostResume(BaseModel):
    type: Literal["host_resume"]
    room_code: str
    token: str


class TimerChanges(BaseModel):
    """Seconds for the phases the host wants to change; the others keep their values."""

    question: Seconds | None = None
    quoting: Seconds | None = None
    trading: Seconds | None = None
    reveal: Seconds | None = None
    scores: Seconds | None = None
    case_question: Seconds | None = None
    case_trading: Seconds | None = None


class HostConfigure(BaseModel):
    """Settings the host changes from the settings drawer; a field left out stays as it is.
    Rounds only change in the lobby (the questions are drawn from it); timers, the hint and
    the position limit take effect from the next phase or round."""

    type: Literal["host_configure"]
    recall_on_start: bool | None = None
    drinks: bool | None = None
    drink_strength: int | None = Field(default=None, ge=MIN_DRINK_STRENGTH, le=MAX_DRINK_STRENGTH)
    max_players: int | None = Field(default=None, ge=2, le=ROOM_CAPACITY)
    categories: list[str] | None = None
    rounds: int | None = Field(default=None, ge=MIN_ROUNDS, le=MAX_ROUNDS)
    timers: TimerChanges | None = None
    hint_seconds_left: float | None = Field(default=None, ge=0, le=600)
    position_limit: int | None = Field(default=None, ge=1, le=100)
    case_mode: CaseMode | None = None  # lobby only


class HostBots(BaseModel):
    """Sets how many bots sit in the room, and how good they are. Lobby only."""

    type: Literal["host_bots"]
    count: int = Field(ge=0, le=MAX_BOTS)
    level: int = Field(default=2, ge=min(BOT_LEVELS), le=max(BOT_LEVELS))


class HostDemo(BaseModel):
    """Fills the room with bots and starts, so the host can show the game to a room."""

    type: Literal["host_demo"]


class HostRestart(BaseModel):
    """From game over: same room, same players, new questions, scores back to zero."""

    type: Literal["host_restart"]


class HostStart(BaseModel):
    type: Literal["host_start"]


class HostAdvance(BaseModel):
    type: Literal["host_advance"]


class HostEnd(BaseModel):
    type: Literal["host_end"]


class HostSkipRound(BaseModel):
    """Skip question: finish the current question at once and land on its scores."""

    type: Literal["host_skip_round"]


class HostGroupInvite(BaseModel):
    """A signed-in host screen offers one of its account's groups to everyone at the table.
    Signed-in players get a stored invite (their bell, a push) and a card that pops up on their
    phone; guests get the card and can accept once they sign in."""

    type: Literal["host_group_invite"]
    group: str = Field(max_length=40)


class Join(BaseModel):
    type: Literal["join"]
    room_code: str
    name: str
    token: str | None = None


class AnswerGroupInvite(BaseModel):
    """A player's answer to the card the host's group invite put on their phone."""

    type: Literal["answer_group_invite"]
    group: str = Field(max_length=40)
    accept: bool


class SubmitQuote(BaseModel):
    type: Literal["submit_quote"]
    bid: Decimal
    ask: Decimal


class PlaceOrder(BaseModel):
    type: Literal["place_order"]
    side: Side
    price: Decimal
    size: int = Field(ge=1, le=MAX_ORDER_SIZE)


class CancelOrder(BaseModel):
    type: Literal["cancel_order"]
    order_id: str


ClientMessage = Annotated[
    Union[
        HostCreate,
        HostResume,
        HostConfigure,
        HostBots,
        HostDemo,
        HostRestart,
        HostStart,
        HostAdvance,
        HostEnd,
        HostSkipRound,
        HostGroupInvite,
        Join,
        AnswerGroupInvite,
        SubmitQuote,
        PlaceOrder,
        CancelOrder,
    ],
    Field(discriminator="type"),
]
CLIENT_MESSAGE = TypeAdapter(ClientMessage)


# Server -> client


class QuestionView(BaseModel):
    text: str
    unit: str
    tick: Decimal
    kind: str = "standard"  # "case" for a case question
    context: str | None = None  # a case question's setup, shown above the question
    multiplier: Decimal = Decimal(1)  # the round's points multiplier: 1.5 to 2.5 for a case
    # Only present from REVEAL onward.
    answer: Decimal | None = None
    source_url: str | None = None
    source_note: str | None = None


class TapeEntry(BaseModel):
    seq: int
    price: Decimal
    size: int
    buyer: str
    seller: str


class YourFill(BaseModel):
    """One of the viewer's own fills this round, seen from their side of the trade."""

    seq: int
    side: Side
    price: Decimal
    size: int
    counterparty: str


class EarnedAchievement(BaseModel):
    """An achievement tier this game earned, for the game-end screen."""

    id: str
    name: str
    icon: str
    tier: str  # bronze, silver, gold, platinum or mystery
    requirement: str
    reward: str


class You(BaseModel):
    player_id: str
    position: int
    resting_orders: list[Order]
    quote: Quote | None
    round_points: Decimal | None
    total_points: Decimal
    coins_awarded: int | None = None  # set at GAME_OVER once a signed-in player's game is saved
    xp_awarded: int | None = None
    prestige_awarded: int | None = None
    level_up: int | None = None  # the new level, when this game crossed one
    achievements: list[EarnedAchievement] = []  # tiers this game earned, set at GAME_OVER
    fills: list[YourFill] = []  # every fill of yours this round, oldest first
    sitting_out: bool = False  # joined mid-round; plays from the next question
    group_invites: list["TableInvite"] = []  # the host's group invites you haven't answered


class TableInvite(BaseModel):
    """A card that pops up on a phone: the host invited this table to one of their groups."""

    group: str  # the group's public id
    name: str
    host: str  # the inviting host's name
    sign_in_first: bool = False  # a guest must sign in before accepting
    # The group as a stranger sees it, so the card can show what's on offer.
    icon: dict[str, str | None] | None = None  # glyph, color, image
    member_count: int = 0
    prestige: int = 0


class HostView(BaseModel):
    """The account signed in on the host screen. It hosts as itself and takes no seat, so the
    same account can also sit down and play from a phone."""

    name: str
    avatar: dict[str, str | None] | None = None
    level: int | None = None
    prestige: int | None = None
    public_id: str | None = None


class GroupRoom(BaseModel):
    """The group a members-only room is for."""

    public_id: str
    name: str


class InviteTally(BaseModel):
    """How a table invite is going, for the host screen."""

    group: str
    name: str
    invited: int  # seats that have had the card
    joined: int


You.model_rebuild()  # `You` names TableInvite before it's defined


class PlayerView(BaseModel):
    id: str
    name: str
    connected: bool
    quoted: bool
    signed_in: bool = False
    avatar: dict[str, str | None] | None = None  # slot -> item id; None for guests
    total_points: Decimal
    round_points: Decimal | None
    drinks: int | None = None  # this round's drinks once settled, only in drinks mode
    drinks_total: int = 0  # drinks over the whole game
    bot: bool = False  # a server-side player; never earns coins or Best Quote
    level: int | None = None  # the account's standing; None for guests and bots
    prestige: int | None = None
    public_id: str | None = None  # the account's link id, for its profile and Add friend (M5)


class HintView(BaseModel):
    """The hint shown late in trading: a range that contains the answer, or, for a case
    question, a sentence giving a related figure. One or the other, never both."""

    low: Decimal | None = None
    high: Decimal | None = None
    text: str | None = None


class BestQuoteView(BaseModel):
    name: str
    bid: Decimal
    ask: Decimal


class GameAward(BaseModel):
    """An end-of-game superlative: who did the most of something this game. Ties share it."""

    id: str  # best_quotes, biggest_round, most_trades
    title: str
    detail: str  # "3 Best Quotes", "+142.30 in one round", "18 trades"
    winners: list[str]  # seat ids
    names: list[str]


class LiveView(BaseModel):
    """Set on the nightly live room (M6): when it starts, and whether too few came."""

    starts_at: int | None  # epoch ms; the lobby counts down to it
    cancelled: bool = False


class State(BaseModel):
    type: Literal["state"] = "state"
    room_code: str
    phase: str
    round_no: int
    rounds_total: int
    timer_ends_at: int | None
    # How long this phase runs in all, and when its hint is due (epoch ms, only while one is
    # still to come). Sent because a case question's phases don't follow the plain timers.
    phase_seconds: float | None = None
    hint_at: int | None = None
    server_now: int  # epoch ms, so clients can correct for clock skew
    question: QuestionView | None
    hint: HintView | None  # from late TRADING through the end of the round
    book: BookSnapshot
    tape: list[TapeEntry]
    you: You | None  # None for the host screen
    player_count: int  # everyone seated; a phone's `players` list is only the leaders plus itself
    players: list[PlayerView]
    best_quote: BestQuoteView | None
    config: RoomConfig
    awards: list[GameAward] = []  # end-of-game superlatives, only at GAME_OVER
    group: GroupRoom | None = None  # set when only that group's members may join
    host: HostView | None = None  # who is hosting, when the host screen is signed in
    invites: list[InviteTally] = []  # the host's table invites to their groups
    live: LiveView | None = None  # only on the nightly live room
    endless: bool = False  # the endless table: no last round, points paid every round


class Notice(BaseModel):
    """A one-off message for one screen, such as how a table invite went."""

    type: Literal["notice"] = "notice"
    message: str


class Hosted(BaseModel):
    type: Literal["hosted"] = "hosted"
    room_code: str
    token: str


class Joined(BaseModel):
    type: Literal["joined"] = "joined"
    room_code: str
    player_id: str
    token: str


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
