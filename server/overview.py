"""The overview page (Ryan, Nov 17, 2026): how Almanac is put together, what it runs on and what
is planned, on one page for the admins and teammates working on it.

Three kinds of thing are on it:

- The app's structure, written out here: the layers and what sits in each (LAYERS), every page
  (PAGES), every server module (MODULES) and every database table (TABLES). Tests check each
  list against the code, so a new page, module or table can't be added without it.
- Plans, services and tool versions, from server/overview_data.json. tools/dashboard/refresh.py
  writes that file from the same sources that feed Ryan's dashboard (progress.json,
  services.json, the development log's goals), and it ships with the code, so it is as current
  as the last deploy. Nothing from the log's "Relevant Information" section is ever in it.
- What is true right now, read from the running server: when it started, the build it serves,
  rooms open, accounts, how big each table is, and which optional features are switched on.
  A switch is shown as on or off, never as a key or a secret's value.

Open to the same people as the players page: admins, and the teammates they've added. Only
admins see emails.
"""

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Request, Response

from server import auth, live, players, social
from server.db import Database
from server.questions.validate import BANK_PATH
from server.rooms import Hub, Phase

HERE = Path(__file__).resolve().parent
DATA = HERE / "overview_data.json"
CLIENT_INDEX = HERE.parent / "client" / "dist" / "index.html"
STARTED_AT = datetime.now(timezone.utc)
STARTED = time.monotonic()

# The structure, top to bottom: who opens what, what runs, where things are kept, what the app
# reaches outside for, and what is run by hand. The outside services' parts come from the data
# file, so that layer has none here. `link` is what joins a layer to the one under it.
LAYERS = [
    {
        "id": "screens",
        "name": "Screens",
        "about": "What people open in a browser. There is nothing to install.",
        "parts": [
            {"name": "A player's phone", "about": "The main menu, a seat at a table, the locker, the marketplace and the profile.", "where": "/ and /play"},
            {"name": "The host screen", "about": "A laptop or TV running a room: the code to join, the book, the tape and the scores.", "where": "/host"},
            {"name": "Team pages", "about": "The players table, this overview, and the admins' two review queues.", "where": "/admin/..."},
        ],
        "link": "Pages and /api calls over HTTPS, and one WebSocket (/ws) for each screen at a table",
    },
    {
        "id": "app",
        "name": "The app",
        "about": "One Python process on one machine. It hands out the client and runs every game.",
        "parts": [
            {"name": "Client", "about": "React and TypeScript, built by Vite into static files the server hands out.", "where": "client/src"},
            {"name": "Game", "about": "Rooms, the round's phases and timers, bots, the order book and scoring.", "where": "rooms.py, engine/, protocol.py"},
            {"name": "Accounts and progression", "about": "Google sign-in, sessions, coins, XP and prestige, avatars, the marketplace, achievements.", "where": "auth.py, db.py, cosmetics.py, shop.py, achievements.py"},
            {"name": "Social", "about": "Friends, groups, invites, the bell, phone notifications and reports.", "where": "social.py, social_api.py, push.py, images.py, moderation.py"},
            {"name": "Crowd modes", "about": "The nightly live game, the open table, and the accuracy flags that guard them.", "where": "live.py, endless.py, anticheat.py"},
            {"name": "Team tools", "about": "The players page and this overview.", "where": "players.py, overview.py"},
        ],
        "link": "Reads and writes one database file; games in progress stay in memory",
    },
    {
        "id": "data",
        "name": "Data",
        "about": "Where things are kept.",
        "parts": [
            {"name": "Database", "about": "SQLite, one file on a volume: accounts, saved games and everything social. Snapshotted before each deploy.", "where": "/data/almanac.db"},
            {"name": "Live rooms", "about": "Games in progress, in the server's memory. A restart ends them, so deploys wait for an empty table.", "where": "memory"},
            {"name": "Question bank", "about": "Every question with its answer, source and verification, shipped with the code.", "where": "server/questions/questions.json"},
        ],
        "link": "The running app reaches outside for three things: hosting, sign-in and notifications",
    },
    {
        "id": "services",
        "name": "Outside services",
        "about": "What Almanac relies on that someone else runs. Details are under Services.",
        "parts": [],
        "link": "",
    },
    {
        "id": "offline",
        "name": "Offline tools",
        "about": "Run by hand from a developer's machine. The game server never runs them.",
        "parts": [
            {"name": "Question verifier", "about": "Researches each question with the Claude API and marks the ones that pass its evidence checks.", "where": "server/questions/verify.py"},
            {"name": "Dashboard refresh", "about": "Rebuilds the figures behind Ryan's dashboard and the plans on this page.", "where": "tools/dashboard/refresh.py"},
            {"name": "Deploy", "about": "flyctl builds the image and swaps the machine, after a snapshot of the volume.", "where": "Dockerfile, fly.toml"},
        ],
        "link": "",
    },
]
# How each kind of outside service connects, by its category in services.json.
SERVICE_USE = {
    "Hosting": "Runs the app",
    "Sign-in": "Called by the app",
    "Notifications": "Called by the app",
    "Build": "Used when deploying",
    "Question research": "Used by the offline verifier",
    "Development": "Used to build the project",
}

