import base64
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from server import app as app_module
from server import push, social
from server.db import Database
from server.tests.test_social import account, app_db, client_for, fake_verify  # noqa: F401  (fixture)


def uid(db, name):
    return account(db, name)[0]["id"]


def public_id(db, user_id):
    return db._fetch_user(user_id)["public_id"]


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "push.db")


@pytest.fixture
def keys(monkeypatch):
    public, private = push.new_keys()
    monkeypatch.setenv("VAPID_PUBLIC_KEY", public)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", private)
    return public, private


def latest(db, user_id):
    return db.conn.execute("SELECT MAX(id) FROM notifications WHERE user_id = ?", (user_id,)).fetchone()[0]


def subscription_keys():
    """A browser's half of a push subscription: its P-256 public key and auth secret."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    encode = lambda data: base64.urlsafe_b64encode(data).rstrip(b"=").decode()  # noqa: E731
    return encode(raw), encode(os.urandom(16))


class TestMessages:
    def test_a_friend_request_says_who_and_opens_social(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        social.send_request(db, ann, ben)
        user_id, payload = push.message(db, latest(db, ben))
        assert user_id == ben
        assert payload["body"] == "Ann wants to be friends." and payload["url"] == "/social"

    def test_an_accepted_request_opens_the_friend_s_profile(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        social.send_request(db, ann, ben)
        social.accept_request(db, ben, ann)
        _, payload = push.message(db, latest(db, ann))
        assert payload["body"] == "Ben accepted your friend request."
        assert payload["url"] == f"/u/{public_id(db, ben)}"

    def test_group_invites_and_room_invites(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Fintech Club")
        social.invite(db, ann, group["public_id"], ben)
        _, invite = push.message(db, latest(db, ben))
        assert invite["body"] == "Ann invited you to Fintech Club." and invite["url"] == f"/g/{group['public_id']}"
        social.join(db, ben, group["public_id"])
        row_id = social.group_ref(db, group["public_id"])["id"]
        social.invite_to_room(db, row_id, "VWAP", ann)
        _, room = push.message(db, latest(db, ben))
        assert room["body"] == "Ann opened a game for Fintech Club. Room VWAP." and room["url"] == "/?room=VWAP"

    def test_a_member_joining_stays_in_the_bell(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Fintech Club")
        social.invite(db, ann, group["public_id"], ben)
        social.join(db, ben, group["public_id"])
        assert db.conn.execute("SELECT kind FROM notifications WHERE id = ?", (latest(db, ann),)).fetchone()[0] == "group_joined"
        assert push.message(db, latest(db, ann)) is None

    def test_a_hidden_group_name_stays_hidden(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Fintech Club")
        db.conn.execute("UPDATE groups SET name_hidden = 1")
        social.invite(db, ann, group["public_id"], ben)
        assert social.HIDDEN_GROUP_NAME in push.message(db, latest(db, ben))[1]["body"]

    def test_a_notification_that_never_committed_is_skipped(self, db):
        assert push.message(db, 12345) is None


class TestDelivery:
    def test_every_device_gets_it_and_gone_ones_are_dropped(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        push.subscribe(db, ben, "https://push.example/phone", "p", "a")
        push.subscribe(db, ben, "https://push.example/old-laptop", "p", "a")
        social.send_request(db, ann, ben)
        sent = []

        def send(subscription, data, ttl, urgency):
            sent.append((subscription["endpoint"], json.loads(data)["body"], ttl, urgency))
            return 410 if "old" in subscription["endpoint"] else 201

        assert push.deliver(db, latest(db, ben), send) == 1
        assert sorted(sent) == [
            ("https://push.example/old-laptop", "Ann wants to be friends.", push.DEFAULT_TTL, "normal"),
            ("https://push.example/phone", "Ann wants to be friends.", push.DEFAULT_TTL, "normal"),
        ]
        assert [d["endpoint"] for d in push.devices(db, ben)] == ["https://push.example/phone"]

    def test_a_room_invite_is_urgent_and_short_lived(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Fintech Club")
        social.invite(db, ann, group["public_id"], ben)
        social.join(db, ben, group["public_id"])
        social.invite_to_room(db, social.group_ref(db, group["public_id"])["id"], "VWAP", ann)
        push.subscribe(db, ben, "https://push.example/phone", "p", "a")
        seen = []
        push.deliver(db, latest(db, ben), lambda s, d, ttl, urgency: seen.append((ttl, urgency)) or 201)
        assert seen == [(15 * 60, "high")]

    def test_a_failing_push_service_never_raises(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        push.subscribe(db, ben, "https://push.example/phone", "p", "a")
        social.send_request(db, ann, ben)

        def broken(*_):
            raise ConnectionError("offline")

        assert push.deliver(db, latest(db, ben), broken) == 0
        assert len(push.devices(db, ben)) == 1  # a network error isn't a reason to forget the phone

    def test_the_background_thread_sends_what_social_records(self, db, monkeypatch):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        push.subscribe(db, ben, "https://push.example/phone", "p", "a")
        sent = threading.Event()
        pusher = push.Pusher(lambda: db, lambda *_: sent.set() or 201)
        monkeypatch.setattr(social, "on_notify", pusher.enqueue)
        social.send_request(db, ann, ben)
        assert sent.wait(3)


class TestSubscriptions:
    def test_a_device_moves_to_whoever_signed_in_on_it_last(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        push.subscribe(db, ann, "https://push.example/shared", "p", "a")
        push.subscribe(db, ben, "https://push.example/shared", "p2", "a2")
        assert push.devices(db, ann) == []
        assert [d["p256dh"] for d in push.devices(db, ben)] == ["p2"]

    def test_an_account_keeps_its_newest_devices(self, db):
        ann = uid(db, "Ann")
        for n in range(push.MAX_DEVICES + 2):
            push.subscribe(db, ann, f"https://push.example/{n}", "p", "a")
        kept = {d["endpoint"] for d in push.devices(db, ann)}
        assert len(kept) == push.MAX_DEVICES and "https://push.example/0" not in kept

    def test_unsubscribing_only_touches_your_own_device(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        push.subscribe(db, ann, "https://push.example/a", "p", "a")
        push.unsubscribe(db, ben, "https://push.example/a")
        assert len(push.devices(db, ann)) == 1
        push.unsubscribe(db, ann, "https://push.example/a")
        assert push.devices(db, ann) == []


class TestKeys:
    def test_new_keys_are_a_raw_p256_pair(self):
        from py_vapid import Vapid01

        public, private = push.new_keys()
        pad = lambda text: text + "=" * (-len(text) % 4)  # noqa: E731
        assert len(base64.urlsafe_b64decode(pad(public))) == 65 and public.startswith("B")
        assert len(base64.urlsafe_b64decode(pad(private))) == 32
        assert Vapid01.from_string(private).public_key is not None

    def test_push_is_off_without_both_keys(self, monkeypatch):
        monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
        monkeypatch.setenv("VAPID_PRIVATE_KEY", "x")
        assert not push.enabled() and push.start(lambda: None) is None

    def test_the_subject_defaults_to_the_site(self, monkeypatch):
        monkeypatch.delenv("VAPID_SUBJECT", raising=False)
        monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:5173,https://almanac.example")
        assert push.subject() == "https://almanac.example"
        monkeypatch.setenv("VAPID_SUBJECT", "mailto:club@example.com")
        assert push.subject() == "mailto:club@example.com"


class FakePushService(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        FakePushService.received.append((dict(self.headers), body))
        self.send_response(201)
        self.end_headers()

    def log_message(self, *_):
        pass


class TestRealSender:
    def test_pywebpush_encrypts_and_signs_the_request(self, keys):
        server = HTTPServer(("127.0.0.1", 0), FakePushService)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        FakePushService.received = []
        try:
            p256dh, auth = subscription_keys()
            endpoint = f"http://127.0.0.1:{server.server_port}/push/abc"
            status = push.webpush_sender()({"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}, '{"body":"hi"}', 60, "high")
        finally:
            server.shutdown()
        assert status == 201
        sent, body = FakePushService.received[0]
        headers = {name.lower(): value for name, value in sent.items()}
        # RFC 8292 form, which Apple's push service requires: "vapid t=<signed JWT>, k=<our key>".
        assert headers["authorization"].startswith("vapid t=") and f"k={keys[0]}" in headers["authorization"]
        assert headers["content-encoding"] == "aes128gcm" and headers["ttl"] == "60" and headers["urgency"] == "high"
        assert b"hi" not in body  # encrypted for the device, unreadable to the push service


class TestApi:
    def test_the_key_is_null_while_push_is_off(self, app_db, monkeypatch):
        monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
        assert TestClient(app_module.app).get("/api/push/key").json() == {"public_key": None}
        ann = client_for("Ann")
        sub = {"endpoint": "https://push.example/x", "keys": {"p256dh": "p", "auth": "a"}}
        assert ann.post("/api/push/subscriptions", json=sub).status_code == 503

    def test_subscribe_and_remove(self, app_db, keys):
        assert TestClient(app_module.app).get("/api/push/key").json() == {"public_key": keys[0]}
        sub = {"endpoint": "https://push.example/x", "keys": {"p256dh": "p", "auth": "a"}}
        assert TestClient(app_module.app).post("/api/push/subscriptions", json=sub).status_code == 401
        ann = client_for("Ann")
        assert ann.post("/api/push/subscriptions", json=sub).json() == {"on": True}
        me = ann.get("/api/me").json()["user"]["id"]
        assert [d["endpoint"] for d in push.devices(app_db, me)] == ["https://push.example/x"]
        bad = {**sub, "endpoint": "http://evil.example/x"}
        assert ann.post("/api/push/subscriptions", json=bad).status_code == 400
        assert ann.post("/api/push/subscriptions/remove", json={"endpoint": sub["endpoint"]}).json() == {"on": False}
        assert push.devices(app_db, me) == []

    @pytest.mark.skipif(not (app_module.CLIENT_DIST / "sw.js").is_file(), reason="client not built")
    def test_the_service_worker_is_served_from_the_root_and_rechecked(self, app_db):
        response = TestClient(app_module.app).get("/sw.js")
        assert response.status_code == 200 and "javascript" in response.headers["content-type"]
        assert response.headers["cache-control"] == "no-cache" and "push" in response.text
        manifest = TestClient(app_module.app).get("/manifest.webmanifest")
        assert manifest.headers["content-type"].startswith("application/manifest+json")
        assert manifest.json()["display"] == "standalone"
