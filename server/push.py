"""Web push (M5): the bell's notifications on a phone's lock screen.

A signed-in player turns notifications on for a device; the browser subscribes with the
server's VAPID public key and the server stores the subscription. Whenever server/social.py
records a notification, its id goes on a queue, and a background thread sends it to each of
that player's devices through the browser's push service. Nothing is sent from inside a
request or while the database lock is held, and a notification whose transaction rolled back
is simply not found and skipped. A subscription the push service says is gone (404 or 410) is
deleted.

Off unless VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are set (Fly secrets in production). Keys
are the raw P-256 pair, base64url without padding: `python -m server.push --keys` prints one.
VAPID_SUBJECT is the contact the push services see; it defaults to the site's own https URL
taken from the first ALLOWED_ORIGINS entry. On iPhone, push works only once Almanac is added
to the Home Screen (iOS 16.4 and later); the client says so.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import queue
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from server import social
from server.auth import current_user

if TYPE_CHECKING:
    from server.db import Database

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS push_subscriptions_by_user ON push_subscriptions(user_id);
"""

MAX_DEVICES = 10  # per account; the oldest goes when an eleventh subscribes
SETTLE_SECONDS = 0.2  # lets the transaction that recorded a notification commit first
# Kinds that reach the lock screen. A group's owner isn't buzzed for every member who joins;
# that stays in the bell.
PUSHED_KINDS = ("friend_request", "friend_accepted", "group_invite", "room_invite")
# How long a push service keeps trying a phone that's off. A room invite is stale in minutes.
TTL_SECONDS = {"room_invite": 15 * 60}
DEFAULT_TTL = 24 * 60 * 60
GONE = (404, 410)


