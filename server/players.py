"""The players page (Ryan, Nov 17, 2026): every signed-in account with its standing and its
record, for the people running Almanac. The report, who may see it, the Excel export, and the
HTTP API under /api/admin.

It is read live from the app's own database, so the numbers are current whenever the page is
opened and no player data is copied anywhere else.

Who may see it: the accounts in ADMIN_EMAILS, and teammates an admin adds by email on the page
itself (`team_access`). A teammate sees the table and can download it. Players' emails, the
accuracy flags and the team list are for admins only, and a teammate can change nothing.
"""

import io
import json
import logging
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from server import social
from server.auth import current_user
from server.cosmetics import stored_avatar
from server.db import Database, level_for

log = logging.getLogger("almanac.players")

SCHEMA = """
CREATE TABLE IF NOT EXISTS team_access (
    email TEXT PRIMARY KEY,
    added_by INTEGER REFERENCES users(id),
    added_at TEXT NOT NULL
);
"""
MAX_TEAM = 50
EMAIL_LIMIT = 254
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RECENT_DAYS = 7  # "this week" on the page: joined, or played, in the last seven days
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def install(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).isoformat(timespec="seconds")


# Who may see the page.


def on_team(db: Database, user: dict | None) -> bool:
    if user is None:
        return False
    with db.lock:
        found = db.conn.execute("SELECT 1 FROM team_access WHERE email = ?", (user["email"].lower(),)).fetchone()
    return found is not None


def may_view(db: Database, user: dict | None) -> bool:
    return social.is_admin(user) or on_team(db, user)


def team(db: Database) -> list[dict]:
    """The teammates with view access, oldest first, each with the account that email signs in
    to (if it has signed in yet) and who added it."""
    with db.lock:
        rows = db.conn.execute(
            "SELECT t.email, t.added_at, a.name AS added_by, "
            "(SELECT u.name FROM users u WHERE LOWER(u.email) = t.email LIMIT 1) AS account "
            "FROM team_access t LEFT JOIN users a ON a.id = t.added_by ORDER BY t.added_at, t.email"
        ).fetchall()
    return [dict(row) for row in rows]


def add_teammate(db: Database, admin: int, email: str) -> str:
    """Gives the Google account with this email view access. It needn't have signed in yet."""
    email = email.strip().lower()
    if len(email) > EMAIL_LIMIT or not EMAIL.match(email):
        raise social.SocialError("That doesn't look like an email address.")
    with db.lock:
        if db.conn.execute("SELECT 1 FROM team_access WHERE email = ?", (email,)).fetchone():
            return email
        if db.conn.execute("SELECT COUNT(*) FROM team_access").fetchone()[0] >= MAX_TEAM:
            raise social.SocialError(f"The team list holds up to {MAX_TEAM} people.")
        db.conn.execute("INSERT INTO team_access (email, added_by, added_at) VALUES (?, ?, ?)", (email, admin, _stamp()))
    log.info("team access added by user=%s", admin)
    return email


def remove_teammate(db: Database, admin: int, email: str) -> None:
    with db.lock:
        db.conn.execute("DELETE FROM team_access WHERE email = ?", (email.strip().lower(),))
    log.info("team access removed by user=%s", admin)


# The report.


def _by_user(conn: sqlite3.Connection, query: str) -> dict[int, sqlite3.Row]:
    return {row["user_id"]: row for row in conn.execute(query)}


def _within(stamp: str | None, since: datetime) -> bool:
    return bool(stamp) and datetime.fromisoformat(stamp) >= since