# Every page. `access`: everyone, signed_in, team (admins and teammates) or admin.
PAGES = [
    {"path": "/", "name": "Main menu", "about": "Social, Play and Customization as three screens; joining a room by code.", "access": "everyone"},
    {"path": "/play", "name": "A seat at a table", "about": "The phone's game: quote, trade, scores, with the locker and shop a tap away.", "access": "everyone"},
    {"path": "/host", "name": "Host screen", "about": "Opens and runs a room on a big screen; settings, bots and the group invite.", "access": "everyone"},
    {"path": "/open", "name": "The open table", "about": "The table that never closes, with today's and this week's boards.", "access": "everyone"},
    {"path": "/live", "name": "Live game", "about": "The nightly 9 PM Eastern game: countdown, lobby and standings. Playing needs a sign-in.", "access": "everyone"},
    {"path": "/leaderboard", "name": "Leaderboard", "about": "The top fifty groups and players by prestige.", "access": "signed_in"},
    {"path": "/profile", "name": "Profile", "about": "Your stats, level, bio, badges, handle, notifications and sign-out.", "access": "signed_in"},
    {"path": "/profile/games", "name": "Game history", "about": "Every game you've finished, and each one's table, rounds and your trades.", "access": "signed_in"},
    {"path": "/profile/achievements", "name": "Achievements", "about": "Every tier, what it takes and what it pays.", "access": "signed_in"},
    {"path": "/locker", "name": "Locker room", "about": "Dress your avatar and pick a banner from what you own.", "access": "signed_in"},
    {"path": "/shop", "name": "Marketplace", "about": "Buy avatar items, banners and bundles with coins.", "access": "signed_in"},
    {"path": "/academia", "name": "Academia", "about": "The banners earned by level and by prestige.", "access": "signed_in"},
    {"path": "/u/", "name": "A player's public profile", "about": "What others see of an account, with Add friend and Report.", "access": "signed_in"},
    {"path": "/g/", "name": "A group's page", "about": "Members, invites, Play now and customization. An invite link shows a preview to anyone.", "access": "signed_in"},
    {"path": "/admin/players", "name": "Players", "about": "Every account with its standing and record, and the Excel download.", "access": "team"},
    {"path": "/admin/overview", "name": "Overview", "about": "This page.", "access": "team"},
    {"path": "/admin/reports", "name": "Reports", "about": "Reported bios, group names and pictures, to restore or remove.", "access": "admin"},
    {"path": "/admin/flags", "name": "Accuracy flags", "about": "Players whose quotes are too accurate to be luck, to clear or confirm.", "access": "admin"},
]
# Old addresses the client still answers, and the page each one opens.
PAGE_ALIASES = {"/road": "/academia", "/social": "/"}

# Every module in server/, by file or folder. Listed in the order it is easiest to read them.
MODULES = {
    "app.py": "The entry point: the /ws endpoint, every router, and handing out the built client.",
    "rooms.py": "Rooms: the registry, the round's phases and timers, bots, snapshots, and saving finished games.",
    "protocol.py": "Every WebSocket message as a pydantic type. Mirrored by hand in client/src/lib/types.ts.",
    "engine/": "The order book and the scoring. Pure: no I/O, no clock, no randomness.",
    "room_codes.py": "The four-letter words rooms are named with.",
    "questions/": "The question bank, its validator, and the offline verifier.",
    "db.py": "SQLite: accounts, sessions, saved games, coins, XP and prestige, the inventory.",
    "auth.py": "Google sign-in, the session cookie, /api/me and /api/profile.",
    "cosmetics.py": "The avatar catalog: slots, items, bundles, and the index that sets each price.",
    "shop.py": "The marketplace and locker API: buy, equip, the catalog.",
    "achievements.py": "Achievements: tiers, what each takes, what each pays.",
    "social.py": "Friends, blocks, groups, notifications, reports and the leaderboard: rules and storage.",
    "social_api.py": "The social rules' HTTP API under /api.",
    "push.py": "Web push: device subscriptions and the background sender.",
    "images.py": "Uploaded group pictures: decoded and redrawn before they are stored.",
    "moderation.py": "The word list and length limits for bios, handles and group names.",
    "live.py": "The nightly live game: its scheduler, page API and standings.",
    "endless.py": "The open table's page API and its daily and weekly boards.",
    "anticheat.py": "Accuracy flags on the quote log, and the admins' review queue.",
    "players.py": "The players page: every account's record, team access, the Excel file.",
    "overview.py": "This page: the app's structure, plans, services and live status.",
}
# The client isn't on the server's disk in source form, so its areas are described, not measured.
CLIENT_AREAS = [
    {"name": "routes/", "about": "One file per page: Menu, Play, Host, Profile, Group, the admin pages and the rest."},
    {"name": "components/", "about": "Pieces shared between pages: the book and tape, tickets, name cards, the bell, the menu bar."},
    {"name": "avatar/", "about": "Draws an avatar from its parts, still and animated."},
    {"name": "lib/", "about": "Talking to the server: the WebSocket, each API, and types.ts, the protocol's mirror."},
    {"name": "styles.module.css", "about": "Every style, in one CSS module. Check a class name is free before adding one."},
]

