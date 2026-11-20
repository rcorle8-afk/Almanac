"""SQLite storage for accounts, sessions, and saved game results.

One file on one machine: a Fly volume in production, ./data locally. Writes are small and
rare (a sign-in, a game ending), so plain sqlite3 behind a lock is enough. Live rooms never
touch this; only finished games do.
"""

import json
import logging
import math
import secrets
import sqlite3
import threading
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from server import social
from server.cosmetics import CATALOG, DEFAULT_AVATAR, WELCOME_COINS, stored_avatar

log = logging.getLogger("almanac.db")

# Items retired from the catalog. Anyone still holding one is refunded what they paid, at
# startup, and the inventory row removed, so nothing points at art that no longer exists.
RETIRED_ITEMS: frozenset[str] = frozenset({"effect_phoenix"})  # Phoenix wings, Nov 4, 2026

# Items renamed after they could be bought or worn: inventories and avatars move to the new id
# at startup. The banners' first names were live for part of Nov 4, 2026.
RENAMED_ITEMS: dict[str, str] = {
    "banner_slate": "banner_ballpark",
    "banner_ledger": "banner_envelope",
    "banner_pinstripe": "banner_thumb",
    "banner_sparkline": "banner_guess",
    "banner_tape": "banner_magnitude",
    "banner_bluechip": "banner_fermi",
    "banner_analyst": "banner_luck",
    "banner_associate": "banner_suspect",
    "banner_vp": "banner_knowitall",
    "banner_director": "banner_almanac",
    "banner_partner": "banner_oracle",
    "banner_beta": "banner_close",
    "banner_alpha": "banner_spoton",
    "banner_sigma": "banner_reckoning",
    "banner_omega": "banner_crystal",
    "banner_closing_bell": "banner_podium",
    "banner_opening_bell": "banner_primetime",
}

# One-off gifts of coins to every account (Ryan, Nov 17, 2026: 800 to everyone). Each is paid
# once, at startup, to the accounts that exist when the server first runs with it listed here.
# `coin_grants` records that it was paid, so a restart never pays it twice and an account made
# later doesn't get it. To give another, add a line under a new name; never change or remove one
# that has been paid.
COIN_GRANTS: dict[str, int] = {"2026-11-17-everyone": 800}

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "almanac.db"
SESSION_DAYS = 90
RECENT_GAMES = 20  # on the profile; the full history is paged
HISTORY_PAGE = 25

# Coins are play money earned only by playing. Points are zero-sum, so finishing and winning
# pay out too; otherwise half of every table would earn nothing.
COINS_PER_POSITIVE_POINT = 1
COINS_FOR_FINISHING = 20
COINS_FOR_WINNING = 50
COINS_PER_BEST_QUOTE = 10

# Progression (M4). XP rewards playing at all; prestige rewards winning and Best Quotes and is
# the number people compare. Level n needs LEVEL_XP * (n - 1)^2 XP: 100, 400, 900, 1600...
XP_FOR_FINISHING = 50
XP_PER_ROUND = 5
XP_PER_TRADE = 2
XP_PER_BEST_QUOTE = 15
PRESTIGE_FOR_WINNING = 100
PRESTIGE_FOR_PODIUM = 30  # second and third
PRESTIGE_PER_BEST_QUOTE = 20
LEVEL_XP = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    google_sub TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    picture TEXT NOT NULL DEFAULT '',
    coins INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    room_code TEXT NOT NULL,
    rounds INTEGER NOT NULL,
    player_count INTEGER NOT NULL,
    ended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    points TEXT NOT NULL,
    rank INTEGER NOT NULL,
    best_quotes INTEGER NOT NULL,
    trades INTEGER NOT NULL,
    coins INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS results_by_user ON results(user_id, id);
