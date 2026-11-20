"""Friends, groups, notifications and reports (M5).

Storage and rules for the social layer, on the same SQLite connection and lock as
server/db.py. In public an account is named by its `public_id`, a random link id, never by its
database id or email. Every function takes the Database and opens the lock itself; helpers
whose names start with an underscore expect the caller to hold it.

Decided with Ryan, Nov 4, 2026: friend requests come from people you've played with, by
friend code, and by handle search; a report hides a bio or group name from everyone but its
owner until Ryan reviews it; notifications are an in-app bell, and web push (server/push.py,
Nov 10, 2026) sends most of them to phones as well.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from server import images
from server.cosmetics import stored_avatar
from server.moderation import clean_bio, clean_group_name, clean_handle

if TYPE_CHECKING:
    from server.db import Database

FRIEND_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0 or 1 to misread
FRIEND_CODE_LENGTH = 8
MAX_PENDING_SENT = 30
MAX_REQUESTS_PER_DAY = 50
MAX_GROUPS_OWNED = 5
MAX_GROUP_MEMBERS = 150  # a club meeting runs to 100 (the FinTech club), with room to grow
# Coins to start a group (Ryan, Nov 11, 2026). Spent, not lent: disbanding gives nothing back.
# Groups made before the charge were free and stay as they are.
GROUP_COST = 1500
# A group's icon is one of these drawings on one of these colours, or a picture its owner
# uploaded. "letters" is the group's initials, and what every group starts with. The client
# draws them (client/src/components/GroupIcon.tsx); a test checks it knows every id here.
GROUP_GLYPHS = (
    "letters", "book", "bars", "target", "bolt", "crown", "star",
    "shield", "flask", "compass", "dice", "rocket", "flame",
    # Fuller drawings, added the same day at Ryan's request.
    "owl", "lighthouse", "mountain", "anchor", "castle", "hourglass", "abacus",
    "globe", "laurel", "trophy", "scales", "ship", "atom",
)  # fmt: skip
GROUP_COLORS = ("blue", "sky", "navy", "forest", "mint", "purple", "lavender", "paper")
MAX_REPORTS_PER_DAY = 20
NOTIFICATIONS_SHOWN = 30
NOTIFICATIONS_KEPT = 200
TABLEMATES_SHOWN = 12
SEARCH_RESULTS = 20
SEARCH_MIN = 2
HIDDEN_GROUP_NAME = "Name under review"
NOTIFICATION_KINDS = ("friend_request", "friend_accepted", "group_invite", "group_joined", "room_invite")
# Called with each new notification's id; server/push.py sets it when web push is configured.
on_notify: Callable[[int], None] | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS friendships (
    user_a INTEGER NOT NULL REFERENCES users(id),
    user_b INTEGER NOT NULL REFERENCES users(id),
    since TEXT NOT NULL,
    PRIMARY KEY (user_a, user_b),
    CHECK (user_a < user_b)
);
CREATE TABLE IF NOT EXISTS friend_requests (
    from_id INTEGER NOT NULL REFERENCES users(id),
    to_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    declined INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (from_id, to_id)
);
CREATE INDEX IF NOT EXISTS friend_requests_to ON friend_requests(to_id);
CREATE TABLE IF NOT EXISTS blocks (
    blocker_id INTEGER NOT NULL REFERENCES users(id),
    blocked_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (blocker_id, blocked_id)
);
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    name_hidden INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS group_members (
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (group_id, user_id)
);
CREATE INDEX IF NOT EXISTS group_members_by_user ON group_members(user_id);
CREATE TABLE IF NOT EXISTS group_invites (
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    invited_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (group_id, user_id)
);
CREATE TABLE IF NOT EXISTS group_images (
    group_id INTEGER PRIMARY KEY REFERENCES groups(id) ON DELETE CASCADE,
    data BLOB NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(id),
    group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
    room_code TEXT,
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX IF NOT EXISTS notifications_by_user ON notifications(user_id, id);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    reporter_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id),
    group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
"""

# Columns on users, added to databases that predate M5 (server/db.py applies them).
USER_COLUMNS = {
    "public_id": "ALTER TABLE users ADD COLUMN public_id TEXT",
    "handle": "ALTER TABLE users ADD COLUMN handle TEXT",  # stored lowercase, shown with an @
    "friend_code": "ALTER TABLE users ADD COLUMN friend_code TEXT",
    "bio_hidden": "ALTER TABLE users ADD COLUMN bio_hidden INTEGER NOT NULL DEFAULT 0",
}
# Columns on groups since Nov 11, 2026: a bio, the icon, and the code in the group's invite link.
# The picture itself is in group_images, so reading a group never drags its picture along;
# image_tag is empty with no picture and changes with every upload, so its address does too.
GROUP_COLUMNS = {
    "bio": "ALTER TABLE groups ADD COLUMN bio TEXT NOT NULL DEFAULT ''",
    "bio_hidden": "ALTER TABLE groups ADD COLUMN bio_hidden INTEGER NOT NULL DEFAULT 0",
    "glyph": "ALTER TABLE groups ADD COLUMN glyph TEXT NOT NULL DEFAULT 'letters'",
    "color": "ALTER TABLE groups ADD COLUMN color TEXT NOT NULL DEFAULT 'blue'",
    "image_tag": "ALTER TABLE groups ADD COLUMN image_tag TEXT NOT NULL DEFAULT ''",
    "image_hidden": "ALTER TABLE groups ADD COLUMN image_hidden INTEGER NOT NULL DEFAULT 0",
    "invite_code": "ALTER TABLE groups ADD COLUMN invite_code TEXT",
}


