from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from server import app as app_module
from server import social
from server.db import Database, GameResult, SeatRecord
from server.moderation import clean_group_name, clean_handle
from server.protocol import RoomConfig
from server.rooms import Room, RoomError
from server.tests.test_rooms import QUESTIONS, Clock, receive_until


FUNDS = 20_000  # coins every test account holds: enough to start groups (test_groups.py tests the charge)


def account(db, name):
    user, token = db.sign_in_google(f"g-{name}", f"{name.lower()}@example.com", name)
    db.conn.execute("UPDATE users SET coins = ? WHERE id = ?", (FUNDS, user["id"]))
    return user, token


def uid(db, name):
    return account(db, name)[0]["id"]


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "social.db")


class TestIdentity:
    def test_every_account_gets_a_public_id_and_friend_code(self, db):
        user, _ = account(db, "Ann")
        assert len(user["public_id"]) >= 10 and len(user["friend_code"]) == social.FRIEND_CODE_LENGTH
        assert user["handle"] is None and user["bio_hidden"] is False
        again, _ = account(db, "Ann")  # signing in again keeps them
        assert (again["public_id"], again["friend_code"]) == (user["public_id"], user["friend_code"])

    def test_old_accounts_are_given_them_at_startup(self, tmp_path):
        path = tmp_path / "old.db"
        db = Database(path)
        user, _ = account(db, "Ann")
        db.conn.execute("UPDATE users SET public_id = NULL, friend_code = NULL")
        reopened = Database(path)
        row = reopened.conn.execute("SELECT public_id, friend_code FROM users WHERE id = ?", (user["id"],)).fetchone()
        assert row["public_id"] and row["friend_code"]

    @pytest.mark.parametrize("text", ["@Ryan_C", "  ryan_c ", "RYAN_C"])
    def test_handles_are_stored_lowercase_without_the_at(self, text):
        assert clean_handle(text) == "ryan_c"

    @pytest.mark.parametrize("text", ["ab", "1ryan", "ryan corle", "x" * 21, "admin", "fuckface", "big_shit", "n1gger"])
    def test_bad_handles_are_refused(self, text):
        with pytest.raises(ValueError):
            clean_handle(text)

    # Short words are matched whole, so these pass. The worst words are caught inside a handle
    # too, which costs the odd innocent one ("scunthorpe"); that trade is deliberate.
    @pytest.mark.parametrize("text", ["dickens", "hancock", "cocktail_hour"])
    def test_innocent_handles_pass(self, text):
        assert clean_handle(text) == text

    def test_handles_are_unique_and_can_be_cleared(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        assert social.set_handle(db, ann, "@Annie") == "annie"
        with pytest.raises(social.SocialError, match="taken"):
            social.set_handle(db, ben, "ANNIE")
        assert social.set_handle(db, ann, "") is None
        assert social.set_handle(db, ben, "annie") == "annie"

    def test_a_new_friend_code_replaces_the_old(self, db):
        ann = uid(db, "Ann")
        old = db._fetch_user(ann)["friend_code"]
        new = social.new_code(db, ann)
        assert new != old and social.user_id_for_code(db, new.lower()[:4] + "-" + new[4:]) == ann
        with pytest.raises(social.SocialError):
            social.user_id_for_code(db, old)

    def test_group_names_are_checked(self):
        assert clean_group_name("  IU   FinTech Club ") == "IU FinTech Club"
        for bad in ("ab", "x" * 33, "Shit Traders"):
            with pytest.raises(ValueError):
                clean_group_name(bad)


class TestFriends:
    def test_request_accept_and_both_sides_hear(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        assert social.send_request(db, ann, ben) == "requested"
        assert social.relations(db, ann, [ben]) == {ben: "requested"}
        assert social.relations(db, ben, [ann]) == {ann: "incoming"}
        assert [n["kind"] for n in social.notifications(db, ben)["items"]] == ["friend_request"]
        assert social.notifications(db, ben)["items"][0]["open"] is True
        assert social.accept_request(db, ben, ann) == "friend"
        assert social.notifications(db, ben)["items"][0]["open"] is False  # settled: no buttons
        assert social.relations(db, ann, [ben]) == {ben: "friend"}
        bell = social.notifications(db, ann)
        assert bell["unread"] == 1 and bell["items"][0]["kind"] == "friend_accepted"
        assert bell["items"][0]["actor"]["name"] == "Ben"
        assert social.notifications(db, ben)["unread"] == 0  # accepting reads the request

    def test_asking_someone_who_asked_you_accepts(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        social.send_request(db, ann, ben)
        assert social.send_request(db, ben, ann) == "friend"

    def test_a_decline_is_silent(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        social.send_request(db, ann, ben)
        social.decline_request(db, ben, ann)
        assert social.relations(db, ann, [ben]) == {ben: "requested"}
        assert social.relations(db, ben, [ann]) == {ann: "none"}
        assert social.overview(db, ben)["incoming"] == []

    def test_cancel_and_unfriend(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        social.send_request(db, ann, ben)
        social.remove(db, ann, ben)
        assert social.relations(db, ben, [ann]) == {ann: "none"}
        social.send_request(db, ann, ben)
        social.accept_request(db, ben, ann)
        social.remove(db, ben, ann)
        assert social.relations(db, ann, [ben]) == {ben: "none"}

    def test_blocking_ends_everything_and_silences_requests(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        social.set_handle(db, ann, "annie")
        social.send_request(db, ann, ben)
        social.accept_request(db, ben, ann)
        social.block(db, ann, ben)
        assert social.relations(db, ann, [ben]) == {ben: "blocked"}
        assert social.search(db, ben, "ann") == []
        assert social.send_request(db, ben, ann) == "requested"  # looks pending to Ben...
        assert social.overview(db, ann)["incoming"] == []  # ...and never reaches Ann
        with pytest.raises(social.SocialError, match="Unblock"):
            social.send_request(db, ann, ben)
        with pytest.raises(social.SocialError):
            social.public_profile(db, ben, db._fetch_user(ann)["public_id"])
        social.unblock(db, ann, ben)
        # Ben's request arrived while blocked, so it stays silently declined after the unblock.
        assert social.relations(db, ann, [ben]) == {ben: "none"}
        assert social.relations(db, ben, [ann]) == {ann: "requested"}

    def test_pending_requests_are_capped(self, db, monkeypatch):
        monkeypatch.setattr(social, "MAX_PENDING_SENT", 2)
        ann = uid(db, "Ann")
        others = [uid(db, name) for name in ("Ben", "Cat", "Dan")]
        social.send_request(db, ann, others[0])
        social.send_request(db, ann, others[1])
        with pytest.raises(social.SocialError, match="waiting"):
            social.send_request(db, ann, others[2])

    def test_you_cant_add_yourself(self, db):
        ann = uid(db, "Ann")
        with pytest.raises(social.SocialError):
            social.send_request(db, ann, ann)


class TestSearchAndOverview:
    def test_search_matches_handles_only(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        social.set_handle(db, ben, "benny_trades")
        assert [r["handle"] for r in social.search(db, ann, "@ben")] == ["benny_trades"]
        assert social.search(db, ann, "Ben") != [] and social.search(db, ann, "ben@example") == []
        assert social.search(db, ann, "b") == []  # too short
        assert social.search(db, ann, "_") == []  # LIKE wildcards are literal
        assert social.search(db, ben, "benny") == []  # not yourself
        uid(db, "Cat")  # no handle: not findable
        assert social.search(db, ann, "cat") == []

    def test_friends_leaderboard_and_tablemates(self, db):
        ann, ben, cat, dan = (uid(db, n) for n in ("Ann", "Ben", "Cat", "Dan"))
        db.conn.execute("UPDATE users SET prestige = 500 WHERE id = ?", (cat,))
        for other in (ben, cat):
            social.send_request(db, ann, other)
            social.accept_request(db, other, ann)
        seats = [
            SeatRecord("p1", "Ann", ann, False, 1, Decimal(10)),
            SeatRecord("p2", "Dan", dan, False, 2, Decimal(-10)),
            SeatRecord("p3", "Guest", None, False, 3, Decimal(0)),
        ]
        db.record_game("ABCD", 3, 3, [GameResult(ann, "Ann", Decimal(10), Decimal(10), 1, 0, 0)], seats=seats)
        view = social.overview(db, ann)
        assert [f["name"] for f in view["friends"]] == ["Cat", "Ben"]  # by prestige
        assert [(m["name"], m["relation"]) for m in view["tablemates"]] == [("Dan", "none")]
        assert view["me"]["friend_code"] and "email" not in view["me"]


class TestGroups:
    def test_create_invite_join_and_the_owner_hears(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "IU FinTech Club")
        assert group["role"] == "owner" and group["member_count"] == 1
        with pytest.raises(social.SocialError, match="no longer open"):
            social.join(db, ben, group["public_id"])  # no invite
        assert social.invite(db, ann, group["public_id"], ben) == "invited"
        assert social.invite(db, ann, group["public_id"], ben) == "already_invited"
        assert social.notifications(db, ben)["items"][0]["group"]["name"] == "IU FinTech Club"
        assert social.overview(db, ben)["group_invites"][0]["invited_by"]["name"] == "Ann"
        assert social.join(db, ben, group["public_id"])["role"] == "member"
        assert social.notifications(db, ben)["items"][0]["open"] is False  # joined: the invite is settled
        assert social.notifications(db, ann)["items"][0]["kind"] == "group_joined"
        detail = social.group_detail(db, ben, group["public_id"])
        assert detail["member_count"] == 2 and detail["role"] == "member"

    def test_only_the_owner_manages(self, db):
        ann, ben, cat = uid(db, "Ann"), uid(db, "Ben"), uid(db, "Cat")
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.join(db, ben, group, via_room=True)
        for action in (
            lambda: social.invite(db, ben, group, cat),
            lambda: social.rename(db, ben, group, "Mine now"),
            lambda: social.remove_member(db, ben, group, ann),
            lambda: social.disband(db, ben, group),
        ):
            with pytest.raises(social.SocialError, match="owner"):
                action()
        with pytest.raises(social.SocialError, match="Disband"):
            social.leave(db, ann, group)
        social.remove_member(db, ann, group, ben)
        assert social.role_in(db, group, ben) is None

    def test_owner_sees_friends_to_invite_and_members_rank_by_prestige(self, db):
        ann, ben, cat = uid(db, "Ann"), uid(db, "Ben"), uid(db, "Cat")
        db.conn.execute("UPDATE users SET prestige = 900 WHERE id = ?", (ben,))
        for other in (ben, cat):
            social.send_request(db, ann, other)
            social.accept_request(db, other, ann)
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.invite(db, ann, group, cat)
        social.join(db, ben, group, via_room=True)
        detail = social.group_detail(db, ann, group)
        assert [m["name"] for m in detail["members"]] == ["Ben", "Ann"]
        assert detail["invitable"] == [] and [p["name"] for p in detail["pending"]] == ["Cat"]

    def test_caps(self, db, monkeypatch):
        ann, ben, cat = uid(db, "Ann"), uid(db, "Ben"), uid(db, "Cat")
        monkeypatch.setattr(social, "MAX_GROUPS_OWNED", 1)
        monkeypatch.setattr(social, "MAX_GROUP_MEMBERS", 2)
        group = social.create_group(db, ann, "Quants")["public_id"]
        with pytest.raises(social.SocialError, match="up to 1"):
            social.create_group(db, ann, "Second")
        social.join(db, ben, group, via_room=True)
        with pytest.raises(social.SocialError, match="full"):
            social.join(db, cat, group, via_room=True)

    def test_disbanding_removes_members_invites_and_their_notifications(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.invite(db, ann, group, ben)
        social.disband(db, ann, group)
        assert social.notifications(db, ben)["items"] == []
        assert social.overview(db, ben)["group_invites"] == []
        with pytest.raises(social.SocialError):
            social.group_detail(db, ann, group)

    def test_a_room_invite_reaches_every_other_member(self, db):
        ann, ben, cat = uid(db, "Ann"), uid(db, "Ben"), uid(db, "Cat")
        ref = social.create_group(db, ann, "Quants")
        social.join(db, ben, ref["public_id"], via_room=True)
        group_id = social.group_ref(db, ref["public_id"])["id"]
        assert social.invite_to_room(db, group_id, "VWAP", ben) == 1
        item = social.notifications(db, ann)["items"][0]
        assert (item["kind"], item["room_code"], item["actor"]["name"]) == ("room_invite", "VWAP", "Ben")
        assert social.notifications(db, cat)["items"] == []


class TestReports:
    def test_a_reported_bio_hides_from_everyone_but_its_owner(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        db.set_bio(ann, "Buy low, sell high.")
        pid = db._fetch_user(ann)["public_id"]
        social.report(db, ben, "bio", pid)
        social.report(db, ben, "bio", pid)  # a second report from the same person adds nothing
        assert social.public_profile(db, ben, pid)["bio"] == ""
        mine = social.public_profile(db, ann, pid)
        assert mine["bio"] == "Buy low, sell high." and mine["bio_hidden"] is True
        [queued] = social.open_reports(db)
        assert queued["text"] == "Buy low, sell high." and len(queued["reporters"]) == 1
        social.resolve(db, queued["id"], "restore")
        assert social.public_profile(db, ben, pid)["bio"] == "Buy low, sell high."
        assert social.open_reports(db) == []

    def test_clearing_a_bio_or_group_name(self, db):
        ann, ben, cat = uid(db, "Ann"), uid(db, "Ben"), uid(db, "Cat")
        db.set_bio(ann, "Something rude")
        social.report(db, ben, "bio", db._fetch_user(ann)["public_id"])
        social.report(db, cat, "bio", db._fetch_user(ann)["public_id"])
        [queued] = social.open_reports(db)
        assert len(queued["reporters"]) == 2
        social.resolve(db, queued["id"], "clear")
        assert db._fetch_user(ann)["bio"] == "" and social.open_reports(db) == []
        group = social.create_group(db, ann, "Edgy Name")["public_id"]
        social.report(db, ben, "group_name", group)
        assert social.group_detail(db, ben, group)["name"] == social.HIDDEN_GROUP_NAME
        assert social.group_detail(db, ann, group)["name"] == "Edgy Name"
        [queued] = social.open_reports(db)
        social.resolve(db, queued["id"], "clear")
        assert social.group_detail(db, ben, group)["name"].startswith("Group ")

    def test_renaming_a_hidden_group_shows_the_new_name(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Edgy Name")["public_id"]
        social.report(db, ben, "group_name", group)
        social.rename(db, ann, group, "Calm Name")
        assert social.group_detail(db, ben, group)["name"] == "Calm Name"
        assert social.open_reports(db) == []

    def test_what_cant_be_reported(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        pid = db._fetch_user(ann)["public_id"]
        with pytest.raises(social.SocialError, match="nothing"):
            social.report(db, ben, "bio", pid)
        db.set_bio(ann, "Hi")
        with pytest.raises(social.SocialError, match="own"):
            social.report(db, ann, "bio", pid)
        with pytest.raises(social.SocialError):
            social.report(db, ben, "name", pid)


# The API, through the app.


def fake_verify(credential):
    name = credential.removeprefix("as:")
    return {"sub": f"g-{name}", "email": f"{name.lower()}@example.com", "name": name, "picture": ""}


@pytest.fixture
def app_db(tmp_path, monkeypatch):
    db = Database(tmp_path / "api.db")
    monkeypatch.setattr(app_module.app.state, "db", db)
    monkeypatch.setattr(app_module.app.state, "verify_google", fake_verify)
    monkeypatch.setattr(app_module.hub, "questions", QUESTIONS)
    monkeypatch.setattr(app_module.hub, "publish_interval", 0)
    app_module.hub.rooms.clear()
    return db


def client_for(name, coins=FUNDS):
    client = TestClient(app_module.app)
    client.post("/api/auth/google", json={"credential": f"as:{name}"})
    app_module.app.state.db.conn.execute("UPDATE users SET coins = ? WHERE email = ?", (coins, f"{name.lower()}@example.com"))
    return client


class TestApi:
    def test_everything_needs_a_sign_in(self, app_db):
        anon = TestClient(app_module.app)
        for method, path in [("get", "/api/social"), ("get", "/api/notifications"), ("post", "/api/groups"), ("get", "/api/u/x")]:
            assert getattr(anon, method)(path).status_code in (401, 422)

    def test_friend_by_code_and_by_link_then_the_profile(self, app_db):
        ann, ben = client_for("Ann"), client_for("Ben")
        code = ann.get("/api/social").json()["me"]["friend_code"]
        assert ben.post("/api/friends", json={"friend_code": code}).json() == {"relation": "requested"}
        ben_id = ben.get("/api/me").json()["user"]["public_id"]
        assert ann.get("/api/notifications").json()["unread"] == 1
        assert ann.post(f"/api/friends/{ben_id}/accept").json() == {"relation": "friend"}
        profile = ann.get(f"/api/u/{ben_id}").json()
        assert profile["relation"] == "friend" and "email" not in profile and "id" not in profile
        assert ann.post("/api/notifications/read").json() == {"unread": 0}
        assert ben.post("/api/friends", json={"friend_code": "NOPE-NOPE"}).status_code == 404
        assert ann.get("/api/u/not-a-player").status_code == 404

    def test_handles_and_search(self, app_db):
        ann, ben = client_for("Ann"), client_for("Ben")
        assert ben.put("/api/profile/handle", json={"handle": "@BenTrades"}).json() == {"handle": "bentrades"}
        assert ann.put("/api/profile/handle", json={"handle": "bentrades"}).status_code == 400
        assert ann.put("/api/profile/handle", json={"handle": "shitlord"}).status_code == 400
        results = ann.get("/api/social/search", params={"q": "bent"}).json()["results"]
        assert [r["handle"] for r in results] == ["bentrades"] and results[0]["relation"] == "none"

    def test_groups_end_to_end(self, app_db):
        ann, ben = client_for("Ann"), client_for("Ben")
        group = ann.post("/api/groups", json={"name": "FinTech Club"}).json()
        ben_id = ben.get("/api/me").json()["user"]["public_id"]
        assert ann.post(f"/api/groups/{group['public_id']}/invites", json={"public_id": ben_id}).json() == {"result": "invited"}
        assert ben.post(f"/api/groups/{group['public_id']}/join").json()["role"] == "member"
        assert [g["name"] for g in ben.get("/api/groups/mine").json()["groups"]] == ["FinTech Club"]
        assert ben.patch(f"/api/groups/{group['public_id']}", json={"name": "Hijacked"}).status_code == 403
        assert ben.post(f"/api/groups/{group['public_id']}/leave").json() == {"ok": True}
        assert ann.delete(f"/api/groups/{group['public_id']}").json() == {"ok": True}

    def test_reports_and_the_review_page(self, app_db, monkeypatch):
        ann, ben = client_for("Ann"), client_for("Ben")
        ann.put("/api/profile/bio", json={"bio": "Hello there"})
        ann_id = ann.get("/api/me").json()["user"]["public_id"]
        assert ben.post("/api/reports", json={"kind": "bio", "public_id": ann_id}).json() == {"ok": True}
        assert ben.get(f"/api/u/{ann_id}").json()["bio"] == ""
        assert ben.get("/api/admin/reports").status_code == 403
        assert ben.get("/api/me").json()["user"]["admin"] is False
        monkeypatch.setenv("ADMIN_EMAILS", "ryan@x.com, Ben@Example.com")
        assert ben.get("/api/me").json()["user"]["admin"] is True
        [queued] = ben.get("/api/admin/reports").json()["reports"]
        assert ben.post(f"/api/admin/reports/{queued['id']}", json={"action": "restore"}).json() == {"ok": True}
        assert ben.get(f"/api/u/{ann_id}").json()["bio"] == "Hello there"

    def test_the_game_log_says_who_you_can_add_without_leaking_account_ids(self, app_db):
        ann = client_for("Ann")
        ben = client_for("Ben")
        ann_user = ann.get("/api/me").json()["user"]
        ben_user = ben.get("/api/me").json()["user"]
        db = app_db
        ann_id = social.user_id_for(db, ann_user["public_id"])
        ben_id = social.user_id_for(db, ben_user["public_id"])
        seats = [SeatRecord("p1", "Ann", ann_id, False, 1, Decimal(5)), SeatRecord("p2", "Ben", ben_id, False, 2, Decimal(-5))]
        db.record_game("ABCD", 3, 2, [GameResult(ann_id, "Ann", Decimal(5), Decimal(5), 1, 0, 0)], seats=seats)
        game_id = ann.get("/api/games").json()["games"][0]["game_id"]
        players = {p["name"]: p for p in ann.get(f"/api/games/{game_id}").json()["players"]}
        assert players["Ben"]["relation"] == "none" and players["Ben"]["public_id"] == ben_user["public_id"]
        assert players["Ann"]["relation"] == "you" and all("user_id" not in p for p in players.values())


# Rooms: members-only rooms and a hosting owner's table invites.


class TestGroupRooms:
    def test_only_members_can_join_a_group_room(self, db):
        ann, _ = account(db, "Ann")
        ben, _ = account(db, "Ben")
        room = Room("ABCD", RoomConfig(), QUESTIONS, Clock())
        room.group = {"id": 1, "public_id": "g1", "name": "Quants"}
        room.member_ids = {ann["id"]}
        with pytest.raises(RoomError, match="Sign in"):
            room.join("Guest")
        with pytest.raises(RoomError, match="only for members"):
            room.join("", user=ben)
        assert room.join("", user=ann).public_id == ann["public_id"]
        assert room.snapshot().group.name == "Quants"

    def test_table_invites_reach_non_members_once(self, db):
        ann, _ = account(db, "Ann")
        room = Room("ABCD", RoomConfig(), QUESTIONS, Clock())
        a = room.join("", user=ann)
        guest = room.join("Guest")
        room.set_bots(1, 1)
        group = {"id": 1, "public_id": "g1", "name": "Quants"}
        assert room.invite_table(group, "Ryan") == [a, guest]  # bots never
        assert room.invite_table(group, "Ryan") == []  # once each, while the card is up
        cards = room._you(guest).group_invites
        assert [(c.name, c.host, c.sign_in_first) for c in cards] == [("Quants", "Ryan", True)]
        room.answer_invite(a, "g1", accepted=True)
        assert room._you(a).group_invites == []
        assert room.snapshot().invites[0].model_dump() == {"group": "g1", "name": "Quants", "invited": 2, "joined": 1}
        with pytest.raises(RoomError):
            room.answer_invite(a, "g1", accepted=True)


def socket_for(client, token):
    return client.websocket_connect("/ws", headers={"cookie": f"almanac_session={token}"})


class TestOverSockets:
    def test_play_now_opens_a_members_only_room_and_rings_the_members(self, app_db):
        db = app_db
        ann, ann_token = account(db, "Ann")
        ben, ben_token = account(db, "Ben")
        cat, cat_token = account(db, "Cat")
        group = social.create_group(db, ann["id"], "Quants")["public_id"]
        social.join(db, ben["id"], group, via_room=True)
        client = TestClient(app_module.app)
        with socket_for(client, ann_token) as host:
            host.send_json({"type": "host_create", "config": {}, "group": group})
            code = receive_until(host, lambda m: m["type"] == "hosted")["room_code"]
            item = social.notifications(db, ben["id"])["items"][0]
            assert (item["kind"], item["room_code"]) == ("room_invite", code)
            with socket_for(client, cat_token) as outsider:
                outsider.send_json({"type": "join", "room_code": code, "name": "Cat"})
                assert receive_until(outsider, lambda m: m["type"] == "error")["code"] == "group_only"
            with socket_for(client, ben_token) as member:
                member.send_json({"type": "join", "room_code": code, "name": "Ben"})
                assert receive_until(member, lambda m: m["type"] == "joined")
        with client.websocket_connect("/ws") as anonymous:  # not signed in: no group rooms
            anonymous.send_json({"type": "host_create", "config": {}, "group": group})
            assert receive_until(anonymous, lambda m: m["type"] == "error")["code"] == "sign_in"
        with socket_for(client, cat_token) as stranger:
            stranger.send_json({"type": "host_create", "config": {}, "group": group})
            assert receive_until(stranger, lambda m: m["type"] == "error")["code"] == "not_member"

    def test_a_hosting_owner_invites_the_table(self, app_db):
        db = app_db
        ann, ann_token = account(db, "Ann")  # the club's owner, on the host screen
        ben, ben_token = account(db, "Ben")
        group = social.create_group(db, ann["id"], "FinTech Club")["public_id"]
        client = TestClient(app_module.app)
        with socket_for(client, ann_token) as host:
            host.send_json({"type": "host_create", "config": {}})
            code = receive_until(host, lambda m: m["type"] == "hosted")["room_code"]
            with socket_for(client, ben_token) as member, client.websocket_connect("/ws") as guest:
                member.send_json({"type": "join", "room_code": code, "name": "Ben"})
                receive_until(member, lambda m: m["type"] == "joined")
                guest.send_json({"type": "join", "room_code": code, "name": "Gus"})
                receive_until(guest, lambda m: m["type"] == "joined")
                host.send_json({"type": "host_group_invite", "group": group})
                notice = receive_until(host, lambda m: m["type"] == "notice")
                assert notice["message"] == "Invited 2 players to FinTech Club. 1 guest can accept after signing in."
                card = receive_until(member, lambda m: m["type"] == "state" and m["you"]["group_invites"])
                assert card["you"]["group_invites"][0]["host"] == "Ann"
                assert social.notifications(db, ben["id"])["items"][0]["kind"] == "group_invite"
                gus = receive_until(guest, lambda m: m["type"] == "state" and m["you"]["group_invites"])
                assert gus["you"]["group_invites"][0]["sign_in_first"] is True
                guest.send_json({"type": "answer_group_invite", "group": group, "accept": True})
                assert receive_until(guest, lambda m: m["type"] == "error")["code"] == "sign_in"
                member.send_json({"type": "answer_group_invite", "group": group, "accept": True})
                done = receive_until(member, lambda m: m["type"] == "state" and not m["you"]["group_invites"])
                assert done["invites"][0]["joined"] == 1
                assert social.role_in(db, group, ben["id"]) == "member"
                host.send_json({"type": "host_group_invite", "group": group})
                again = receive_until(host, lambda m: m["type"] == "notice")
                assert again["message"].startswith("Everyone here is already in FinTech Club")
        _, cat_token = account(db, "Cat")
        with socket_for(client, cat_token) as stranger:  # any member may offer a group; an outsider can't
            stranger.send_json({"type": "host_create", "config": {}})
            receive_until(stranger, lambda m: m["type"] == "hosted")
            stranger.send_json({"type": "host_group_invite", "group": group})
            assert receive_until(stranger, lambda m: m["type"] == "error")["code"] == "not_member"