def install(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Keys.


def public_key() -> str | None:
    return os.environ.get("VAPID_PUBLIC_KEY") or None


def enabled() -> bool:
    return bool(public_key() and os.environ.get("VAPID_PRIVATE_KEY"))


def subject() -> str:
    configured = os.environ.get("VAPID_SUBJECT")
    if configured:
        return configured
    origins = [o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.startswith("https://")]
    return origins[0] if origins else "mailto:noreply@localhost"


def new_keys() -> tuple[str, str]:
    """A fresh VAPID pair as (public, private), base64url without padding."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    raw_public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    raw_private = key.private_numbers().private_value.to_bytes(32, "big")
    encode = lambda data: base64.urlsafe_b64encode(data).rstrip(b"=").decode()  # noqa: E731
    return encode(raw_public), encode(raw_private)


# Subscriptions.


def subscribe(db: Database, user_id: int, endpoint: str, p256dh: str, auth: str) -> None:
    """Stores a device's subscription for this account. A device that signs into another
    account moves to it, so a shared phone never buzzes for someone who signed out."""
    with db.lock:
        db.conn.execute(
            "INSERT INTO push_subscriptions (endpoint, user_id, p256dh, auth, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id, p256dh = excluded.p256dh, "
            "auth = excluded.auth, created_at = excluded.created_at",
            (endpoint, user_id, p256dh, auth, _stamp()),
        )
        db.conn.execute(
            "DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint NOT IN "
            "(SELECT endpoint FROM push_subscriptions WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?)",
            (user_id, user_id, MAX_DEVICES),
        )


def unsubscribe(db: Database, user_id: int, endpoint: str) -> None:
    with db.lock:
        db.conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ? AND user_id = ?", (endpoint, user_id))


def devices(db: Database, user_id: int) -> list[sqlite3.Row]:
    with db.lock:
        return db.conn.execute("SELECT * FROM push_subscriptions WHERE user_id = ?", (user_id,)).fetchall()


def _drop(db: Database, endpoint: str) -> None:
    with db.lock:
        db.conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


# What a push says.


def message(db: Database, notification_id: int) -> tuple[int, dict] | None:
    """(recipient, payload) for a notification, or None if it is gone (its transaction rolled
    back) or of a kind that isn't pushed. The text matches the bell's."""
    with db.lock:
        row = db.conn.execute(
            "SELECT n.*, u.name AS actor_name, u.public_id AS actor_public_id, "
            "g.public_id AS group_public_id, g.name AS group_name, g.name_hidden, g.owner_id "
            "FROM notifications n LEFT JOIN users u ON u.id = n.actor_id LEFT JOIN groups g ON g.id = n.group_id "
            "WHERE n.id = ?",
            (notification_id,),
        ).fetchone()
    if row is None or row["kind"] not in PUSHED_KINDS:
        return None
    who = row["actor_name"] or "Someone"
    group = "a group"
    if row["group_public_id"]:
        hidden = row["name_hidden"] and row["owner_id"] != row["user_id"]
        group = social.HIDDEN_GROUP_NAME if hidden else row["group_name"]
    match row["kind"]:
        case "friend_request":
            body, url = f"{who} wants to be friends.", "/social"
        case "friend_accepted":
            body, url = f"{who} accepted your friend request.", f"/u/{row['actor_public_id']}"
        case "group_invite":
            body, url = f"{who} invited you to {group}.", f"/g/{row['group_public_id']}"
        case _:  # room_invite
            body = f"{who} opened a game for {group}. Room {row['room_code']}."
            url = f"/?room={row['room_code']}"
    payload = {"title": "Almanac", "body": body, "url": url, "tag": f"{row['kind']}:{row['id']}"}
    return row["user_id"], payload


# Sending.


Sender = Callable[[dict, str, int, str], int]  # (subscription, data, ttl, urgency) -> HTTP status


def webpush_sender() -> Sender:
    """Sends through pywebpush with the configured keys. Returns the push service's status."""
    from py_vapid import Vapid02
    from pywebpush import WebPushException, webpush

    vapid = Vapid02.from_string(os.environ["VAPID_PRIVATE_KEY"])

    def send(subscription: dict, data: str, ttl: int, urgency: str) -> int:
        try:
            response = webpush(
                subscription_info=subscription,
                data=data,
                vapid_private_key=vapid,
                vapid_claims={"sub": subject()},  # a fresh dict: webpush writes aud and exp into it
                ttl=ttl,
                headers={"Urgency": urgency},
                timeout=10,
            )
            return response.status_code
        except WebPushException as error:
            return error.response.status_code if error.response is not None else 0

    return send


def deliver(db: Database, notification_id: int, send: Sender) -> int:
    """Sends one notification to every device of its recipient. Returns how many accepted it."""
    found = message(db, notification_id)
    if found is None:
        return 0
    user_id, payload = found
    kind = payload["tag"].split(":")[0]
    data = json.dumps(payload)
    ttl = TTL_SECONDS.get(kind, DEFAULT_TTL)
    urgency = "high" if kind == "room_invite" else "normal"
    delivered = 0
    for device in devices(db, user_id):
        subscription = {"endpoint": device["endpoint"], "keys": {"p256dh": device["p256dh"], "auth": device["auth"]}}
        try:
            status = send(subscription, data, ttl, urgency)
        except Exception:  # a network failure must never take the sender thread down
            log.exception("push failed endpoint=%s", device["endpoint"][:60])
            continue
        if status in GONE:
            _drop(db, device["endpoint"])
            log.info("push subscription gone user=%s", user_id)
        elif 200 <= status < 300:
            delivered += 1
        else:
            log.warning("push refused status=%s user=%s", status, user_id)
    return delivered


class Pusher:
    """A background thread that sends queued notifications, one at a time."""

    def __init__(self, db: Callable[[], Database], send: Sender):
        self.db = db
        self.send = send
        self.queue: queue.Queue[int] = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="push", daemon=True)
        self.thread.start()

    def enqueue(self, notification_id: int) -> None:
        self.queue.put(notification_id)

    def _run(self) -> None:
        while True:
            notification_id = self.queue.get()
            time.sleep(SETTLE_SECONDS)
            try:
                deliver(self.db(), notification_id, self.send)
            except Exception:
                log.exception("push delivery failed notification=%s", notification_id)


def start(db: Callable[[], Database]) -> Pusher | None:
    """Starts sending if keys are configured, and hooks social's notifications to it."""
    if not enabled():
        log.info("web push off: VAPID keys not set")
        return None
    pusher = Pusher(db, webpush_sender())
    social.on_notify = pusher.enqueue
    log.info("web push on")
    return pusher


# HTTP.


router = APIRouter(prefix="/api/push")


class Keys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class Subscription(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1000)
    keys: Keys


class Endpoint(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1000)


def _me(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in first.")
    return user


@router.get("/key")
def key() -> dict:
    """The public key a browser subscribes with; null when push is off."""
    return {"public_key": public_key() if enabled() else None}


@router.post("/subscriptions")
def add(body: Subscription, request: Request) -> dict:
    user = _me(request)
    if not enabled():
        raise HTTPException(503, "Notifications aren't set up on this server.")
    if not body.endpoint.startswith("https://"):
        raise HTTPException(400, "That isn't a push address.")
    subscribe(request.app.state.db, user["id"], body.endpoint, body.keys.p256dh, body.keys.auth)
    return {"on": True}


@router.post("/subscriptions/remove")
def remove(body: Endpoint, request: Request) -> dict:
    user = _me(request)
    unsubscribe(request.app.state.db, user["id"], body.endpoint)
    return {"on": False}


if __name__ == "__main__":
    import sys

    if "--keys" in sys.argv:
        public, private = new_keys()
        print(f"VAPID_PUBLIC_KEY={public}\nVAPID_PRIVATE_KEY={private}")