CREATE TABLE IF NOT EXISTS inventory (
    user_id INTEGER NOT NULL REFERENCES users(id),
    item_id TEXT NOT NULL,
    price INTEGER NOT NULL,
    bought_at TEXT NOT NULL,
    PRIMARY KEY (user_id, item_id)
);
CREATE TABLE IF NOT EXISTS quote_log (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id),
    round_no INTEGER NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    bid TEXT NOT NULL,
    ask TEXT NOT NULL,
    answer TEXT NOT NULL,
    mid_error REAL NOT NULL,
    fills INTEGER NOT NULL,
    question_id TEXT NOT NULL DEFAULT '',
    quote_ms INTEGER
);
CREATE TABLE IF NOT EXISTS game_players (
    game_id INTEGER NOT NULL REFERENCES games(id),
    seat TEXT NOT NULL,
    name TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id),
    bot INTEGER NOT NULL,
    rank INTEGER NOT NULL,
    points TEXT NOT NULL,
    PRIMARY KEY (game_id, seat)
);
CREATE TABLE IF NOT EXISTS game_rounds (
    game_id INTEGER NOT NULL REFERENCES games(id),
    round_no INTEGER NOT NULL,
    question TEXT NOT NULL,
    unit TEXT NOT NULL,
    answer TEXT NOT NULL,
    PRIMARY KEY (game_id, round_no)
);
CREATE TABLE IF NOT EXISTS game_fills (
    game_id INTEGER NOT NULL REFERENCES games(id),
    round_no INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    price TEXT NOT NULL,
    size INTEGER NOT NULL,
    buyer TEXT NOT NULL,
    seller TEXT NOT NULL,
    buyer_points TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS game_fills_by_game ON game_fills(game_id, round_no, seq);
CREATE TABLE IF NOT EXISTS endless_results (
    game_id INTEGER NOT NULL REFERENCES games(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    points TEXT NOT NULL,
    vs_people TEXT NOT NULL,
    vs_house TEXT NOT NULL,
    trades INTEGER NOT NULL,
    best_quote INTEGER NOT NULL,
    coins INTEGER NOT NULL,
    xp INTEGER NOT NULL,
    PRIMARY KEY (game_id, user_id)
);
CREATE INDEX IF NOT EXISTS endless_results_by_user ON endless_results(user_id);
CREATE TABLE IF NOT EXISTS achievements (
    user_id INTEGER NOT NULL REFERENCES users(id),
    achievement_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    earned_at TEXT NOT NULL,
    PRIMARY KEY (user_id, achievement_id, tier)
);
CREATE TABLE IF NOT EXISTS coin_grants (
    id TEXT PRIMARY KEY,
    coins INTEGER NOT NULL,
    accounts INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);
"""
BIO_LIMIT = 160  # characters; server/moderation.py checks a bio before it's stored

# Columns added after the first release, applied to databases that predate them.
MIGRATIONS = {
    ("users", "avatar"): "ALTER TABLE users ADD COLUMN avatar TEXT NOT NULL DEFAULT ''",
    ("users", "xp"): "ALTER TABLE users ADD COLUMN xp INTEGER NOT NULL DEFAULT 0",
    ("users", "prestige"): "ALTER TABLE users ADD COLUMN prestige INTEGER NOT NULL DEFAULT 0",
    ("results", "xp"): "ALTER TABLE results ADD COLUMN xp INTEGER NOT NULL DEFAULT 0",
    ("results", "prestige"): "ALTER TABLE results ADD COLUMN prestige INTEGER NOT NULL DEFAULT 0",
    ("users", "bio"): "ALTER TABLE users ADD COLUMN bio TEXT NOT NULL DEFAULT ''",
    ("quote_log", "question_id"): "ALTER TABLE quote_log ADD COLUMN question_id TEXT NOT NULL DEFAULT ''",  # M6
    ("quote_log", "quote_ms"): "ALTER TABLE quote_log ADD COLUMN quote_ms INTEGER",  # M6
    ("games", "live"): "ALTER TABLE games ADD COLUMN live INTEGER NOT NULL DEFAULT 0",  # M6 live mode
    ("games", "endless"): "ALTER TABLE games ADD COLUMN endless INTEGER NOT NULL DEFAULT 0",  # M6 endless table
    **{("users", column): statement for column, statement in social.USER_COLUMNS.items()},  # M5
}


@dataclass(frozen=True)
class Award:
    """What one finished game paid a signed-in player."""

    coins: int
    xp: int
    prestige: int
    level_before: int
    level_after: int

    @property
    def level_up(self) -> int | None:
        return self.level_after if self.level_after > self.level_before else None


@dataclass(frozen=True)
class QuoteRecord:
    """One signed-in player's sealed quote for one round, with how far off it was: the raw
    material for anti-cheat later. mid_error is ln(midpoint / answer)."""

    round_no: int
    user_id: int | None
    name: str
    bid: Decimal
    ask: Decimal
    answer: Decimal
    mid_error: float
    fills: int
    question_id: str = ""  # which question, so a flag's review can show it
    quote_ms: int | None = None  # how long after quoting opened the quote was sealed


@dataclass(frozen=True)
class EndlessResult:
    """One signed-in player's round at the endless table. Points are split by who was on the
    other side of each fill, because winnings off the house bots pay coins at a lower rate."""

    user_id: int
    points: Decimal  # the whole round: fills plus any Best Quote bonus
    vs_people: Decimal  # fills against other people
    vs_house: Decimal  # fills against house bots
    trades: int
    best_quote: bool


# Endless-table payouts, per round (M6, Nov 10, 2026). Points won from people pay a coin each,
# like a game; points won off the house pay a quarter, so farming the bots isn't worth much.
# XP needs a quote or a trade, so sitting at the table earns nothing.
HOUSE_COIN_RATE = Decimal("0.25")
ENDLESS_XP_BASE = 5


def endless_award(result: EndlessResult) -> tuple[int, int]:
    """(coins, xp) for one endless round."""
    bonus = COINS_PER_BEST_QUOTE if result.best_quote else 0
    from_people = max(Decimal(0), result.points - result.vs_house)  # people's fills plus the bonus
    coins = int(from_people * COINS_PER_POSITIVE_POINT) + int(max(Decimal(0), result.vs_house) * HOUSE_COIN_RATE) + bonus
    xp = ENDLESS_XP_BASE + XP_PER_TRADE * result.trades + (XP_PER_BEST_QUOTE if result.best_quote else 0)
    return coins, xp


@dataclass(frozen=True)
class SeatRecord:
    """Everyone at a finished game's table, signed in or not, for the game log."""

    seat: str
    name: str
    user_id: int | None
    bot: bool
    rank: int
    points: Decimal


@dataclass(frozen=True)
class RoundRecord:
    round_no: int
    question: str
    unit: str
    answer: Decimal


@dataclass(frozen=True)
class FillRecord:
    """One trade of a finished game; the seller's points are the negative of the buyer's."""

    round_no: int
    seq: int
    price: Decimal
    size: int
    buyer: str  # seats
    seller: str
    buyer_points: Decimal


@dataclass(frozen=True)
class GameResult:
    user_id: int
    name: str
    points: Decimal
    positive_points: Decimal  # the sum of the rounds this player finished positive
    rank: int
    best_quotes: int
    trades: int


def coins_for(result: GameResult) -> int:
    return (
        int(result.positive_points) * COINS_PER_POSITIVE_POINT
        + COINS_FOR_FINISHING
        + (COINS_FOR_WINNING if result.rank == 1 else 0)
        + COINS_PER_BEST_QUOTE * result.best_quotes
    )


def xp_for(result: GameResult, rounds: int) -> int:
    return (
        XP_FOR_FINISHING
        + XP_PER_ROUND * rounds
        + XP_PER_TRADE * result.trades
        + XP_PER_BEST_QUOTE * result.best_quotes
    )


def prestige_for(result: GameResult) -> int:
    placing = PRESTIGE_FOR_WINNING if result.rank == 1 else PRESTIGE_FOR_PODIUM if result.rank in (2, 3) else 0
    return placing + PRESTIGE_PER_BEST_QUOTE * result.best_quotes


def level_for(xp: int) -> int:
    return math.isqrt(max(0, xp) // LEVEL_XP) + 1


def xp_for_level(level: int) -> int:
    return LEVEL_XP * (level - 1) ** 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        added = set()
        for (table, column), statement in MIGRATIONS.items():
            present = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in present:
                self.conn.execute(statement)
                added.add((table, column))
        if ("results", "xp") in added:
            self._backfill_progression()
        social.install(self.conn)  # friends, groups, notifications, reports; public ids
        from server import anticheat, players, push  # imported here: they import modules that import this one

        push.install(self.conn)  # devices subscribed to web push
        anticheat.install(self.conn)  # M6: accuracy flags for review
        players.install(self.conn)  # teammates who may open the players page
        self._rename_items()
        self._refund_retired()
        self._pay_grants()

    def _pay_grants(self) -> None:
        """Pays each grant in COIN_GRANTS that this database hasn't had yet: the coins to every
        account, and the record that it was paid, together or not at all."""
        paid = {row["id"] for row in self.conn.execute("SELECT id FROM coin_grants")}
        for name, coins in COIN_GRANTS.items():
            if name in paid:
                continue
            self.conn.execute("BEGIN")
            try:
                accounts = self.conn.execute("UPDATE users SET coins = coins + ?", (coins,)).rowcount
                self.conn.execute(
                    "INSERT INTO coin_grants (id, coins, accounts, applied_at) VALUES (?, ?, ?, ?)",
                    (name, coins, accounts, _stamp(_now())),
                )
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            log.info("coin grant %s: %d coins to each of %d accounts", name, coins, accounts)

    def _rename_items(self) -> None:
        """Moves inventories and worn avatars from a renamed item's old id to its new one."""
        for old, new in RENAMED_ITEMS.items():
            # Someone who somehow holds both keeps the new row.
            self.conn.execute(
                "DELETE FROM inventory WHERE item_id = ? AND user_id IN "
                "(SELECT user_id FROM inventory WHERE item_id = ?)",
                (old, new),
            )
            self.conn.execute("UPDATE inventory SET item_id = ? WHERE item_id = ?", (new, old))
        rows = self.conn.execute("SELECT id, avatar FROM users").fetchall()
        for row in rows:
            if not row["avatar"]:  # never dressed: NULL or an empty string
                continue
            avatar = json.loads(row["avatar"])
            moved = {
                slot: RENAMED_ITEMS.get(item, item) if isinstance(item, str) else item
                for slot, item in avatar.items()
            }
            if moved != avatar:
                self.conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (json.dumps(moved), row["id"]))

    def _refund_retired(self) -> None:
        """Gives back the coins for any item that can no longer be sold, then drops the row:
        items retired from the catalog, and items that have since been made free (most hair
        styles, Nov 4, 2026), so nobody stays out of pocket for something everyone gets."""
        free_now = {item.id for item in CATALOG if item.free}
        refundable = sorted(RETIRED_ITEMS | free_now)
        marks = ",".join("?" * len(refundable))
        rows = self.conn.execute(
            f"SELECT user_id, item_id, price FROM inventory WHERE item_id IN ({marks})",
            tuple(refundable),
        ).fetchall()
        for row in rows:
            self.conn.execute(
                "UPDATE users SET coins = coins + ? WHERE id = ?", (row["price"], row["user_id"])
            )
            self.conn.execute(
                "DELETE FROM inventory WHERE user_id = ? AND item_id = ?", (row["user_id"], row["item_id"])
            )
            log.info("refunded user=%s item=%s coins=%s", row["user_id"], row["item_id"], row["price"])

    def _backfill_progression(self) -> None:
        """Credits XP and prestige for games saved before progression existed, once, when the
        columns first appear, so nobody's history starts at level 1."""
        rows = self.conn.execute(
            "SELECT r.id, r.user_id, r.rank, r.best_quotes, r.trades, g.rounds "
            "FROM results r JOIN games g ON g.id = r.game_id"
        ).fetchall()
        for row in rows:
            result = GameResult(
                user_id=row["user_id"],
                name="",
                points=Decimal(0),
                positive_points=Decimal(0),
                rank=row["rank"],
                best_quotes=row["best_quotes"],
                trades=row["trades"],
            )
            xp, prestige = xp_for(result, row["rounds"]), prestige_for(result)
            self.conn.execute("UPDATE results SET xp = ?, prestige = ? WHERE id = ?", (xp, prestige, row["id"]))
            self.conn.execute(
                "UPDATE users SET xp = xp + ?, prestige = prestige + ? WHERE id = ?",
                (xp, prestige, row["user_id"]),
            )

    @staticmethod
    def _user(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "picture": row["picture"],
            "coins": row["coins"],
            "avatar": stored_avatar(json.loads(row["avatar"]) if row["avatar"] else None),
            "xp": row["xp"],
            "prestige": row["prestige"],
            "level": level_for(row["xp"]),
            "next_level_xp": xp_for_level(level_for(row["xp"]) + 1),
            "bio": row["bio"],
            "bio_hidden": bool(row["bio_hidden"]),  # reported, waiting for review (M5)
            "public_id": row["public_id"],
            "handle": row["handle"],
            "friend_code": row["friend_code"],
        }

    def set_bio(self, user_id: int, bio: str) -> dict | None:
        """Stores an already-cleaned bio (server/moderation.py checks it first)."""
        with self.lock:
            self.conn.execute("UPDATE users SET bio = ? WHERE id = ?", (bio[:BIO_LIMIT], user_id))
            return self._fetch_user(user_id)

    def lifetime(self, user_id: int) -> dict[str, float]:
        """A player's whole record, as achievement facts (server/achievements.py)."""
        with self.lock:
            ranks = [
                row["rank"]
                for row in self.conn.execute(
                    "SELECT rank FROM results WHERE user_id = ? ORDER BY id", (user_id,)
                )
            ]
            totals = self.conn.execute(
                "SELECT COALESCE(SUM(best_quotes), 0) AS best_quotes, COALESCE(SUM(trades), 0) AS trades "
                "FROM results WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            owned = self.conn.execute(
                "SELECT COUNT(*) AS items, COALESCE(SUM(price), 0) AS spent FROM inventory WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        streak = best_streak = 0
        for rank in ranks:
            streak = streak + 1 if rank == 1 else 0
            best_streak = max(best_streak, streak)
        return {
            "life_games": len(ranks),
            "life_wins": sum(1 for rank in ranks if rank == 1),
            "life_podiums": sum(1 for rank in ranks if rank <= 3),
            "life_win_streak": best_streak,
            "life_best_quotes": totals["best_quotes"],
            "life_trades": totals["trades"],
            "life_coins_spent": owned["spent"],
            "life_items_owned": owned["items"],
        }

    def earned_achievements(self, user_id: int) -> dict[tuple[str, str], str]:
        """(achievement id, tier) -> when it was earned."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT achievement_id, tier, earned_at FROM achievements WHERE user_id = ?", (user_id,)
            ).fetchall()
        return {(row["achievement_id"], row["tier"]): row["earned_at"] for row in rows}

    def award_achievements(
        self, user_id: int, tiers: Iterable[tuple[str, str, int, str | None]]
    ) -> list[tuple[str, str]]:
        """Records each (achievement, tier, coins, item) not already held and pays it, all in one
        transaction: the coins, and the item into the inventory at no cost. Returns the new ones."""
        new: list[tuple[str, str]] = []
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                stamp = _stamp(_now())
                for achievement_id, tier, coins, item_id in tiers:
                    inserted = self.conn.execute(
                        "INSERT OR IGNORE INTO achievements (user_id, achievement_id, tier, earned_at) "
                        "VALUES (?, ?, ?, ?)",
                        (user_id, achievement_id, tier, stamp),
                    ).rowcount
                    if not inserted:
                        continue
                    new.append((achievement_id, tier))
                    self.conn.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (coins, user_id))
                    if item_id:
                        self.conn.execute(
                            "INSERT OR IGNORE INTO inventory (user_id, item_id, price, bought_at) VALUES (?, ?, 0, ?)",
                            (user_id, item_id, stamp),
                        )
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        for achievement_id, tier in new:
            log.info("achievement user=%s id=%s tier=%s", user_id, achievement_id, tier)
        return new

    def _fetch_user(self, user_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user(row) if row else None

    def sign_in_google(self, sub: str, email: str, name: str, picture: str = "") -> tuple[dict, str]:
        """Finds or creates the user for a Google identity and opens a session."""
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.conn.execute("BEGIN")
            # New accounts start with the welcome coins; returning ones keep their balance.
            self.conn.execute(
                """
                INSERT INTO users (google_sub, email, name, picture, coins, created_at, public_id, friend_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(google_sub) DO UPDATE SET
                    email = excluded.email, name = excluded.name, picture = excluded.picture
                """,
                (sub, email, name, picture, WELCOME_COINS, _stamp(_now()), social.new_public_id(), social.new_friend_code()),
            )
            row = self.conn.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
            self.conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, row["id"], _stamp(_now() + timedelta(days=SESSION_DAYS))),
            )
            self.conn.execute("COMMIT")
        return self._user(row), token

    def user_for_session(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self.lock:
            row = self.conn.execute(
                """
                SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token = ? AND s.expires_at > ?
                """,
                (token, _stamp(_now())),
            ).fetchone()
        return self._user(row) if row else None

    def sign_out(self, token: str) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def record_game(
        self,
        room_code: str,
        rounds: int,
        player_count: int,
        results: list[GameResult],
        quotes: Iterable[QuoteRecord] = (),
        seats: Iterable[SeatRecord] = (),
        rounds_played: Iterable[RoundRecord] = (),
        fills: Iterable[FillRecord] = (),
        live: bool = False,
    ) -> dict[int, Award]:
        """Stores a finished game for its signed-in players and pays coins, XP and prestige.
        The table, its rounds and its trades go into the game log. Returns what each user was
        paid, with their level before and after."""
        awarded: dict[int, Award] = {}
        with self.lock:
            self.conn.execute("BEGIN")
            game_id = self.conn.execute(
                "INSERT INTO games (room_code, rounds, player_count, ended_at, live) VALUES (?, ?, ?, ?, ?)",
                (room_code, rounds, player_count, _stamp(_now()), int(live)),
            ).lastrowid
            self.conn.executemany(
                "INSERT INTO game_players (game_id, seat, name, user_id, bot, rank, points) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(game_id, s.seat, s.name, s.user_id, int(s.bot), s.rank, str(s.points)) for s in seats],
            )
            self.conn.executemany(
                "INSERT INTO game_rounds (game_id, round_no, question, unit, answer) VALUES (?, ?, ?, ?, ?)",
                [(game_id, r.round_no, r.question, r.unit, str(r.answer)) for r in rounds_played],
            )
            self.conn.executemany(
                "INSERT INTO game_fills (game_id, round_no, seq, price, size, buyer, seller, buyer_points) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (game_id, f.round_no, f.seq, str(f.price), f.size, f.buyer, f.seller, str(f.buyer_points))
                    for f in fills
                ],
            )
            for result in results:
                before = self.conn.execute(
                    "SELECT xp FROM users WHERE id = ?", (result.user_id,)
                ).fetchone()["xp"]
                award = Award(
                    coins=coins_for(result),
                    xp=xp_for(result, rounds),
                    prestige=prestige_for(result),
                    level_before=level_for(before),
                    level_after=level_for(before + xp_for(result, rounds)),
                )
                awarded[result.user_id] = award
                self.conn.execute(
                    """
                    INSERT INTO results
                        (game_id, user_id, name, points, rank, best_quotes, trades, coins, xp, prestige)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_id,
                        result.user_id,
                        result.name,
                        str(result.points),
                        result.rank,
                        result.best_quotes,
                        result.trades,
                        award.coins,
                        award.xp,
                        award.prestige,
                    ),
                )
                self.conn.execute(
                    "UPDATE users SET coins = coins + ?, xp = xp + ?, prestige = prestige + ? WHERE id = ?",
                    (award.coins, award.xp, award.prestige, result.user_id),
                )
            for quote in quotes:
                if quote.user_id is None:
                    continue
                self.conn.execute(
                    """
                    INSERT INTO quote_log
                        (game_id, round_no, user_id, bid, ask, answer, mid_error, fills, question_id, quote_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_id,
                        quote.round_no,
                        quote.user_id,
                        str(quote.bid),
                        str(quote.ask),
                        str(quote.answer),
                        quote.mid_error,
                        quote.fills,
                        quote.question_id,
                        quote.quote_ms,
                    ),
                )
            self.conn.execute("COMMIT")
        return awarded

    def record_endless_round(
        self,
        room_code: str,
        question: RoundRecord,
        player_count: int,
        results: list[EndlessResult],
        quotes: Iterable[QuoteRecord] = (),
    ) -> dict[int, tuple[int, int]]:
        """Saves one endless-table round and pays its coins and XP, in one transaction. The
        round is stored as a one-round game marked `endless`, so the quote log (and anti-cheat)
        and the review page read it like any other; it stays out of game history and lifetime
        stats, which read `results`. Returns (coins, xp) per user."""
        paid: dict[int, tuple[int, int]] = {}
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                game_id = self.conn.execute(
                    "INSERT INTO games (room_code, rounds, player_count, ended_at, endless) VALUES (?, 1, ?, ?, 1)",
                    (room_code, player_count, _stamp(_now())),
                ).lastrowid
                self.conn.execute(
                    "INSERT INTO game_rounds (game_id, round_no, question, unit, answer) VALUES (?, 1, ?, ?, ?)",
                    (game_id, question.question, question.unit, str(question.answer)),
                )
                for result in results:
                    coins, xp = endless_award(result)
                    paid[result.user_id] = (coins, xp)
                    self.conn.execute(
                        "INSERT INTO endless_results (game_id, user_id, points, vs_people, vs_house, trades, best_quote, coins, xp) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            game_id,
                            result.user_id,
                            str(result.points),
                            str(result.vs_people),
                            str(result.vs_house),
                            result.trades,
                            int(result.best_quote),
                            coins,
                            xp,
                        ),
                    )
                    self.conn.execute(
                        "UPDATE users SET coins = coins + ?, xp = xp + ? WHERE id = ?", (coins, xp, result.user_id)
                    )
                for quote in quotes:
                    if quote.user_id is None:
                        continue
                    self.conn.execute(
                        "INSERT INTO quote_log (game_id, round_no, user_id, bid, ask, answer, mid_error, fills, question_id, quote_ms) "
                        "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            game_id,
                            quote.user_id,
                            str(quote.bid),
                            str(quote.ask),
                            str(quote.answer),
                            quote.mid_error,
                            quote.fills,
                            quote.question_id,
                            quote.quote_ms,
                        ),
                    )
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return paid

    def history(self, user_id: int, before: int | None = None, limit: int = HISTORY_PAGE) -> dict:
        """Every game a player has finished, newest first, a page at a time. `before` is the
        last game id of the page already shown; `next` is the cursor for the page after this
        one, or None at the end. `winners` names whoever finished first (more than one on a tie),
        and is empty for games saved before the log kept the table."""
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT g.id AS game_id, g.room_code, g.ended_at, g.rounds, g.player_count, r.points,
                       r.rank, r.coins, r.xp, r.prestige, r.best_quotes, r.trades,
                       (SELECT group_concat(name, ', ') FROM game_players p
                        WHERE p.game_id = g.id AND p.rank = 1) AS winners
                FROM results r JOIN games g ON g.id = r.game_id
                WHERE r.user_id = ? AND (? IS NULL OR g.id < ?)
                ORDER BY g.id DESC LIMIT ?
                """,
                (user_id, before, before, limit + 1),
            ).fetchall()
            total = self.conn.execute(
                "SELECT COUNT(*) FROM results WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
        games = [{**dict(row), "winners": row["winners"] or ""} for row in rows[:limit]]
        more = len(rows) > limit
        return {"games": games, "total": total, "next": games[-1]["game_id"] if more else None}

    def game_detail(self, user_id: int, game_id: int) -> dict | None:
        """One past game from a player's side: the whole table, each round's question and
        answer, and that player's own trades with who was on the other side and what each
        scored. None unless they played in it. Games saved before the log existed have only the
        player's result (`detailed` is False)."""
        with self.lock:
            mine = self.conn.execute(
                "SELECT g.id, g.room_code, g.ended_at, g.rounds, g.player_count, r.points, r.rank, "
                "r.coins, r.xp, r.prestige FROM results r JOIN games g ON g.id = r.game_id "
                "WHERE r.user_id = ? AND r.game_id = ?",
                (user_id, game_id),
            ).fetchone()
            if mine is None:
                return None
            seats = self.conn.execute(
                "SELECT p.seat, p.name, p.user_id, p.bot, p.rank, p.points, u.public_id FROM game_players p "
                "LEFT JOIN users u ON u.id = p.user_id WHERE p.game_id = ? ORDER BY p.rank, p.name",
                (game_id,),
            ).fetchall()
            rounds = self.conn.execute(
                "SELECT round_no, question, unit, answer FROM game_rounds WHERE game_id = ? ORDER BY round_no",
                (game_id,),
            ).fetchall()
            fills = self.conn.execute(
                "SELECT round_no, seq, price, size, buyer, seller, buyer_points FROM game_fills "
                "WHERE game_id = ? ORDER BY round_no, seq",
                (game_id,),
            ).fetchall()
        names = {row["seat"]: row["name"] for row in seats}
        my_seat = next((row["seat"] for row in seats if row["user_id"] == user_id), None)
        by_round: dict[int, list[dict]] = defaultdict(list)
        for fill in fills:
            if my_seat not in (fill["buyer"], fill["seller"]):
                continue
            bought = fill["buyer"] == my_seat
            points = Decimal(fill["buyer_points"])
            by_round[fill["round_no"]].append(
                {
                    "side": "BUY" if bought else "SELL",
                    "price": fill["price"],
                    "size": fill["size"],
                    "counterparty": names.get(fill["seller"] if bought else fill["buyer"], "?"),
                    "points": str(points if bought else -points),
                }
            )
        return {
            "game": {key: mine[key] for key in mine.keys()},
            "detailed": bool(seats),
            "players": [
                {
                    "name": row["name"],
                    "rank": row["rank"],
                    "points": row["points"],
                    "bot": bool(row["bot"]),
                    "signed_in": row["user_id"] is not None,
                    "you": row["seat"] == my_seat,
                    # Links to their profile and the "Add friend" button (M5); with `user_id` so
                    # the API can add each relation, then drops it before answering.
                    "public_id": row["public_id"],
                    "user_id": row["user_id"],
                }
                for row in seats
            ],
            "rounds": [
                {
                    "round_no": row["round_no"],
                    "question": row["question"],
                    "unit": row["unit"],
                    "answer": row["answer"],
                    "fills": by_round.get(row["round_no"], []),
                }
                for row in rounds
            ],
        }

    def quote_history(self, user_id: int) -> list[dict]:
        """A player's logged quotes, newest first; what anti-cheat will read."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT game_id, round_no, bid, ask, answer, mid_error, fills FROM quote_log "
                "WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def inventory(self, user_id: int) -> list[str]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT item_id FROM inventory WHERE user_id = ? ORDER BY bought_at, item_id",
                (user_id,),
            ).fetchall()
        return [row["item_id"] for row in rows]

    def buy(self, user_id: int, item_id: str, price: int) -> dict:
        """Spends coins on one item. Raises ValueError with a player-facing reason."""
        return self.buy_many(user_id, {item_id: price}, price)

    def buy_many(self, user_id: int, prices: dict[str, int], total: int) -> dict:
        """Spends `total` coins on several items at once: all of them or none of them.

        `prices` maps each item id to the share recorded against it, which may add up to
        less than `total` when a bundle's rounding lands between them.
        """
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                marks = ",".join("?" * len(prices))
                owned = self.conn.execute(
                    f"SELECT item_id FROM inventory WHERE user_id = ? AND item_id IN ({marks})",
                    (user_id, *prices),
                ).fetchall()
                if owned:
                    raise ValueError("You already own that.")
                row = self.conn.execute("SELECT coins FROM users WHERE id = ?", (user_id,)).fetchone()
                if row is None:
                    raise ValueError("Unknown player.")
                if row["coins"] < total:
                    raise ValueError(f"You need {total - row['coins']} more coins for that.")
                self.conn.execute("UPDATE users SET coins = coins - ? WHERE id = ?", (total, user_id))
                stamp = _stamp(_now())
                for item_id, price in prices.items():
                    self.conn.execute(
                        "INSERT INTO inventory (user_id, item_id, price, bought_at) VALUES (?, ?, ?, ?)",
                        (user_id, item_id, price, stamp),
                    )
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            return self._fetch_user(user_id)

    def set_avatar(self, user_id: int, avatar: dict) -> dict | None:
        with self.lock:
            self.conn.execute(
                "UPDATE users SET avatar = ? WHERE id = ?", (json.dumps(avatar), user_id)
            )
            return self._fetch_user(user_id)

    def profile(self, user_id: int) -> dict | None:
        with self.lock:
            user = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None:
                return None
            totals = self.conn.execute(
                """
                SELECT COUNT(*) AS games,
                       COALESCE(SUM(CASE WHEN rank = 1 THEN 1 ELSE 0 END), 0) AS wins,
                       COALESCE(SUM(best_quotes), 0) AS best_quotes,
                       COALESCE(SUM(trades), 0) AS trades
                FROM results WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            points = self.conn.execute(
                "SELECT points FROM results WHERE user_id = ?", (user_id,)
            ).fetchall()
            recent = self.conn.execute(
                """
                SELECT g.id AS game_id, g.room_code, g.ended_at, g.rounds, g.player_count, r.points,
                       r.rank, r.coins, r.xp, r.prestige
                FROM results r JOIN games g ON g.id = r.game_id
                WHERE r.user_id = ? ORDER BY r.id DESC LIMIT ?
                """,
                (user_id, RECENT_GAMES),
            ).fetchall()
        return {
            "user": self._user(user),
            "games": totals["games"],
            "wins": totals["wins"],
            "best_quotes": totals["best_quotes"],
            "trades": totals["trades"],
            "total_points": str(sum((Decimal(row["points"]) for row in points), Decimal(0))),
            "recent": [dict(row) for row in recent],
        }