# Every table, and what it holds.
TABLES = {
    "users": "One row per signed-in account: name, email, coins, XP, prestige, avatar, bio, handle.",
    "sessions": "Sign-ins: a random token per device, good for 90 days.",
    "games": "Every saved game: hosted, live, and each open-table round.",
    "results": "A signed-in player's result in a hosted or live game: points, rank, coins, XP, prestige.",
    "endless_results": "A signed-in player's result in one open-table round.",
    "game_players": "Everyone at a saved game's table, guests and bots included.",
    "game_rounds": "Each round's question and answer in a saved game.",
    "game_fills": "Every trade in a saved game.",
    "quote_log": "Every signed-in sealed quote and how close it was, for the accuracy flags.",
    "inventory": "Avatar items and banners each account owns, and what they paid.",
    "achievements": "Achievement tiers each account has earned.",
    "coin_grants": "One-off gifts of coins to every account: how many coins, to how many accounts, and when.",
    "friendships": "Pairs of accounts that are friends.",
    "friend_requests": "Friend requests waiting for an answer.",
    "blocks": "Who has blocked whom.",
    "groups": "Groups: name, owner, bio, shield and invite link.",
    "group_members": "Who is in each group.",
    "group_invites": "Invites to a group that haven't been answered.",
    "group_images": "Uploaded group pictures, as redrawn by the server.",
    "notifications": "What the bell shows each account.",
    "reports": "Reported bios, group names and pictures, and what was decided.",
    "push_subscriptions": "Devices that asked for notifications.",
    "accuracy_flags": "Accounts flagged for quotes too accurate to be luck, and each review.",
    "team_access": "Teammates the admins have given view access to the team pages.",
}

BUILD = re.compile(r"assets/index-([\w-]+)\.js")


@lru_cache(maxsize=1)
def planning() -> dict:
    """Plans, services and tool versions, as written by tools/dashboard/refresh.py. Read once:
    the file only changes with a deploy. Empty if a checkout doesn't have it yet."""
    if not DATA.is_file():
        return {}
    return json.loads(DATA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def bank_size() -> int:
    """Questions in the bank, playable or not. The file only changes with a deploy."""
    return len(json.loads(BANK_PATH.read_bytes()))


def build_id() -> str | None:
    """The built client's content hash, which changes with every deploy that touches it."""
    try:
        found = BUILD.search(CLIENT_INDEX.read_text(encoding="utf-8"))
    except OSError:
        return None
    return found.group(1) if found else None


def lines_in(path: Path) -> int:
    files = [path] if path.is_file() else [f for f in path.rglob("*.py") if "tests" not in f.parts]
    return sum(len(f.read_text(encoding="utf-8", errors="ignore").splitlines()) for f in files)


def modules() -> list[dict]:
    """Each server module with what it is for and how long it is. A file nobody has described
    yet still shows, so the list can't hide one."""
    rows = [
        {"name": name, "about": about, "lines": lines_in(HERE / name) if (HERE / name).exists() else None}
        for name, about in MODULES.items()
    ]
    described = {name.rstrip("/") for name in MODULES}
    for path in sorted(HERE.iterdir()):
        if path.name.startswith("_") or path.name == "tests" or path.name in described:
            continue
        if path.suffix == ".py" or (path.is_dir() and any(path.glob("*.py"))):
            rows.append({"name": path.name + ("/" if path.is_dir() else ""), "about": "", "lines": lines_in(path)})
    return rows


def tables(conn: sqlite3.Connection) -> list[dict]:
    """Every table with what it holds and how many rows it has now."""
    names = [
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    ]
    order = {name: index for index, name in enumerate(TABLES)}
    names.sort(key=lambda name: (order.get(name, len(order)), name))
    return [
        {"name": name, "about": TABLES.get(name, ""), "rows": conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]}
        for name in names
    ]