class SocialError(ValueError):
    """A request the rules refuse, with a reason the player can read. `status` is the HTTP
    code the API answers with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds")


def new_public_id() -> str:
    return secrets.token_urlsafe(8)


def new_friend_code() -> str:
    return "".join(secrets.choice(FRIEND_CODE_ALPHABET) for _ in range(FRIEND_CODE_LENGTH))


def normalize_code(text: str) -> str:
    """What a player types ("abcd-2345 ") as a stored code ("ABCD2345")."""
    return "".join(c for c in text.upper() if c.isalnum())


def new_invite_code() -> str:
    """The secret in a group's invite link. Whoever has the link can join, so it is long enough
    not to be guessed and the owner can swap it for a new one."""
    return secrets.token_urlsafe(9)


def install(conn: sqlite3.Connection) -> None:
    """Creates the social tables and gives every account a public id and friend code, and every
    group an invite link. Runs at startup after server/db.py has added USER_COLUMNS."""
    conn.executescript(SCHEMA)
    have = {row[1] for row in conn.execute("PRAGMA table_info(groups)")}
    for column, statement in GROUP_COLUMNS.items():
        if column not in have:
            conn.execute(statement)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_public_id ON users(public_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_handle ON users(handle)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_friend_code ON users(friend_code)")
    missing = conn.execute("SELECT id FROM users WHERE public_id IS NULL OR friend_code IS NULL").fetchall()
    for row in missing:
        conn.execute(
            "UPDATE users SET public_id = COALESCE(public_id, ?), friend_code = COALESCE(friend_code, ?) WHERE id = ?",
            (new_public_id(), new_friend_code(), row[0]),
        )
    for row in conn.execute("SELECT id FROM groups WHERE invite_code IS NULL").fetchall():
        conn.execute("UPDATE groups SET invite_code = ? WHERE id = ?", (new_invite_code(), row[0]))


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}


def is_admin(user: dict | None) -> bool:
    return user is not None and user["email"].lower() in admin_emails()


# Cards: how one account appears to others.

CARD = "u.id, u.public_id, u.name, u.handle, u.avatar, u.xp, u.prestige"


def _card(row: sqlite3.Row) -> dict:
    from server.db import level_for  # here, not at the top: server/db.py imports this module

    return {
        "public_id": row["public_id"],
        "name": row["name"],
        "handle": row["handle"],
        "avatar": stored_avatar(json.loads(row["avatar"]) if row["avatar"] else None),
        "level": level_for(row["xp"]),
        "prestige": row["prestige"],
    }


def _cards(conn: sqlite3.Connection, user_ids: list[int]) -> dict[int, dict]:
    if not user_ids:
        return {}
    marks = ",".join("?" * len(user_ids))
    rows = conn.execute(f"SELECT {CARD} FROM users u WHERE u.id IN ({marks})", tuple(user_ids)).fetchall()
    return {row["id"]: _card(row) for row in rows}


def _user_id(conn: sqlite3.Connection, public_id: str) -> int:
    row = conn.execute("SELECT id FROM users WHERE public_id = ?", (public_id,)).fetchone()
    if row is None:
        raise SocialError("No player has that link.", 404)
    return row["id"]


def user_id_for(db: Database, public_id: str) -> int:
    with db.lock:
        return _user_id(db.conn, public_id)


def _pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _blocked(conn: sqlite3.Connection, blocker: int, blocked: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM blocks WHERE blocker_id = ? AND blocked_id = ?", (blocker, blocked)
    ).fetchone() is not None


def _either_blocked(conn: sqlite3.Connection, a: int, b: int) -> bool:
    return _blocked(conn, a, b) or _blocked(conn, b, a)


def _friends(conn: sqlite3.Connection, a: int, b: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM friendships WHERE user_a = ? AND user_b = ?", _pair(a, b)
    ).fetchone() is not None


def _relation(conn: sqlite3.Connection, me: int, other: int) -> str:
    """you, blocked (by me), friend, requested (by me, pending), incoming, or none. A request
    the other side declined still reads as requested: declines are silent."""
    if me == other:
        return "you"
    if _blocked(conn, me, other):
        return "blocked"
    if _friends(conn, me, other):
        return "friend"
    if conn.execute("SELECT 1 FROM friend_requests WHERE from_id = ? AND to_id = ?", (me, other)).fetchone():
        return "requested"
    incoming = conn.execute(
        "SELECT 1 FROM friend_requests WHERE from_id = ? AND to_id = ? AND declined = 0", (other, me)
    ).fetchone()
    return "incoming" if incoming else "none"


def relations(db: Database, me: int, others: list[int]) -> dict[int, str]:
    with db.lock:
        return {other: _relation(db.conn, me, other) for other in others}


def _notify(
    conn: sqlite3.Connection,
    user_id: int,
    kind: str,
    actor_id: int | None = None,
    group_id: int | None = None,
    room_code: str | None = None,
) -> None:
    cursor = conn.execute(
        "INSERT INTO notifications (user_id, kind, actor_id, group_id, room_code, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, kind, actor_id, group_id, room_code, _stamp()),
    )
    if on_notify is not None:  # web push (server/push.py); sent from its own thread
        on_notify(cursor.lastrowid)
    # Keep the newest few hundred; the bell only ever shows the latest.
    conn.execute(
        "DELETE FROM notifications WHERE user_id = ? AND id NOT IN "
        "(SELECT id FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?)",
        (user_id, user_id, NOTIFICATIONS_KEPT),
    )


class _Transaction:
    """`with _Transaction(db):` holds the lock and commits, or rolls back on an exception."""

    def __init__(self, db: Database):
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        self.db.lock.acquire()
        self.db.conn.execute("BEGIN")
        return self.db.conn

    def __exit__(self, kind, error, trace) -> None:
        try:
            self.db.conn.execute("ROLLBACK" if kind else "COMMIT")
        finally:
            self.db.lock.release()


# Identity: handles and friend codes.


def set_handle(db: Database, me: int, text: str) -> str | None:
    """Sets or clears (with an empty string) the handle others can search for."""
    handle = clean_handle(text) if text.strip() else None
    with db.lock:
        try:
            db.conn.execute("UPDATE users SET handle = ? WHERE id = ?", (handle, me))
        except sqlite3.IntegrityError as error:
            raise SocialError("That handle is taken. Try another.") from error
    return handle


def new_code(db: Database, me: int) -> str:
    """Replaces the friend code, for one that has spread further than its owner wanted."""
    with db.lock:
        while True:
            code = new_friend_code()
            try:
                db.conn.execute("UPDATE users SET friend_code = ? WHERE id = ?", (code, me))
                return code
            except sqlite3.IntegrityError:
                continue


def user_id_for_code(db: Database, code: str) -> int:
    with db.lock:
        row = db.conn.execute("SELECT id FROM users WHERE friend_code = ?", (normalize_code(code),)).fetchone()
    if row is None:
        raise SocialError("No player has that friend code.", 404)
    return row["id"]


# Friends.


def send_request(db: Database, me: int, other: int) -> str:
    """Asks to be friends. Returns the new relation. If they had already asked you, this
    accepts. A request to someone who has blocked you is stored as already declined, so it
    looks pending to you and never reaches them."""
    if me == other:
        raise SocialError("That's you.")
    with _Transaction(db) as conn:
        if _blocked(conn, me, other):
            raise SocialError("You've blocked this player. Unblock them first.")
        if _friends(conn, me, other):
            return "friend"
        theirs = conn.execute(
            "SELECT declined FROM friend_requests WHERE from_id = ? AND to_id = ?", (other, me)
        ).fetchone()
        if theirs is not None and not theirs["declined"]:
            _befriend(conn, me, other)
            return "friend"
        if conn.execute("SELECT 1 FROM friend_requests WHERE from_id = ? AND to_id = ?", (me, other)).fetchone():
            return "requested"
        pending = conn.execute("SELECT COUNT(*) FROM friend_requests WHERE from_id = ?", (me,)).fetchone()[0]
        if pending >= MAX_PENDING_SENT:
            raise SocialError(f"You have {MAX_PENDING_SENT} requests waiting. Cancel some first.")
        since = _stamp(_now() - timedelta(days=1))
        today = conn.execute(
            "SELECT COUNT(*) FROM friend_requests WHERE from_id = ? AND created_at > ?", (me, since)
        ).fetchone()[0]
        if today >= MAX_REQUESTS_PER_DAY:
            raise SocialError("That's a lot of requests for one day. Try again tomorrow.", 429)
        silent = _blocked(conn, other, me)
        conn.execute(
            "INSERT INTO friend_requests (from_id, to_id, created_at, declined) VALUES (?, ?, ?, ?)",
            (me, other, _stamp(), int(silent)),
        )
        if not silent:
            _notify(conn, other, "friend_request", actor_id=me)
    return "requested"


def _befriend(conn: sqlite3.Connection, me: int, other: int) -> None:
    """Accepting `other`'s request: the requests go, the friendship stays, and they hear."""
    conn.execute(
        "DELETE FROM friend_requests WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)",
        (me, other, other, me),
    )
    conn.execute("INSERT OR IGNORE INTO friendships (user_a, user_b, since) VALUES (?, ?, ?)", (*_pair(me, other), _stamp()))
    conn.execute(
        "UPDATE notifications SET read_at = ? WHERE user_id = ? AND actor_id = ? AND kind = 'friend_request' AND read_at IS NULL",
        (_stamp(), me, other),
    )
    _notify(conn, other, "friend_accepted", actor_id=me)


