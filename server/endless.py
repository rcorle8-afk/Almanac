"""The endless table (M6, Nov 10, 2026): one room that never ends, open to anyone, any time.

The room logic lives in server/rooms.py (`Room.make_endless`, the house bots, `save_endless_round`);
this module is its page's API and its leaderboards. Rounds are scored and paid one at a time,
so the boards add up each signed-in player's points over today and this week, Eastern time.
Anyone whose latest accuracy flag is confirmed is left off them, as on the live tables.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from server import social
from server.auth import current_user
from server.live import LIVE_ZONE, _confirmed
from server.rooms import ENDLESS_CODE, HOUSE_TRADERS, Phase

if TYPE_CHECKING:
    from server.db import Database
    from server.rooms import Hub

BOARD_SHOWN = 15


def day_start(now: datetime) -> datetime:
    """Midnight Eastern today, as a UTC moment."""
    local = now.astimezone(LIVE_ZONE)
    return datetime.combine(local.date(), time(0), tzinfo=LIVE_ZONE).astimezone(timezone.utc)


def week_start(now: datetime) -> datetime:
    """Midnight Eastern on this week's Monday, as a UTC moment."""
    local = now.astimezone(LIVE_ZONE)
    monday = local.date() - timedelta(days=local.weekday())
    return datetime.combine(monday, time(0), tzinfo=LIVE_ZONE).astimezone(timezone.utc)


def board(db: Database, since: datetime, viewer: int | None = None) -> dict:
    """Points at the endless table since `since`, best first: the top BOARD_SHOWN, and the
    viewer's own row and place if they played."""
    stamp = since.isoformat(timespec="seconds")
    with db.lock:
        conn = db.conn
        rows = conn.execute(
            """
            SELECT r.user_id, SUM(CAST(r.points AS REAL)) AS points, COUNT(*) AS rounds
            FROM endless_results r JOIN games g ON g.id = r.game_id
            WHERE g.endless = 1 AND g.ended_at >= ?
            GROUP BY r.user_id
            """,
            (stamp,),
        ).fetchall()
        hidden = _confirmed(conn)
        rows = sorted((row for row in rows if row["user_id"] not in hidden), key=lambda row: -row["points"])
        ids = [row["user_id"] for row in rows[:BOARD_SHOWN]]
        mine = next((i for i, row in enumerate(rows) if row["user_id"] == viewer), None)
        if mine is not None:
            ids.append(rows[mine]["user_id"])
        cards = social._cards(conn, ids)

    def entry(index: int) -> dict:
        row = rows[index]
        card = cards[row["user_id"]]
        return {
            "place": index + 1,
            "name": card["name"],
            "public_id": card["public_id"],
            "avatar": card["avatar"],
            "points": round(row["points"], 2),
            "rounds": row["rounds"],
        }

    return {
        "top": [entry(i) for i in range(min(BOARD_SHOWN, len(rows)))],
        "you": entry(mine) if mine is not None else None,
        "players": len(rows),
    }


def router_for(hub: Hub) -> APIRouter:
    router = APIRouter(prefix="/api/open")

    @router.get("")
    def overview(request: Request) -> dict:
        """What /open shows: who's at the table right now, and today's and this week's boards."""
        db = request.app.state.db
        user = current_user(request)
        viewer = user["id"] if user else None
        room = hub.rooms.get(ENDLESS_CODE)
        people = len(room.connected_humans) if room else 0
        bots = sum(1 for player in room.players if player.is_bot) if room else 0
        now = datetime.now(timezone.utc)
        return {
            "code": ENDLESS_CODE,
            "people": people,
            "bots": bots,
            "house_traders": HOUSE_TRADERS,
            "running": room is not None and room.phase is not Phase.LOBBY,
            "round_no": room.round_no if room else 0,
            "signed_in": user is not None,
            "today": board(db, day_start(now), viewer),
            "week": board(db, week_start(now), viewer),
        }

    return router
