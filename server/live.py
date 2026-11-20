"""Live mode (M6): one game a night that everyone signed in can join.

Decided by Ryan on Nov 10, 2026: a short game of LIVE_ROUNDS questions, quotes and trading as
usual, every evening at LIVE_HOUR o'clock Eastern, for signed-in accounts only. The server runs
it with no host: LOBBY_MINUTES before the start it opens the room under the reserved code
LIVE_CODE, the lobby counts down, the room's own timer starts the game (or calls it off if fewer
than two have come), and the room's timers run every phase after that. The finished game is
saved like any other, marked live, and /live shows the countdown, a Join button, the last live
game's table and the all-time live standings. Anyone with a confirmed accuracy flag
(server/anticheat.py) is left off both tables; that is the whole penalty, as decided.

LIVE_MODE=0 turns the nightly room off (tests, local work).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request

from server import social
from server.auth import current_user
from server.protocol import RoomConfig

if TYPE_CHECKING:
    from server.db import Database
    from server.rooms import Hub

log = logging.getLogger("almanac")

LIVE_CODE = "LIVE"  # never a word room code: the word list has no LIVE and random codes have no I
LIVE_ZONE = ZoneInfo("America/New_York")
LIVE_HOUR = 21
LIVE_ROUNDS = 5
LOBBY_MINUTES = 10
STANDINGS_SHOWN = 20


def enabled() -> bool:
    return os.environ.get("LIVE_MODE", "1") != "0"


def live_config() -> RoomConfig:
    """Five standard questions at the standard pace; case questions stay out, since their longer
    read and trade would double the length of a game meant to be quick."""
    return RoomConfig(rounds=LIVE_ROUNDS, case_mode="off", recall_on_start=True)


def next_start(now: datetime) -> datetime:
    """The next live start at or after `now`: today at LIVE_HOUR Eastern, or tomorrow's. Eastern
    time follows daylight saving, so the UTC hour moves twice a year."""
    local = now.astimezone(LIVE_ZONE)
    today = datetime.combine(local.date(), time(LIVE_HOUR), tzinfo=LIVE_ZONE)
    return today if local < today else datetime.combine(local.date() + timedelta(days=1), time(LIVE_HOUR), tzinfo=LIVE_ZONE)


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


async def run(hub: Hub, now: Callable[[], datetime] = lambda: datetime.now(LIVE_ZONE)) -> None:
    """Forever: wait for the lobby to open, open it, wait out the start, repeat. A server that
    restarts during the lobby opens it again at once; one that restarts mid-game loses that game.

    LIVE_DEV_START_SECONDS (local testing only, like ALLOW_DEV_LOGIN; never on a deployed
    server) opens a lobby at once whose game starts that many seconds after the server does."""
    dev_start = os.environ.get("LIVE_DEV_START_SECONDS")
    if dev_start:
        start = now() + timedelta(seconds=float(dev_start))
        await hub.open_live(LIVE_CODE, live_config(), ms(start))
        await asyncio.sleep(max(0.0, (start - now()).total_seconds()) + 60)
    while True:
        try:
            start = next_start(now())
            opens = start - timedelta(minutes=LOBBY_MINUTES)
            await asyncio.sleep(max(0.0, (opens - now()).total_seconds()))
            await hub.open_live(LIVE_CODE, live_config(), ms(start))
            await asyncio.sleep(max(0.0, (start - now()).total_seconds()) + 60)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("live scheduler failed; trying again in a minute")
            await asyncio.sleep(60)


# Tables.


def _confirmed(conn) -> set[int]:
    rows = conn.execute(
        "SELECT user_id FROM accuracy_flags f WHERE status = 'confirmed' AND id = "
        "(SELECT MAX(id) FROM accuracy_flags WHERE user_id = f.user_id)"
    ).fetchall()
    return {row["user_id"] for row in rows}


def last_game(db: Database) -> dict | None:
    """The latest live game's table, without anyone confirmed as looking answers up; places are
    counted again without them."""
    with db.lock:
        conn = db.conn
        game = conn.execute("SELECT id, ended_at, rounds, player_count FROM games WHERE live = 1 ORDER BY id DESC LIMIT 1").fetchone()
        if game is None:
            return None
        rows = conn.execute(
            "SELECT user_id, name, rank, points FROM game_players WHERE game_id = ? AND bot = 0 ORDER BY rank, name", (game["id"],)
        ).fetchall()
        hidden = _confirmed(conn)
        shown = [row for row in rows if row["user_id"] not in hidden]
        cards = social._cards(conn, [row["user_id"] for row in shown if row["user_id"] is not None])
    table = []
    for row in shown:
        card = cards.get(row["user_id"], {})
        place = 1 + sum(1 for other in shown if float(other["points"]) > float(row["points"]))
        table.append(
            {
                "place": place,
                "name": card.get("name", row["name"]),
                "public_id": card.get("public_id"),
                "avatar": card.get("avatar"),
                "prestige": card.get("prestige"),
                "points": row["points"],
            }
        )
    return {"ended_at": game["ended_at"], "rounds": game["rounds"], "players": len(rows), "table": table}


def standings(db: Database) -> list[dict]:
    """Everyone's live record, most wins first, then most points: the all-time live board."""
    with db.lock:
        conn = db.conn
        rows = conn.execute(
            """
            SELECT p.user_id, COUNT(*) AS games, SUM(CASE WHEN p.rank = 1 THEN 1 ELSE 0 END) AS wins,
                   SUM(CAST(p.points AS REAL)) AS points
            FROM game_players p JOIN games g ON g.id = p.game_id
            WHERE g.live = 1 AND p.user_id IS NOT NULL AND p.bot = 0
            GROUP BY p.user_id
            """
        ).fetchall()
        hidden = _confirmed(conn)
        rows = [row for row in rows if row["user_id"] not in hidden]
        rows.sort(key=lambda row: (-row["wins"], -row["points"]))
        rows = rows[:STANDINGS_SHOWN]
        cards = social._cards(conn, [row["user_id"] for row in rows])
    return [
        {
            "name": cards[row["user_id"]]["name"],
            "public_id": cards[row["user_id"]]["public_id"],
            "avatar": cards[row["user_id"]]["avatar"],
            "prestige": cards[row["user_id"]]["prestige"],
            "games": row["games"],
            "wins": row["wins"],
            "points": round(row["points"], 2),
        }
        for row in rows
    ]


# HTTP.


def router_for(hub: Hub) -> APIRouter:
    router = APIRouter(prefix="/api/live")

    @router.get("")
    def overview(request: Request) -> dict:
        """What /live shows: the next start, tonight's room if it's open, and the tables."""
        db = request.app.state.db
        start = next_start(datetime.now(LIVE_ZONE))
        room = hub.rooms.get(LIVE_CODE)
        tonight = None
        if room is not None and room.live:
            tonight = {
                "code": room.code,
                "phase": room.phase.value,
                "round_no": room.round_no,
                "rounds_total": room.config.rounds,
                "players": len(room.humans),
                "starts_at": room.starts_at,
                "cancelled": room.cancelled,
            }
        return {
            "on": enabled(),
            "zone": "ET",
            "hour": LIVE_HOUR,
            "rounds": LIVE_ROUNDS,
            "lobby_minutes": LOBBY_MINUTES,
            "next_start": ms(start),
            "room": tonight,
            "signed_in": current_user(request) is not None,
            "last": last_game(db),
            "standings": standings(db),
        }

    return router