def accept_request(db: Database, me: int, other: int) -> str:
    with _Transaction(db) as conn:
        theirs = conn.execute(
            "SELECT 1 FROM friend_requests WHERE from_id = ? AND to_id = ? AND declined = 0", (other, me)
        ).fetchone()
        if theirs is None:
            raise SocialError("That request is no longer waiting.", 404)
        _befriend(conn, me, other)
    return "friend"


def decline_request(db: Database, me: int, other: int) -> str:
    """Silent: the sender still sees their request as waiting."""
    with db.lock:
        db.conn.execute("UPDATE friend_requests SET declined = 1 WHERE from_id = ? AND to_id = ?", (other, me))
    return "none"


def remove(db: Database, me: int, other: int) -> str:
    """Unfriends, or cancels a request you sent."""
    with db.lock:
        db.conn.execute("DELETE FROM friendships WHERE user_a = ? AND user_b = ?", _pair(me, other))
        db.conn.execute("DELETE FROM friend_requests WHERE from_id = ? AND to_id = ?", (me, other))
    return "none"


def block(db: Database, me: int, other: int) -> str:
    """Ends any friendship and request between the two, and stops `other` finding or asking
    you. They aren't told."""
    if me == other:
        raise SocialError("That's you.")
    with _Transaction(db) as conn:
        conn.execute("INSERT OR IGNORE INTO blocks (blocker_id, blocked_id, created_at) VALUES (?, ?, ?)", (me, other, _stamp()))
        conn.execute("DELETE FROM friendships WHERE user_a = ? AND user_b = ?", _pair(me, other))
        conn.execute(
            "DELETE FROM friend_requests WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)",
            (me, other, other, me),
        )
    return "blocked"


def unblock(db: Database, me: int, other: int) -> str:
    with db.lock:
        db.conn.execute("DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?", (me, other))
    return "none"


def search(db: Database, me: int, text: str) -> list[dict]:
    """Accounts whose handle starts with `text`. Only handles are searched, never names or
    emails, so an account without a handle can't be found this way."""
    query = text.strip().removeprefix("@").lower()
    if len(query) < SEARCH_MIN:
        return []
    pattern = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with db.lock:
        rows = db.conn.execute(
            f"""
            SELECT {CARD} FROM users u
            WHERE u.handle LIKE ? ESCAPE '\\' AND u.id != ?
              AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.blocker_id = u.id AND b.blocked_id = ?)
                                                       OR (b.blocker_id = ? AND b.blocked_id = u.id))
            ORDER BY u.handle LIMIT ?
            """,
            (pattern, me, me, me, SEARCH_RESULTS),
        ).fetchall()
        return [{**_card(row), "relation": _relation(db.conn, me, row["id"])} for row in rows]


def overview(db: Database, me: int) -> dict:
    """Everything the Social page shows: your card, friends ranked by prestige (the friends
    leaderboard), requests both ways, people you've played with, your groups and invites."""
    with db.lock:
        conn = db.conn
        mine = conn.execute(f"SELECT {CARD}, u.friend_code FROM users u WHERE u.id = ?", (me,)).fetchone()
        friend_rows = conn.execute(
            "SELECT CASE WHEN user_a = ? THEN user_b ELSE user_a END AS other, since FROM friendships "
            "WHERE user_a = ? OR user_b = ?",
            (me, me, me),
        ).fetchall()
        incoming_rows = conn.execute(
            "SELECT from_id AS other, created_at FROM friend_requests WHERE to_id = ? AND declined = 0 ORDER BY created_at DESC",
            (me,),
        ).fetchall()
        outgoing_rows = conn.execute(
            "SELECT to_id AS other, created_at FROM friend_requests WHERE from_id = ? ORDER BY created_at DESC",
            (me,),
        ).fetchall()
        mates = conn.execute(
            """
            SELECT other.user_id AS other, MAX(g.id) AS last_game, MAX(g.ended_at) AS last_played
            FROM game_players mine
            JOIN game_players other ON other.game_id = mine.game_id
                 AND other.user_id IS NOT NULL AND other.user_id != mine.user_id
            JOIN games g ON g.id = mine.game_id
            WHERE mine.user_id = ?
            GROUP BY other.user_id ORDER BY last_game DESC LIMIT 60
            """,
            (me,),
        ).fetchall()
        friend_ids = {row["other"] for row in friend_rows}
        mate_rows = []
        for row in mates:
            if row["other"] in friend_ids or _either_blocked(conn, me, row["other"]):
                continue
            mate_rows.append(row)
            if len(mate_rows) == TABLEMATES_SHOWN:
                break
        ids = [row["other"] for row in [*friend_rows, *incoming_rows, *outgoing_rows, *mate_rows]]
        cards = _cards(conn, ids)
        relation = {row["other"]: _relation(conn, me, row["other"]) for row in mate_rows}
        groups = _my_groups(conn, me)
        invites = _my_invites(conn, me)
        coins = conn.execute("SELECT coins FROM users WHERE id = ?", (me,)).fetchone()["coins"]
    friends = sorted(
        ({**cards[row["other"]], "since": row["since"]} for row in friend_rows),
        key=lambda card: (-card["prestige"], card["name"].casefold()),
    )
    return {
        "me": {**_card(mine), "friend_code": mine["friend_code"]},
        "friends": friends,
        "incoming": [{**cards[row["other"]], "at": row["created_at"]} for row in incoming_rows],
        "outgoing": [{**cards[row["other"]], "at": row["created_at"]} for row in outgoing_rows],
        "tablemates": [
            {**cards[row["other"]], "last_played": row["last_played"], "relation": relation[row["other"]]}
            for row in mate_rows
        ],
        "groups": groups,
        "group_invites": invites,
        # What starting a group costs, what you have, and how many more you may own.
        "coins": coins,
        "group_cost": GROUP_COST,
        "groups_left": max(0, MAX_GROUPS_OWNED - sum(1 for group in groups if group["role"] == "owner")),
    }


