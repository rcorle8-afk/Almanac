"""Anti-cheat (M6): flags players whose sealed quotes are too accurate to be estimates.

Every signed-in player's sealed quote has been logged since M3 (quote_log). A quote is a
bullseye when it holds the answer and is tight: ask no more than BULLSEYE_RATIO times the bid.
Honest estimators land those now and then; someone looking answers up lands them again and
again. After each saved game, every signed-in player in it is checked: with at least
MIN_QUOTES logged quotes, a binomial test asks how likely their bullseye count would be at the
rate everyone else hits them. Below ALPHA, the player is shadow-flagged: nothing changes for
them, they aren't told, and the flag waits on /admin/flags for review. Nothing is punished
automatically (spec, M6: "shadow-flag for review before any punishment").

Why a test against everyone else's rate and not a percentile (the spec's first wording): with a
few dozen regulars a top percentile always holds somebody, cheating or not. The test flags
nobody until the evidence is strong, and gets more exact as the player base grows.

A review clears a flag (a strong honest player) or confirms it. A cleared player is checked
again only on quotes made after the review, so the same evidence never flags them twice.
Confirming records the judgment; what follows from it (keeping them off live and public
leaderboards) arrives with live mode.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from server import social
from server.auth import current_user

if TYPE_CHECKING:
    from server.db import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS accuracy_flags (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL,
    quotes INTEGER NOT NULL,
    bullseyes INTEGER NOT NULL,
    baseline REAL NOT NULL,
    p_value REAL NOT NULL,
    after_quote_id INTEGER NOT NULL,
    last_quote_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS accuracy_flags_by_user ON accuracy_flags(user_id, id);
"""

MIN_QUOTES = 20  # logged quotes before a player is judged at all
BULLSEYE_RATIO = Decimal("1.25")  # a quote this tight that holds the answer
ALPHA = 0.001  # how unlikely a bullseye count must be, at everyone else's rate, to flag
# Everyone else's rate starts from a prior of 5 bullseyes in 100 quotes, so a small or brand-new
# player base can't make an ordinary run of luck look impossible.
PRIOR_HITS = 5
PRIOR_QUOTES = 100
QUOTES_SHOWN = 25
REVIEWED_SHOWN = 20
STATUSES = ("open", "cleared", "confirmed")