def report(db: Database, full: bool, now: datetime | None = None) -> dict:
    """Every account with its standing (level, XP, prestige, coins) and its record, and totals
    for the top of the page. `full` adds what only admins see: each player's email and their
    latest accuracy flag.

    A game here is a hosted or live game, as on a player's own profile; rounds at the open table
    are counted on their own, since each is saved as a one-round game."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=RECENT_DAYS)
    with db.lock:
        conn = db.conn
        users = conn.execute(
            "SELECT id, public_id, name, handle, email, avatar, xp, prestige, coins, created_at FROM users"
        ).fetchall()
        played = _by_user(
            conn,
            "SELECT r.user_id, COUNT(*) AS games, SUM(r.rank = 1) AS wins, SUM(r.rank <= 3) AS podiums, "
            "SUM(r.best_quotes) AS best_quotes, SUM(r.trades) AS trades, SUM(CAST(r.points AS REAL)) AS points, "
            "SUM(g.live) AS live_games, MAX(g.ended_at) AS last "
            "FROM results r JOIN games g ON g.id = r.game_id GROUP BY r.user_id",
        )
        at_open_table = _by_user(
            conn,
            "SELECT e.user_id, COUNT(*) AS rounds, MAX(g.ended_at) AS last "
            "FROM endless_results e JOIN games g ON g.id = e.game_id GROUP BY e.user_id",
        )
        owned = _by_user(conn, "SELECT user_id, COUNT(*) AS items, SUM(price) AS spent FROM inventory GROUP BY user_id")
        badges = _by_user(conn, "SELECT user_id, COUNT(*) AS held FROM achievements GROUP BY user_id")
        friends: Counter[int] = Counter()
        for pair in conn.execute("SELECT user_a, user_b FROM friendships"):
            friends.update((pair["user_a"], pair["user_b"]))
        groups: dict[int, list[str]] = {}
        for row in conn.execute(
            "SELECT m.user_id, g.name, g.name_hidden FROM group_members m JOIN groups g ON g.id = m.group_id "
            "ORDER BY g.name COLLATE NOCASE"
        ):
            # A reported name stays hidden here as everywhere else.
            groups.setdefault(row["user_id"], []).append(social.HIDDEN_GROUP_NAME if row["name_hidden"] else row["name"])
        flags = {}
        if full:
            flags = _by_user(
                conn,
                "SELECT f.user_id, f.status FROM accuracy_flags f "
                "WHERE f.id = (SELECT MAX(id) FROM accuracy_flags WHERE user_id = f.user_id)",
            )
        games_saved = conn.execute("SELECT COUNT(*) FROM games WHERE endless = 0").fetchone()[0]
        open_rounds = conn.execute("SELECT COUNT(*) FROM games WHERE endless = 1").fetchone()[0]

    players = []
    for user in users:
        record, table = played.get(user["id"]), at_open_table.get(user["id"])
        last = max(filter(None, (record and record["last"], table and table["last"])), default=None)
        player = {
            "public_id": user["public_id"],
            "name": user["name"],
            "handle": user["handle"],
            "avatar": stored_avatar(json.loads(user["avatar"]) if user["avatar"] else None),
            "joined": user["created_at"],
            "last_played": last,
            "level": level_for(user["xp"]),
            "xp": user["xp"],
            "prestige": user["prestige"],
            "coins": user["coins"],
            "games": record["games"] if record else 0,
            "wins": record["wins"] if record else 0,
            "podiums": record["podiums"] if record else 0,
            "best_quotes": record["best_quotes"] if record else 0,
            "trades": record["trades"] if record else 0,
            "points": round(record["points"], 2) if record else 0,
            "live_games": record["live_games"] if record else 0,
            "open_rounds": table["rounds"] if table else 0,
            "coins_spent": owned[user["id"]]["spent"] if user["id"] in owned else 0,
            "items": owned[user["id"]]["items"] if user["id"] in owned else 0,
            "badges": badges[user["id"]]["held"] if user["id"] in badges else 0,
            "friends": friends[user["id"]],
            "groups": groups.get(user["id"], []),
        }
        if full:
            player["email"] = user["email"]
            player["flag"] = flags[user["id"]]["status"] if user["id"] in flags else None
        players.append(player)
    players.sort(key=lambda p: (-p["prestige"], -p["xp"], p["name"].casefold()))
    return {
        "as_of": _stamp(now),
        "recent_days": RECENT_DAYS,
        "summary": {
            "accounts": len(players),
            "new_recently": sum(_within(p["joined"], since) for p in players),
            "played_recently": sum(_within(p["last_played"], since) for p in players),
            "played_ever": sum(p["last_played"] is not None for p in players),
            "games": games_saved,
            "open_rounds": open_rounds,
            "coins": sum(p["coins"] for p in players),
        },
        "players": players,
    }


# The Excel file.

# (heading, key or how to work the value out, number format, column width)
COLUMNS = [
    ("Player", "name", None, 22),
    ("Handle", lambda p: f"@{p['handle']}" if p["handle"] else "", None, 16),
    ("Email", "email", None, 28),  # admins' downloads only
    ("Joined", "joined", "yyyy-mm-dd", 12),
    ("Last played", "last_played", "yyyy-mm-dd", 12),
    ("Level", "level", "0", 8),
    ("XP", "xp", "#,##0", 9),
    ("Prestige", "prestige", "#,##0", 10),
    ("Coins", "coins", "#,##0", 10),
    ("Games", "games", "0", 8),
    ("Wins", "wins", "0", 8),
    ("Win rate", lambda p: p["wins"] / p["games"] if p["games"] else None, "0%", 10),
    ("Podiums", "podiums", "0", 9),
    ("Best Quotes", "best_quotes", "0", 12),
    ("Trades", "trades", "#,##0", 9),
    ("Points", "points", "#,##0.00", 11),
    ("Live games", "live_games", "0", 11),
    ("Open-table rounds", "open_rounds", "#,##0", 17),
    ("Coins spent", "coins_spent", "#,##0", 12),
    ("Items owned", "items", "0", 12),
    ("Badges", "badges", "0", 9),
    ("Friends", "friends", "0", 9),
    ("Groups", lambda p: ", ".join(p["groups"]), None, 30),
    ("Accuracy flag", "flag", None, 14),  # admins' downloads only
    ("Profile", lambda p, site="": f"{site}/u/{p['public_id']}", None, 40),
]
ADMIN_COLUMNS = {"Email", "Accuracy flag"}
DATE_COLUMNS = {"Joined", "Last played"}


def workbook(data: dict, site: str = "", exported_by: str = "") -> bytes:
    """The report as an .xlsx: a Players sheet (one row each, a frozen, filterable header, real
    numbers and dates) and a Summary sheet. Columns only admins see are left out unless the
    report has them. Text is always written as text, so a player's name that starts with "="
    can't arrive in Excel as a formula."""
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    def put(sheet, row: int, column: int, value, number_format: str | None = None):
        cell = sheet.cell(row=row, column=column)
        if isinstance(value, str):
            cell.value = ILLEGAL_CHARACTERS_RE.sub("", value)
            cell.data_type = "s"  # never a formula, whatever it starts with
        else:
            cell.value = value
            if number_format:
                cell.number_format = number_format
        return cell

    players = data["players"]
    full = bool(players) and "email" in players[0]
    columns = [column for column in COLUMNS if full or column[0] not in ADMIN_COLUMNS]

    book = Workbook()
    sheet = book.active
    sheet.title = "Players"
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", start_color="1F5FD6")
    for index, (heading, _, _, width) in enumerate(columns, start=1):
        cell = put(sheet, 1, index, heading)
        cell.font, cell.fill = head, fill
        cell.alignment = Alignment(vertical="center")
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row, player in enumerate(players, start=2):
        for index, (heading, source, number_format, _) in enumerate(columns, start=1):
            if heading == "Profile":
                value = source(player, site)
            elif callable(source):
                value = source(player)
            else:
                value = player.get(source)
            if heading in DATE_COLUMNS and value:
                value = datetime.fromisoformat(value).date()
            if value is None:
                continue
            put(sheet, row, index, value, number_format)
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(2, len(players) + 1)}"

    summary = book.create_sheet("Summary")
    totals = data["summary"]
    days = data["recent_days"]
    lines = [
        ("Almanac players", None),
        ("Exported (UTC)", data["as_of"].replace("T", " ")[:19]),
        ("Exported by", exported_by),
        (None, None),
        ("Accounts", totals["accounts"]),
        (f"New in the last {days} days", totals["new_recently"]),
        (f"Played in the last {days} days", totals["played_recently"]),
        ("Have played at least once", totals["played_ever"]),
        ("Games saved (hosted and live)", totals["games"]),
        ("Open-table rounds", totals["open_rounds"]),
        ("Coins held by all players", totals["coins"]),
    ]
    for row, (label, value) in enumerate(lines, start=1):
        if label is not None:
            put(summary, row, 1, label).font = Font(bold=row == 1, size=14 if row == 1 else 11)
        if value is not None:
            put(summary, row, 2, value, "#,##0")
    summary.column_dimensions["A"].width = 34
    summary.column_dimensions["B"].width = 24

    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