def public_profile(db: Database, viewer: int, public_id: str) -> dict:
    """Another player's profile as `viewer` sees it. Someone who has blocked the viewer reads
    as not found. A hidden bio shows only to its owner."""
    from server import achievements

    with db.lock:
        conn = db.conn
        row = conn.execute(f"SELECT {CARD}, u.bio, u.bio_hidden FROM users u WHERE u.public_id = ?", (public_id,)).fetchone()
        if row is None or _blocked(conn, row["id"], viewer):
            raise SocialError("No player has that link.", 404)
        totals = conn.execute(
            "SELECT COUNT(*) AS games, COALESCE(SUM(CASE WHEN rank = 1 THEN 1 ELSE 0 END), 0) AS wins, "
            "COALESCE(SUM(best_quotes), 0) AS best_quotes FROM results WHERE user_id = ?",
            (row["id"],),
        ).fetchone()
        relation = _relation(conn, viewer, row["id"])
        groups = [
            {"public_id": g["public_id"], "name": _group_name(g, viewer)}
            for g in conn.execute(
                "SELECT g.* FROM groups g JOIN group_members m ON m.group_id = g.id WHERE m.user_id = ? ORDER BY g.name",
                (row["id"],),
            ).fetchall()
        ]
    own = row["id"] == viewer
    hidden = bool(row["bio_hidden"])
    return {
        **_card(row),
        "bio": row["bio"] if own or not hidden else "",
        "bio_hidden": hidden if own else False,
        "games": totals["games"],
        "wins": totals["wins"],
        "best_quotes": totals["best_quotes"],
        "badges": achievements.badges(db, row["id"]),
        "relation": relation,
        "groups": groups,
    }


# Notifications.


def notifications(db: Database, me: int) -> dict:
    with db.lock:
        conn = db.conn
        rows = conn.execute(
            "SELECT n.*, g.public_id AS group_public_id, g.name AS group_name, g.name_hidden, g.owner_id "
            "FROM notifications n LEFT JOIN groups g ON g.id = n.group_id "
            "WHERE n.user_id = ? ORDER BY n.id DESC LIMIT ?",
            (me, NOTIFICATIONS_SHOWN),
        ).fetchall()
        unread = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", (me,)
        ).fetchone()[0]
        cards = _cards(conn, sorted({row["actor_id"] for row in rows if row["actor_id"]}))
        # Whether a request or invite can still be answered from the bell: one already settled
        # (accepted on the Social page, or joined from a card at the table) shows no buttons.
        pending_from = {
            r["from_id"]
            for r in conn.execute("SELECT from_id FROM friend_requests WHERE to_id = ? AND declined = 0", (me,))
        }
        invited_to = {r["group_id"] for r in conn.execute("SELECT group_id FROM group_invites WHERE user_id = ?", (me,))}
    items = []
    for row in rows:
        group = None
        if row["group_public_id"]:
            group = {
                "public_id": row["group_public_id"],
                "name": HIDDEN_GROUP_NAME if row["name_hidden"] and row["owner_id"] != me else row["group_name"],
            }
        items.append(
            {
                "id": row["id"],
                "kind": row["kind"],
                "at": row["created_at"],
                "read": row["read_at"] is not None,
                "actor": cards.get(row["actor_id"]),
                "group": group,
                "room_code": row["room_code"],
                "open": (row["kind"] == "friend_request" and row["actor_id"] in pending_from)
                or (row["kind"] == "group_invite" and row["group_id"] in invited_to),
            }
        )
    return {"unread": unread, "items": items}


def mark_read(db: Database, me: int) -> None:
    with db.lock:
        db.conn.execute("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL", (_stamp(), me))


# Groups.


def _group_name(row: sqlite3.Row, viewer: int | None) -> str:
    return HIDDEN_GROUP_NAME if row["name_hidden"] and row["owner_id"] != viewer else row["name"]