def install(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_bullseye(bid: str, ask: str, answer: str) -> bool:
    try:
        low, high, truth = Decimal(bid), Decimal(ask), Decimal(answer)
    except InvalidOperation:
        return False
    return low > 0 and low <= truth <= high and high <= low * BULLSEYE_RATIO


def binomial_tail(hits: int, trials: int, rate: float) -> float:
    """P(X >= hits) for X ~ Binomial(trials, rate), summed in log space so long records don't
    overflow."""
    if hits <= 0:
        return 1.0
    if rate <= 0:
        return 0.0
    if rate >= 1:
        return 1.0
    log_rate, log_miss = math.log(rate), math.log1p(-rate)
    terms = [
        math.lgamma(trials + 1) - math.lgamma(i + 1) - math.lgamma(trials - i + 1) + i * log_rate + (trials - i) * log_miss
        for i in range(hits, trials + 1)
    ]
    top = max(terms)
    return min(1.0, math.exp(top) * sum(math.exp(term - top) for term in terms))


def _baseline(conn: sqlite3.Connection, user_id: int) -> float:
    """Everyone else's bullseye rate, shrunk toward the prior."""
    rows = conn.execute("SELECT bid, ask, answer FROM quote_log WHERE user_id != ?", (user_id,)).fetchall()
    hits = sum(is_bullseye(r["bid"], r["ask"], r["answer"]) for r in rows)
    return (hits + PRIOR_HITS) / (len(rows) + PRIOR_QUOTES)


def _evidence(conn: sqlite3.Connection, user_id: int, after: int) -> tuple[int, int, int]:
    """(quotes, bullseyes, last quote id) for a player's quotes logged after `after`."""
    rows = conn.execute(
        "SELECT id, bid, ask, answer FROM quote_log WHERE user_id = ? AND id > ? ORDER BY id", (user_id, after)
    ).fetchall()
    hits = sum(is_bullseye(r["bid"], r["ask"], r["answer"]) for r in rows)
    return len(rows), hits, rows[-1]["id"] if rows else after


def review(db: Database, user_id: int) -> str | None:
    """Checks one player after a saved game. Returns "flagged" when this check opened a flag,
    "updated" when it refreshed the figures on an open or confirmed one, else None."""
    with db.lock:
        conn = db.conn
        latest = conn.execute(
            "SELECT * FROM accuracy_flags WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
        if latest is not None and latest["status"] in ("open", "confirmed"):
            quotes, hits, last = _evidence(conn, user_id, latest["after_quote_id"])
            rate = _baseline(conn, user_id)
            conn.execute(
                "UPDATE accuracy_flags SET quotes = ?, bullseyes = ?, baseline = ?, p_value = ?, last_quote_id = ?, "
                "updated_at = ? WHERE id = ?",
                (quotes, hits, rate, binomial_tail(hits, quotes, rate), last, _stamp(), latest["id"]),
            )
            return "updated"
        # A cleared flag's evidence is spent: only quotes since its review count now.
        after = latest["last_quote_id"] if latest is not None else 0
        quotes, hits, last = _evidence(conn, user_id, after)
        if quotes < MIN_QUOTES:
            return None
        rate = _baseline(conn, user_id)
        p_value = binomial_tail(hits, quotes, rate)
        if p_value >= ALPHA:
            return None
        now = _stamp()
        conn.execute(
            "INSERT INTO accuracy_flags (user_id, status, quotes, bullseyes, baseline, p_value, after_quote_id, "
            "last_quote_id, created_at, updated_at) VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, quotes, hits, rate, p_value, after, last, now, now),
        )
        return "flagged"


def _standing_among_regulars(conn: sqlite3.Connection, user_id: int) -> tuple[int, int] | None:
    """(how many other regular players have a lower bullseye rate, how many others there are).
    A regular has MIN_QUOTES or more logged quotes."""
    rows = conn.execute("SELECT user_id, bid, ask, answer FROM quote_log").fetchall()
    tally: dict[int, list[int]] = {}
    for r in rows:
        counts = tally.setdefault(r["user_id"], [0, 0])
        counts[0] += 1
        counts[1] += is_bullseye(r["bid"], r["ask"], r["answer"])
    rates = {uid: hits / total for uid, (total, hits) in tally.items() if total >= MIN_QUOTES}
    if user_id not in rates or len(rates) < 2:
        return None
    others = [rate for uid, rate in rates.items() if uid != user_id]
    return sum(rate < rates[user_id] for rate in others), len(others)


def _spread(bid: str, ask: str) -> float | None:
    """ask / bid, the quote's width: 1.04 is tight, 4.0 is a wide guess."""
    try:
        return round(float(Decimal(ask) / Decimal(bid)), 2)
    except (InvalidOperation, ZeroDivisionError):
        return None


def queue(db: Database) -> list[dict]:
    """Open flags first, then the most recently reviewed, each with the player's recent quotes."""
    with db.lock:
        conn = db.conn
        flags = conn.execute(
            "SELECT f.*, u.name, u.public_id, u.handle FROM accuracy_flags f JOIN users u ON u.id = f.user_id "
            "WHERE f.status = 'open' ORDER BY f.p_value, f.id"
        ).fetchall()
        reviewed = conn.execute(
            "SELECT f.*, u.name, u.public_id, u.handle FROM accuracy_flags f JOIN users u ON u.id = f.user_id "
            "WHERE f.status != 'open' ORDER BY f.reviewed_at DESC, f.id DESC LIMIT ?",
            (REVIEWED_SHOWN,),
        ).fetchall()
        items = []
        for flag in [*flags, *reviewed]:
            quotes = conn.execute(
                """
                SELECT q.bid, q.ask, q.answer, q.mid_error, q.quote_ms, q.round_no, g.ended_at, r.question, r.unit
                FROM quote_log q
                JOIN games g ON g.id = q.game_id
                LEFT JOIN game_rounds r ON r.game_id = q.game_id AND r.round_no = q.round_no
                WHERE q.user_id = ? AND q.id > ? ORDER BY q.id DESC LIMIT ?
                """,
                (flag["user_id"], flag["after_quote_id"], QUOTES_SHOWN),
            ).fetchall()
            standing = _standing_among_regulars(conn, flag["user_id"])
            items.append(
                {
                    "id": flag["id"],
                    "status": flag["status"],
                    "player": {"name": flag["name"], "public_id": flag["public_id"], "handle": flag["handle"]},
                    "quotes": flag["quotes"],
                    "bullseyes": flag["bullseyes"],
                    "rate": flag["bullseyes"] / flag["quotes"] if flag["quotes"] else 0,
                    "baseline": flag["baseline"],
                    "p_value": flag["p_value"],
                    # More accurate than `beats` of the `regulars` other players with enough quotes.
                    "beats": standing[0] if standing else None,
                    "regulars": standing[1] if standing else None,
                    "created_at": flag["created_at"],
                    "reviewed_at": flag["reviewed_at"],
                    "recent": [
                        {
                            "question": q["question"],
                            "unit": q["unit"],
                            "bid": q["bid"],
                            "ask": q["ask"],
                            "answer": q["answer"],
                            "bullseye": is_bullseye(q["bid"], q["ask"], q["answer"]),
                            "off_percent": round(100 * (math.exp(abs(q["mid_error"])) - 1), 1),
                            "spread": _spread(q["bid"], q["ask"]),
                            "seconds": round(q["quote_ms"] / 1000, 1) if q["quote_ms"] is not None else None,
                            "played": q["ended_at"],
                        }
                        for q in quotes
                    ],
                }
            )
    return items


def resolve(db: Database, flag_id: int, action: str) -> None:
    status = {"clear": "cleared", "confirm": "confirmed"}.get(action)
    if status is None:
        raise social.SocialError("Clear or confirm.")
    with db.lock:
        found = db.conn.execute("SELECT status FROM accuracy_flags WHERE id = ?", (flag_id,)).fetchone()
        if found is None:
            raise social.SocialError("No flag has that number.", 404)
        db.conn.execute(
            "UPDATE accuracy_flags SET status = ?, reviewed_at = ? WHERE id = ?", (status, _stamp(), flag_id)
        )


def standing(db: Database, user_id: int) -> str | None:
    """A player's latest flag status, for live mode to read: "open", "cleared", "confirmed",
    or None if never flagged."""
    with db.lock:
        row = db.conn.execute(
            "SELECT status FROM accuracy_flags WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
    return row["status"] if row else None


# HTTP: the review queue, for the accounts in ADMIN_EMAILS only.

router = APIRouter(prefix="/api/admin/flags")


def _admin(request: Request) -> None:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in first.")
    if not social.is_admin(user):
        raise HTTPException(403, "This page is for the admin.")


@router.get("")
def flags(request: Request) -> dict:
    _admin(request)
    return {"flags": queue(request.app.state.db), "min_quotes": MIN_QUOTES, "bullseye_ratio": str(BULLSEYE_RATIO)}


class Decision(BaseModel):
    action: str = Field(max_length=10)  # clear or confirm


@router.post("/{flag_id}")
def decide(flag_id: int, body: Decision, request: Request) -> dict:
    _admin(request)
    try:
        resolve(request.app.state.db, flag_id, body.action)
    except social.SocialError as error:
        raise HTTPException(error.status, str(error)) from error
    return {"ok": True}