# HTTP. Reading needs an admin or a teammate; the team list is the admins' alone.

router = APIRouter(prefix="/api/admin")


def require_viewer(request: Request) -> tuple[dict, bool]:
    """(the signed-in account, whether it is an admin), or a refusal."""
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in first.")
    admin = social.is_admin(user)
    if not admin and not on_team(request.app.state.db, user):
        raise HTTPException(403, "This page is for the Almanac team.")
    return user, admin


def _admin(request: Request) -> dict:
    user, admin = require_viewer(request)
    if not admin:
        raise HTTPException(403, "Only an admin can change who sees this page.")
    return user


@router.get("/players")
def players(request: Request, response: Response) -> dict:
    _, admin = require_viewer(request)
    response.headers["Cache-Control"] = "no-store"
    return {"viewer": {"admin": admin}, **report(request.app.state.db, full=admin)}


@router.get("/players.xlsx")
def players_file(request: Request) -> Response:
    user, admin = require_viewer(request)
    data = report(request.app.state.db, full=admin)
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    site = f"{scheme}://{request.headers.get('host', request.url.netloc)}"
    body = workbook(data, site=site, exported_by=user["name"])
    log.info("players exported by user=%s rows=%d full=%s", user["id"], len(data["players"]), admin)
    return Response(
        body,
        media_type=XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="almanac-players-{data["as_of"][:10]}.xlsx"',
            "Cache-Control": "no-store",
        },
    )


class Teammate(BaseModel):
    email: str = Field(min_length=3, max_length=EMAIL_LIMIT)


@router.get("/team")
def team_list(request: Request) -> dict:
    _admin(request)
    return {"team": team(request.app.state.db), "admins": sorted(social.admin_emails()), "max": MAX_TEAM}


@router.post("/team")
def team_add(body: Teammate, request: Request) -> dict:
    admin = _admin(request)
    try:
        add_teammate(request.app.state.db, admin["id"], body.email)
    except social.SocialError as error:
        raise HTTPException(error.status, str(error)) from error
    return {"team": team(request.app.state.db)}


@router.delete("/team/{email}")
def team_remove(email: str, request: Request) -> dict:
    admin = _admin(request)
    remove_teammate(request.app.state.db, admin["id"], email)
    return {"team": team(request.app.state.db)}