def _group(conn: sqlite3.Connection, public_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM groups WHERE public_id = ?", (public_id,)).fetchone()
    if row is None:
        raise SocialError("No group has that link.", 404)
    return row


def _role(conn: sqlite3.Connection, group_id: int, user_id: int) -> str | None:
    row = conn.execute(
        "SELECT role FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id)
    ).fetchone()
    return row["role"] if row else None


def _member_count(conn: sqlite3.Connection, group_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM group_members WHERE group_id = ?", (group_id,)).fetchone()[0]


def _group_bio(row: sqlite3.Row, viewer: int | None) -> str:
    return "" if row["bio_hidden"] and row["owner_id"] != viewer else row["bio"]


def _icon(row: sqlite3.Row, viewer: int | None) -> dict:
    """How a group's icon is drawn: its drawing and colour, and the address of its picture when
    it has one this viewer may see. A reported picture shows only to the owner; everyone else
    gets the drawing underneath."""
    shown = row["image_tag"] and (not row["image_hidden"] or row["owner_id"] == viewer)
    return {
        "glyph": row["glyph"],
        "color": row["color"],
        "image": f"/api/groups/{row['public_id']}/image?v={row['image_tag']}" if shown else None,
    }


def _link_opens(row: sqlite3.Row, code: str | None) -> bool:
    """Whether `code` is the one in this group's invite link."""
    return bool(code) and bool(row["invite_code"]) and hmac.compare_digest(row["invite_code"], code)


def _prestige(conn: sqlite3.Connection, group_id: int) -> int:
    """A group's prestige: its members' prestige added up. Worked out when asked, never stored,
    so it is right the moment someone joins, leaves or wins."""
    return conn.execute(
        "SELECT COALESCE(SUM(u.prestige), 0) FROM group_members m JOIN users u ON u.id = m.user_id WHERE m.group_id = ?",
        (group_id,),
    ).fetchone()[0]


def _summary(conn: sqlite3.Connection, row: sqlite3.Row, viewer: int | None) -> dict:
    return {
        "public_id": row["public_id"],
        "name": _group_name(row, viewer),
        "icon": _icon(row, viewer),
        "member_count": _member_count(conn, row["id"]),
        "prestige": _prestige(conn, row["id"]),
        "role": _role(conn, row["id"], viewer) if viewer is not None else None,
    }


def _my_groups(conn: sqlite3.Connection, me: int) -> list[dict]:
    rows = conn.execute(
        "SELECT g.* FROM groups g JOIN group_members m ON m.group_id = g.id WHERE m.user_id = ? ORDER BY g.name COLLATE NOCASE",
        (me,),
    ).fetchall()
    return [_summary(conn, row, me) for row in rows]


def _my_invites(conn: sqlite3.Connection, me: int) -> list[dict]:
    rows = conn.execute(
        "SELECT g.*, i.invited_by, i.created_at AS invited_at FROM group_invites i JOIN groups g ON g.id = i.group_id "
        "WHERE i.user_id = ? ORDER BY i.created_at DESC",
        (me,),
    ).fetchall()
    cards = _cards(conn, [row["invited_by"] for row in rows])
    return [{**_summary(conn, row, me), "invited_by": cards.get(row["invited_by"]), "at": row["invited_at"]} for row in rows]


def my_groups(db: Database, me: int) -> list[dict]:
    with db.lock:
        return _my_groups(db.conn, me)


def owned_groups(db: Database, me: int) -> list[dict]:
    return [group for group in my_groups(db, me) if group["role"] == "owner"]


def create_group(
    db: Database, owner: int, name: str, bio: str = "", glyph: str | None = None, color: str | None = None
) -> dict:
    """Starts a group for GROUP_COST coins, with its bio and icon if the owner chose them up
    front. Everything is checked first, and the coins leave and the group appears in one
    transaction, so a refusal (too few coins, too many groups, a bad name, bio or icon) costs
    nothing."""
    name = clean_group_name(name)
    bio = clean_bio(bio)
    if glyph is not None and glyph not in GROUP_GLYPHS:
        raise SocialError("That icon isn't one of the choices.")
    if color is not None and color not in GROUP_COLORS:
        raise SocialError("That colour isn't one of the choices.")
    with _Transaction(db) as conn:
        owned = conn.execute("SELECT COUNT(*) FROM groups WHERE owner_id = ?", (owner,)).fetchone()[0]
        if owned >= MAX_GROUPS_OWNED:
            raise SocialError(f"You can own up to {MAX_GROUPS_OWNED} groups.")
        coins = conn.execute("SELECT coins FROM users WHERE id = ?", (owner,)).fetchone()["coins"]
        if coins < GROUP_COST:
            raise SocialError(
                f"Starting a group costs {GROUP_COST:,} coins. You need {GROUP_COST - coins:,} more.", 402
            )
        conn.execute("UPDATE users SET coins = coins - ? WHERE id = ?", (GROUP_COST, owner))
        public_id = new_public_id()
        stamp = _stamp()
        group_id = conn.execute(
            "INSERT INTO groups (public_id, name, owner_id, created_at, invite_code, bio, glyph, color) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (public_id, name, owner, stamp, new_invite_code(), bio, glyph or "letters", color or "blue"),
        ).lastrowid
        conn.execute(
            "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
            (group_id, owner, stamp),
        )
        return _summary(conn, _group(conn, public_id), owner)


def group_preview(db: Database, public_id: str, code: str | None, viewer: int | None = None) -> dict:
    """What someone holding a group's invite link sees before joining, signed in or not: its
    name, icon, bio, size and who runs it. Without the right code there is no group to see."""
    with db.lock:
        conn = db.conn
        row = _group(conn, public_id)
        if not _link_opens(row, code):
            raise SocialError("That invite link is no longer open.", 404)
        owner = _cards(conn, [row["owner_id"]])[row["owner_id"]]
        summary = _summary(conn, row, viewer)
    return {
        **summary,
        "bio": _group_bio(row, viewer),
        "max_members": MAX_GROUP_MEMBERS,
        "owner": {"name": owner["name"], "avatar": owner["avatar"]},
    }


def group_detail(db: Database, viewer: int, public_id: str, code: str | None = None) -> dict:
    """A group's page: its members ranked by prestige (the group leaderboard), your place in
    it, the invite link for its members, and for the owner, friends who could be invited.
    `code` is from an invite link the viewer followed; the right one counts as an invite."""
    with db.lock:
        conn = db.conn
        row = _group(conn, public_id)
        members = conn.execute(
            "SELECT user_id, role, joined_at FROM group_members WHERE group_id = ?", (row["id"],)
        ).fetchall()
        role = _role(conn, row["id"], viewer)
        asked = conn.execute(
            "SELECT 1 FROM group_invites WHERE group_id = ? AND user_id = ?", (row["id"], viewer)
        ).fetchone() is not None
        by_link = role is None and _link_opens(row, code) and not _blocked(conn, row["owner_id"], viewer)
        invited = asked or by_link
        member_ids = {m["user_id"] for m in members}
        candidates: list[int] = []
        if role == "owner":
            pending = {
                r["user_id"] for r in conn.execute("SELECT user_id FROM group_invites WHERE group_id = ?", (row["id"],))
            }
            friends = conn.execute(
                "SELECT CASE WHEN user_a = ? THEN user_b ELSE user_a END AS other FROM friendships WHERE user_a = ? OR user_b = ?",
                (viewer, viewer, viewer),
            ).fetchall()
            candidates = [f["other"] for f in friends if f["other"] not in member_ids | pending]
            pending_ids = sorted(pending)
        else:
            pending_ids = []
        cards = _cards(conn, [*member_ids, row["owner_id"], *candidates, *pending_ids])
    ranked = sorted(
        ({**cards[m["user_id"]], "role": m["role"], "joined_at": m["joined_at"], "you": m["user_id"] == viewer} for m in members),
        key=lambda card: (-card["prestige"], card["name"].casefold()),
    )
    own = row["owner_id"] == viewer
    return {
        "public_id": row["public_id"],
        "name": _group_name(row, viewer),
        "name_hidden": bool(row["name_hidden"]) if own else False,
        "bio": _group_bio(row, viewer),
        "bio_hidden": bool(row["bio_hidden"]) if own else False,
        "icon": _icon(row, viewer),
        "image_hidden": bool(row["image_hidden"] and row["image_tag"]) if own else False,
        # Members can pass the link on: anyone who joined by it has it anyway. Only the owner
        # can swap it for a new one.
        "invite_code": row["invite_code"] if role else None,
        "owner": cards[row["owner_id"]],
        "role": role,
        "invited": invited,
        "by_link": by_link and not asked,  # nothing stored to decline
        "members": ranked,
        "member_count": len(ranked),
        "prestige": sum(card["prestige"] for card in ranked),
        "max_members": MAX_GROUP_MEMBERS,
        "invitable": sorted((cards[i] for i in candidates), key=lambda c: c["name"].casefold()),
        "pending": sorted((cards[i] for i in pending_ids), key=lambda c: c["name"].casefold()),
    }


def _owned(conn: sqlite3.Connection, public_id: str, owner: int) -> sqlite3.Row:
    row = _group(conn, public_id)
    if row["owner_id"] != owner:
        raise SocialError("Only the group's owner can do that.", 403)
    return row


def invite(db: Database, owner: int, group_public_id: str, invitee: int) -> str:
    """The owner invites someone; they hear about it on their bell. Returns what happened:
    invited, already_member or already_invited."""
    with _Transaction(db) as conn:
        row = _owned(conn, group_public_id, owner)
        return _invite(conn, row, owner, invitee)


def _invite(conn: sqlite3.Connection, row: sqlite3.Row, inviter: int, invitee: int) -> str:
    """Stores an invite and rings the invitee's bell. `inviter` is the owner, or a member
    hosting a table (offer_at_table)."""
    if _role(conn, row["id"], invitee):
        return "already_member"
    if conn.execute("SELECT 1 FROM group_invites WHERE group_id = ? AND user_id = ?", (row["id"], invitee)).fetchone():
        return "already_invited"
    if _member_count(conn, row["id"]) >= MAX_GROUP_MEMBERS:
        raise SocialError(f"Groups hold up to {MAX_GROUP_MEMBERS} members.")
    if _either_blocked(conn, inviter, invitee):
        return "invited"  # silently: a blocked player never hears from whoever blocked them
    conn.execute(
        "INSERT INTO group_invites (group_id, user_id, invited_by, created_at) VALUES (?, ?, ?, ?)",
        (row["id"], invitee, inviter, _stamp()),
    )
    _notify(conn, invitee, "group_invite", actor_id=inviter, group_id=row["id"])
    return "invited"


def offer_at_table(db: Database, host: int, group_public_id: str, accounts: list[int]) -> tuple[dict, dict[int, str]]:
    """A signed-in host screen offers one of its account's groups to the accounts seated at its
    table (the host-group invite; Ryan, Nov 17, 2026). Any member may make the offer, not only
    the owner: the invite link already lets every member bring people in, and this reaches
    nobody outside the room.

    Returns the group as a stranger sees it, for the card on each phone, and what happened for
    each account: `invited` (a stored invite, so their bell and a push), `already_invited`,
    `already_member`, or `blocked` (a block stands between them and the host or the group's
    owner, so they are never shown the offer)."""
    outcomes: dict[int, str] = {}
    with _Transaction(db) as conn:
        row = _group(conn, group_public_id)
        if not _role(conn, row["id"], host):
            raise SocialError("Only a group's members can invite players to it.", 403)
        for account in accounts:
            if _either_blocked(conn, host, account) or _either_blocked(conn, row["owner_id"], account):
                outcomes[account] = "blocked"
            else:
                outcomes[account] = _invite(conn, row, host, account)
        return _summary(conn, row, None), outcomes


def join(db: Database, me: int, group_public_id: str, via_room: bool = False, code: str | None = None) -> dict:
    """Accepts an invite. `via_room` is a host's invite to their table, which the room itself
    vouches for, so it needs no stored invite (a guest who signs in at the table gets one this
    way). `code` is from the group's invite link, which vouches the same way for whoever holds
    it. Neither opens the group to someone its owner has blocked."""
    with _Transaction(db) as conn:
        row = _group(conn, group_public_id)
        if _role(conn, row["id"], me):
            return _summary(conn, row, me)
        invited = conn.execute(
            "SELECT 1 FROM group_invites WHERE group_id = ? AND user_id = ?", (row["id"], me)
        ).fetchone()
        shut_out = _blocked(conn, row["owner_id"], me)
        by_link = _link_opens(row, code) and not shut_out
        via_room = via_room and not shut_out
        if not invited and not via_room and not by_link:
            raise SocialError("That invite is no longer open.", 404)
        if _member_count(conn, row["id"]) >= MAX_GROUP_MEMBERS:
            raise SocialError(f"This group is full ({MAX_GROUP_MEMBERS} members).")
        conn.execute(
            "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
            (row["id"], me, _stamp()),
        )
        conn.execute("DELETE FROM group_invites WHERE group_id = ? AND user_id = ?", (row["id"], me))
        conn.execute(
            "UPDATE notifications SET read_at = ? WHERE user_id = ? AND group_id = ? AND kind = 'group_invite' AND read_at IS NULL",
            (_stamp(), me, row["id"]),
        )
        _notify(conn, row["owner_id"], "group_joined", actor_id=me, group_id=row["id"])
        return _summary(conn, row, me)


def decline_invite(db: Database, me: int, group_public_id: str) -> None:
    with db.lock:
        row = _group(db.conn, group_public_id)
        db.conn.execute("DELETE FROM group_invites WHERE group_id = ? AND user_id = ?", (row["id"], me))


def leave(db: Database, me: int, group_public_id: str) -> None:
    with db.lock:
        row = _group(db.conn, group_public_id)
        if row["owner_id"] == me:
            raise SocialError("Owners can't leave their group. Disband it instead.")
        db.conn.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = ?", (row["id"], me))


def remove_member(db: Database, owner: int, group_public_id: str, member: int) -> None:
    with db.lock:
        row = _owned(db.conn, group_public_id, owner)
        if member == owner:
            raise SocialError("You own this group. Disband it instead.")
        db.conn.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = ?", (row["id"], member))
        db.conn.execute("DELETE FROM group_invites WHERE group_id = ? AND user_id = ?", (row["id"], member))


def rename(db: Database, owner: int, group_public_id: str, name: str) -> dict:
    """A new name replaces a hidden one, and closes the reports on the old."""
    name = clean_group_name(name)
    with _Transaction(db) as conn:
        row = _owned(conn, group_public_id, owner)
        conn.execute("UPDATE groups SET name = ?, name_hidden = 0 WHERE id = ?", (name, row["id"]))
        conn.execute(
            "UPDATE reports SET status = 'renamed', resolved_at = ? WHERE group_id = ? AND kind = 'group_name' AND status = 'open'",
            (_stamp(), row["id"]),
        )
        return _summary(conn, _group(conn, group_public_id), owner)


def reset_invite_link(db: Database, owner: int, group_public_id: str) -> str:
    """Swaps the code in the group's invite link. Every copy of the old link stops working."""
    with _Transaction(db) as conn:
        row = _owned(conn, group_public_id, owner)
        code = new_invite_code()
        conn.execute("UPDATE groups SET invite_code = ? WHERE id = ?", (code, row["id"]))
        return code


def _close_reports(conn: sqlite3.Connection, group_id: int, kind: str, status: str) -> None:
    conn.execute(
        "UPDATE reports SET status = ?, resolved_at = ? WHERE group_id = ? AND kind = ? AND status = 'open'",
        (status, _stamp(), group_id, kind),
    )


def set_bio(db: Database, owner: int, group_public_id: str, bio: str) -> str:
    """Stores the group's bio, under the same rules as a player's. A reported bio stays hidden
    through an edit, until it's reviewed; emptying it leaves nothing to review."""
    bio = clean_bio(bio)
    with _Transaction(db) as conn:
        row = _owned(conn, group_public_id, owner)
        conn.execute("UPDATE groups SET bio = ? WHERE id = ?", (bio, row["id"]))
        if not bio:
            conn.execute("UPDATE groups SET bio_hidden = 0 WHERE id = ?", (row["id"],))
            _close_reports(conn, row["id"], "group_bio", "removed")
        return bio


def set_icon(db: Database, owner: int, group_public_id: str, glyph: str | None, color: str | None) -> dict:
    """Picks the drawing and colour of the group's icon; either may be left as it is."""
    if glyph is not None and glyph not in GROUP_GLYPHS:
        raise SocialError("That icon isn't one of the choices.")
    if color is not None and color not in GROUP_COLORS:
        raise SocialError("That colour isn't one of the choices.")
    with _Transaction(db) as conn:
        row = _owned(conn, group_public_id, owner)
        conn.execute(
            "UPDATE groups SET glyph = COALESCE(?, glyph), color = COALESCE(?, color) WHERE id = ?",
            (glyph, color, row["id"]),
        )
        return _icon(_group(conn, group_public_id), owner)


def set_image(db: Database, owner: int, group_public_id: str, upload: bytes) -> dict:
    """Makes an uploaded picture the group's icon. It is redrawn first (server/images.py), so
    what's stored is a plain 256px square. A reported picture stays hidden through a
    replacement, until it's reviewed: swapping the file can't put the old one back up."""
    with db.lock:
        _owned(db.conn, group_public_id, owner)  # refuse before doing the work
    picture = images.square_icon(upload)
    with _Transaction(db) as conn:
        row = _owned(conn, group_public_id, owner)
        conn.execute(
            "INSERT INTO group_images (group_id, data, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(group_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (row["id"], picture, _stamp()),
        )
        conn.execute("UPDATE groups SET image_tag = ? WHERE id = ?", (secrets.token_urlsafe(6), row["id"]))
        return _icon(_group(conn, group_public_id), owner)


def remove_image(db: Database, owner: int, group_public_id: str) -> dict:
    """Back to the drawn icon. With no picture there is nothing left to review."""
    with _Transaction(db) as conn:
        row = _owned(conn, group_public_id, owner)
        conn.execute("DELETE FROM group_images WHERE group_id = ?", (row["id"],))
        conn.execute("UPDATE groups SET image_tag = '', image_hidden = 0 WHERE id = ?", (row["id"],))
        _close_reports(conn, row["id"], "group_image", "removed")
        return _icon(_group(conn, group_public_id), owner)


def group_image(db: Database, group_public_id: str, viewer: int | None, reviewing: bool = False) -> bytes:
    """The group's picture, for anyone who has its address: group ids are long random links,
    and someone following an invite link sees the picture before signing in. A reported
    picture is served only to its owner and to an admin reviewing it."""
    with db.lock:
        row = _group(db.conn, group_public_id)
        if row["image_hidden"] and row["owner_id"] != viewer and not reviewing:
            raise SocialError("No picture.", 404)
        image = db.conn.execute("SELECT data FROM group_images WHERE group_id = ?", (row["id"],)).fetchone()
    if image is None:
        raise SocialError("No picture.", 404)
    return bytes(image["data"])


def disband(db: Database, owner: int, group_public_id: str) -> None:
    """Ends the group. Its members, invites, picture and leaderboard go with it, and the coins
    it cost are not returned."""
    with db.lock:
        row = _owned(db.conn, group_public_id, owner)
        db.conn.execute("DELETE FROM groups WHERE id = ?", (row["id"],))


def group_ref(db: Database, public_id: str) -> dict:
    """What a room needs to know about the group it's for."""
    with db.lock:
        row = _group(db.conn, public_id)
    return {"id": row["id"], "public_id": row["public_id"], "name": row["name"], "owner_id": row["owner_id"]}


def role_in(db: Database, group_public_id: str, user_id: int) -> str | None:
    with db.lock:
        row = _group(db.conn, group_public_id)
        return _role(db.conn, row["id"], user_id)


def member_ids(db: Database, group_id: int) -> set[int]:
    with db.lock:
        return {r["user_id"] for r in db.conn.execute("SELECT user_id FROM group_members WHERE group_id = ?", (group_id,))}


def invite_to_room(db: Database, group_id: int, room_code: str, host: int) -> int:
    """A group room opened: every other member's bell gets the code. Returns how many."""
    with _Transaction(db) as conn:
        members = [r["user_id"] for r in conn.execute("SELECT user_id FROM group_members WHERE group_id = ?", (group_id,))]
        others = [m for m in members if m != host]
        for member in others:
            _notify(conn, member, "room_invite", actor_id=host, group_id=group_id, room_code=room_code)
    return len(others)


# The global leaderboard.

LEADERBOARD_SIZE = 50
# Accounts whose latest accuracy flag an admin confirmed (server/anticheat.py). They are left off
# public boards, as on the live tables, and nothing else changes for them.
CONFIRMED_CHEATS = (
    "(SELECT f.user_id FROM accuracy_flags f WHERE f.status = 'confirmed' "
    "AND f.id = (SELECT MAX(id) FROM accuracy_flags WHERE user_id = f.user_id))"
)


def _places(scores: list[int]) -> list[int]:
    """A place for each score in a list already sorted high to low. Equal scores share a place,
    and the next one down skips, as on a podium: 900, 500, 500, 200 is 1, 2, 2, 4."""
    places: list[int] = []
    for index, score in enumerate(scores):
        places.append(places[-1] if index and score == scores[index - 1] else index + 1)
    return places


def leaderboard(db: Database, viewer: int, limit: int = LEADERBOARD_SIZE) -> dict:
    """The two global boards (Ryan, Nov 12, 2026): every group ranked by its members' combined
    prestige, and every player ranked by their own. Only prestige above zero is ranked, so the
    boards hold people and groups who have won something and not everyone who has signed up.
    The top `limit` of each comes back, with where the viewer and the viewer's groups stand
    even when that is further down. A reported group name or picture shows here as it does
    anywhere else."""
    with db.lock:
        conn = db.conn
        ranked = f"u.prestige > 0 AND u.id NOT IN {CONFIRMED_CHEATS}"
        top = conn.execute(
            f"SELECT {CARD} FROM users u WHERE {ranked} ORDER BY u.prestige DESC, u.name COLLATE NOCASE, u.id LIMIT ?",
            (limit,),
        ).fetchall()
        player_count = conn.execute(f"SELECT COUNT(*) FROM users u WHERE {ranked}").fetchone()[0]
        me = conn.execute(f"SELECT u.prestige, u.id IN {CONFIRMED_CHEATS} AS hidden FROM users u WHERE u.id = ?", (viewer,)).fetchone()
        my_place = None
        if me["prestige"] > 0 and not me["hidden"]:
            my_place = 1 + conn.execute(f"SELECT COUNT(*) FROM users u WHERE {ranked} AND u.prestige > ?", (me["prestige"],)).fetchone()[0]
        # Groups are few (each costs coins to start), so all of them are totalled and ranked here.
        groups = conn.execute(
            "SELECT g.*, COALESCE(SUM(u.prestige), 0) AS total, COUNT(m.user_id) AS members "
            "FROM groups g JOIN group_members m ON m.group_id = g.id JOIN users u ON u.id = m.user_id "
            "GROUP BY g.id HAVING total > 0 ORDER BY total DESC, g.name COLLATE NOCASE, g.id"
        ).fetchall()
        mine = {r["group_id"]: r["role"] for r in conn.execute("SELECT group_id, role FROM group_members WHERE user_id = ?", (viewer,))}
    group_rows = [
        {
            "place": place,
            "public_id": row["public_id"],
            "name": _group_name(row, viewer),
            "icon": _icon(row, viewer),
            "member_count": row["members"],
            "prestige": row["total"],
            "role": mine.get(row["id"]),
        }
        for place, row in zip(_places([row["total"] for row in groups]), groups)
    ]
    players = [
        {**_card(row), "place": place, "you": row["id"] == viewer}
        for place, row in zip(_places([row["prestige"] for row in top]), top)
    ]
    return {
        "players": players,
        "player_count": player_count,
        "you": {"place": my_place, "prestige": me["prestige"]},
        "groups": group_rows[:limit],
        "group_count": len(group_rows),
        "your_groups": [{"place": g["place"], "public_id": g["public_id"], "name": g["name"]} for g in group_rows if g["role"]],
    }


# Reports and review.

# What can be reported about a group: the column that hides it, and the column holding what
# was reported (a picture has no text; the review page shows the picture itself).
GROUP_REPORTS = {
    "group_name": ("name_hidden", "name"),
    "group_bio": ("bio_hidden", "bio"),
    "group_image": ("image_hidden", None),
}
REPORT_KINDS = ("bio", *GROUP_REPORTS)


def report(db: Database, reporter: int, kind: str, public_id: str) -> None:
    """Hides the reported thing (a player's bio; a group's name, bio or picture) from everyone
    but its owner at once, until an admin restores or clears it. One open report per reporter
    per thing; a daily cap."""
    if kind not in REPORT_KINDS:
        raise SocialError("Only bios and a group's name, bio or picture can be reported.")
    with _Transaction(db) as conn:
        since = _stamp(_now() - timedelta(days=1))
        today = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE reporter_id = ? AND created_at > ?", (reporter, since)
        ).fetchone()[0]
        if today >= MAX_REPORTS_PER_DAY:
            raise SocialError("That's a lot of reports for one day. Try again tomorrow.", 429)
        if kind == "bio":
            target = conn.execute("SELECT id, bio FROM users WHERE public_id = ?", (public_id,)).fetchone()
            if target is None:
                raise SocialError("No player has that link.", 404)
            if target["id"] == reporter:
                raise SocialError("That's your own bio.")
            if not target["bio"]:
                raise SocialError("There's nothing to report.")
            duplicate = conn.execute(
                "SELECT 1 FROM reports WHERE reporter_id = ? AND kind = 'bio' AND user_id = ? AND status = 'open'",
                (reporter, target["id"]),
            ).fetchone()
            if not duplicate:
                conn.execute(
                    "INSERT INTO reports (reporter_id, kind, user_id, text, created_at) VALUES (?, 'bio', ?, ?, ?)",
                    (reporter, target["id"], target["bio"], _stamp()),
                )
            conn.execute("UPDATE users SET bio_hidden = 1 WHERE id = ?", (target["id"],))
        else:
            hidden, column = GROUP_REPORTS[kind]
            target = _group(conn, public_id)
            if target["owner_id"] == reporter:
                raise SocialError("That's your own group.")
            if not (target[column] if column else target["image_tag"]):
                raise SocialError("There's nothing to report.")
            duplicate = conn.execute(
                "SELECT 1 FROM reports WHERE reporter_id = ? AND kind = ? AND group_id = ? AND status = 'open'",
                (reporter, kind, target["id"]),
            ).fetchone()
            if not duplicate:
                conn.execute(
                    "INSERT INTO reports (reporter_id, kind, group_id, text, created_at) VALUES (?, ?, ?, ?, ?)",
                    (reporter, kind, target["id"], target[column] if column else "", _stamp()),
                )
            conn.execute(f"UPDATE groups SET {hidden} = 1 WHERE id = ?", (target["id"],))


def open_reports(db: Database) -> list[dict]:
    """The review queue: one row per reported thing, with how many reports it has."""
    with db.lock:
        conn = db.conn
        rows = conn.execute(
            "SELECT r.*, g.public_id AS group_public_id, g.name AS group_name, g.image_tag AS group_image_tag "
            "FROM reports r LEFT JOIN groups g ON g.id = r.group_id WHERE r.status = 'open' ORDER BY r.id"
        ).fetchall()
        cards = _cards(conn, sorted({row["user_id"] for row in rows if row["user_id"]} | {row["reporter_id"] for row in rows}))
    queue: dict[tuple, dict] = {}
    for row in rows:
        key = (row["kind"], row["user_id"] or row["group_id"])
        if key not in queue:
            queue[key] = {
                "id": row["id"],
                "kind": row["kind"],
                "text": row["text"],
                "at": row["created_at"],
                "owner": cards.get(row["user_id"]) if row["kind"] == "bio" else None,
                "group": {"public_id": row["group_public_id"], "name": row["group_name"]} if row["group_id"] else None,
                # A reported picture, as it is now: only an admin's request for it is answered.
                "image": f"/api/groups/{row['group_public_id']}/image?v={row['group_image_tag']}"
                if row["kind"] == "group_image" and row["group_image_tag"]
                else None,
                "reporters": [],
            }
        queue[key]["reporters"].append(cards[row["reporter_id"]])
    return list(queue.values())


def resolve(db: Database, report_id: int, action: str) -> None:
    """restore: show it again. clear: empty the bio (a player's or a group's), rename the group
    "Group N", or take its picture down. Either way every open report on the same thing closes."""
    if action not in ("restore", "clear"):
        raise SocialError("Restore or clear.")
    with _Transaction(db) as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if row is None or row["status"] != "open":
            raise SocialError("That report is already closed.", 404)
        status = "restored" if action == "restore" else "cleared"
        if row["kind"] == "bio":
            if action == "clear":
                conn.execute("UPDATE users SET bio = '' WHERE id = ?", (row["user_id"],))
            conn.execute("UPDATE users SET bio_hidden = 0 WHERE id = ?", (row["user_id"],))
            match = ("user_id", row["user_id"])
        else:
            hidden, _ = GROUP_REPORTS[row["kind"]]
            if action == "clear" and row["kind"] == "group_name":
                conn.execute("UPDATE groups SET name = ? WHERE id = ?", (f"Group {row['group_id']}", row["group_id"]))
            elif action == "clear" and row["kind"] == "group_bio":
                conn.execute("UPDATE groups SET bio = '' WHERE id = ?", (row["group_id"],))
            elif action == "clear":
                conn.execute("DELETE FROM group_images WHERE group_id = ?", (row["group_id"],))
                conn.execute("UPDATE groups SET image_tag = '' WHERE id = ?", (row["group_id"],))
            conn.execute(f"UPDATE groups SET {hidden} = 0 WHERE id = ?", (row["group_id"],))
            match = ("group_id", row["group_id"])
        conn.execute(
            f"UPDATE reports SET status = ?, resolved_at = ? WHERE kind = ? AND {match[0]} = ? AND status = 'open'",
            (status, _stamp(), row["kind"], match[1]),
        )