def status(db: Database, hub: Hub, pusher: object | None) -> dict:
    """What is true of the running server right now."""
    rooms = [room for room in hub.rooms.values() if hasattr(room, "players")]
    with db.lock:
        accounts = db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        games = db.conn.execute("SELECT COUNT(*) FROM games WHERE endless = 0").fetchone()[0]
        teammates = db.conn.execute("SELECT COUNT(*) FROM team_access").fetchone()[0]
    try:
        database_bytes = db.path.stat().st_size
    except OSError:
        database_bytes = None
    return {
        "started_at": STARTED_AT.isoformat(timespec="seconds"),
        "uptime_seconds": int(time.monotonic() - STARTED),
        "build": build_id(),
        "rooms": len(rooms),
        "rooms_in_play": sum(room.phase not in (Phase.LOBBY, Phase.GAME_OVER) for room in rooms),
        "people_at_tables": sum(len(room.connected_humans) for room in rooms),
        "accounts": accounts,
        "games": games,
        "questions_playable": len(hub.questions),
        "questions_in_bank": bank_size(),
        "database_bytes": database_bytes,
        "admins": len(social.admin_emails()),
        "teammates": teammates,
        # `expected` is how production should be set; the page marks a switch that differs.
        "switches": [
            {"name": "Sign in with Google", "on": bool(auth.GOOGLE_CLIENT_ID), "expected": True, "about": "GOOGLE_CLIENT_ID is set."},
            {"name": "Phone notifications", "on": pusher is not None, "expected": True, "about": "The VAPID key pair is set."},
            {"name": "Nightly live game", "on": live.enabled(), "expected": True, "about": "LIVE_MODE isn't 0."},
            {"name": "Dev sign-in", "on": auth.ALLOW_DEV_LOGIN, "expected": False, "about": "ALLOW_DEV_LOGIN: a fake sign-in for local testing only."},
            {"name": "Unverified questions", "on": os.environ.get("ALLOW_UNVERIFIED_QUESTIONS") == "1", "expected": False, "about": "ALLOW_UNVERIFIED_QUESTIONS: for local playtests only."},
        ],
    }


def people(db: Database, full: bool) -> dict:
    """Who is on the team: admins and teammates, by the name of the account each email signs in
    to. Emails are for admins' eyes; someone who hasn't signed in yet has no name to show, so a
    teammate viewing sees them only in the count."""
    emails = sorted(social.admin_emails())
    with db.lock:
        names = {
            row["email"].lower(): row["name"]
            for row in db.conn.execute("SELECT email, name FROM users")
            if row["email"].lower() in emails
        }
    listed = players.team(db)

    def person(email: str, name: str | None) -> dict:
        return {"name": name, **({"email": email} if full else {})}

    admins = [person(email, names.get(email)) for email in emails]
    teammates = [person(mate["email"], mate["account"]) for mate in listed]
    if not full:
        admins = [p for p in admins if p["name"]]
        teammates = [p for p in teammates if p["name"]]
    return {"admins": admins, "teammates": teammates, "admin_count": len(emails), "teammate_count": len(listed)}


def layers(services: list[dict]) -> list[dict]:
    """LAYERS, with the outside services filled in from the data file."""
    filled = []
    for layer in LAYERS:
        if layer["id"] == "services":
            parts = [
                {"name": s["service"], "about": s["role"], "where": SERVICE_USE.get(s.get("category", ""), s.get("category", ""))}
                for s in services
            ]
            layer = {**layer, "parts": parts}
        filled.append(layer)
    return filled


def overview(db: Database, hub: Hub, pusher: object | None, full: bool) -> dict:
    plans = planning()
    services = plans.get("services", [])
    with db.lock:
        table_rows = tables(db.conn)
    return {
        "status": status(db, hub, pusher),
        "layers": layers(services),
        "pages": PAGES,
        "modules": modules(),
        "client": CLIENT_AREAS,
        "tables": table_rows,
        "team": people(db, full),
        "plans_as_of": plans.get("refreshed_at"),
        "principles": [row["principle"] for row in plans.get("principles", [])],
        "milestones": plans.get("milestones", []),
        "goals": plans.get("goals", []),
        "timeline": plans.get("timeline", []),
        "services": services,
        "costs": plans.get("costs", []),
        "cost_summary": (plans.get("cost_summary") or [None])[0],
        "stack": plans.get("stack", []),
        "project": (plans.get("snapshot") or [None])[0],
    }


def router_for(hub: Hub) -> APIRouter:
    router = APIRouter(prefix="/api/admin/overview")

    @router.get("")
    def page(request: Request, response: Response) -> dict:
        _, admin = players.require_viewer(request)
        response.headers["Cache-Control"] = "no-store"
        state = request.app.state
        return {"viewer": {"admin": admin}, **overview(state.db, hub, getattr(state, "pusher", None), full=admin)}

    return router
