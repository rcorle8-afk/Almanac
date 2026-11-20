"""The host-group invite (Ryan, Nov 17, 2026): a signed-in host screen offers one of its account's
groups to the table, before the game and again after it. The host screen is an entity of its
own, never a seat, so the same account can host on one screen and play from another."""

import pytest
from fastapi.testclient import TestClient

from server import app as app_module
from server import social
from server.db import Database
from server.protocol import RoomConfig
from server.rooms import Phase, Room
from server.tests.test_rooms import QUESTIONS, Clock, advance_to, make_room, receive_until
from server.tests.test_social import account, app_db, socket_for, uid  # noqa: F401  (fixtures)

GROUP = {
    "public_id": "g1",
    "name": "Quants",
    "icon": {"glyph": "owl", "color": "navy", "image": None},
    "member_count": 4,
    "prestige": 900,
}


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "invite.db")


def cards(room, player):
    return room._you(player).group_invites


def tally(room):
    return room.snapshot().invites[0].model_dump()


class TestTheCard:
    def test_it_shows_the_group_and_skips_members_and_bots(self, db):
        ann, _ = account(db, "Ann")
        ben, _ = account(db, "Ben")
        room = Room("ABCD", RoomConfig(), QUESTIONS, Clock())
        a, b, gus = room.join("", user=ann), room.join("", user=ben), room.join("Gus")
        room.set_bots(1, 1)
        assert room.invite_table(GROUP, "Ann", skip={ann["id"]}) == [b, gus]
        [card] = cards(room, b)
        assert (card.group, card.name, card.host, card.sign_in_first) == ("g1", "Quants", "Ann", False)
        assert (card.icon["glyph"], card.member_count, card.prestige) == ("owl", 4, 900)
        assert cards(room, gus)[0].sign_in_first is True  # a guest signs in, then joins
        assert cards(room, a) == []
        assert tally(room) == {"group": "g1", "name": "Quants", "invited": 2, "joined": 0}

    def test_not_now_holds_until_the_game_is_over_and_then_the_host_may_ask_again(self):
        room, (a, b, c) = make_room(3)
        room.invite_table(GROUP, "Ann")
        room.answer_invite(a, "g1", accepted=False)
        room.answer_invite(b, "g1", accepted=True)
        assert cards(room, c)[0].member_count == 5  # the card still up shows the group as it now is
        # Pressing again in the same lobby nags nobody: a said Not now, b joined, c's card is up.
        assert room.invite_table(GROUP, "Ann") == []
        advance_to(room, Phase.GAME_OVER)
        assert cards(room, a) == []  # nothing comes back on its own
        assert room.invite_table(GROUP, "Ann") == [a]  # the host's second offer, after the game
        assert tally(room) == {"group": "g1", "name": "Quants", "invited": 3, "joined": 1}
        room.answer_invite(a, "g1", accepted=False)
        assert room.invite_table(GROUP, "Ann") == []
        room.restart()
        assert room.invite_table(GROUP, "Ann") == [a]  # and once more in the next lobby

    def test_the_card_comes_down_for_someone_who_joined_another_way(self, db):
        ben, _ = account(db, "Ben")
        room = Room("ABCD", RoomConfig(), QUESTIONS, Clock())
        b = room.join("", user=ben)
        room.invite_table(GROUP, "Ann")
        assert cards(room, b)
        room.invite_table(GROUP, "Ann", skip={ben["id"]})  # by now a member: the bell, or the link
        assert cards(room, b) == []

    def test_each_group_has_its_own_card(self):
        room, (a,) = make_room(1)
        room.invite_table(GROUP, "Ann")
        room.invite_table({"public_id": "g2", "name": "FinTech Club"}, "Ann")
        assert [card.name for card in cards(room, a)] == ["Quants", "FinTech Club"]
        room.answer_invite(a, "g1", accepted=False)
        assert [card.name for card in cards(room, a)] == ["FinTech Club"]


class TestTheOffer:
    def test_any_member_may_offer_their_group(self, db):
        ann, ben, cat, dan = (uid(db, name) for name in ("Ann", "Ben", "Cat", "Dan"))
        group = social.create_group(db, ann, "Quants", glyph="owl", color="navy")["public_id"]
        social.join(db, ben, group, via_room=True)
        card, outcomes = social.offer_at_table(db, ben, group, [ann, ben, cat, dan])
        assert outcomes == {ann: "already_member", ben: "already_member", cat: "invited", dan: "invited"}
        assert (card["name"], card["member_count"], card["icon"]["glyph"]) == ("Quants", 2, "owl")
        [item] = social.notifications(db, cat)["items"]
        assert (item["kind"], item["actor"]["name"], item["open"]) == ("group_invite", "Ben", True)
        # Asked again, nobody's bell rings twice.
        assert social.offer_at_table(db, ben, group, [cat, dan])[1] == {cat: "already_invited", dan: "already_invited"}
        assert len(social.notifications(db, cat)["items"]) == 1
        assert social.join(db, cat, group)["role"] == "member"

    def test_an_outsider_cannot_offer_someone_elses_group(self, db):
        ann, eve, cat = uid(db, "Ann"), uid(db, "Eve"), uid(db, "Cat")
        group = social.create_group(db, ann, "Quants")["public_id"]
        with pytest.raises(social.SocialError, match="members"):
            social.offer_at_table(db, eve, group, [cat])
        assert social.notifications(db, cat)["items"] == []

    def test_a_block_keeps_the_offer_away(self, db):
        ann, ben, cat, dan = (uid(db, name) for name in ("Ann", "Ben", "Cat", "Dan"))
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.join(db, ben, group, via_room=True)
        social.block(db, cat, ben)  # Cat blocked the host
        social.block(db, ann, dan)  # the owner blocked Dan
        assert social.offer_at_table(db, ben, group, [cat, dan])[1] == {cat: "blocked", dan: "blocked"}
        assert social.notifications(db, cat)["items"] == [] and social.notifications(db, dan)["items"] == []
        with pytest.raises(social.SocialError):  # nor does a card at the table let Dan in
            social.join(db, dan, group, via_room=True)


def until(socket, predicate):
    """The first message that passes, and everything read on the way to it."""
    seen = []
    while True:
        message = socket.receive_json()
        seen.append(message)
        if predicate(message):
            return message, seen


def is_state(message):
    return message["type"] == "state"


def is_notice(message):
    return message["type"] == "notice"


def has_card(message):
    return is_state(message) and bool(message["you"]["group_invites"])


def no_card(message):
    return is_state(message) and not message["you"]["group_invites"]


def host_room(socket, config=None):
    socket.send_json({"type": "host_create", "config": config or {}})
    return receive_until(socket, lambda m: m["type"] == "hosted")


def sit(socket, code, name=""):
    socket.send_json({"type": "join", "room_code": code, "name": name})
    return receive_until(socket, lambda m: m["type"] == "joined")


class TestOverSockets:
    def test_one_account_hosts_and_plays_at_once(self, app_db):
        db = app_db
        ann, ann_token = account(db, "Ann")
        ben, ben_token = account(db, "Ben")
        group = social.create_group(db, ann["id"], "FinTech Club")["public_id"]
        client = TestClient(app_module.app)
        with socket_for(client, ann_token) as host:
            code = host_room(host, {"rounds": 3})["room_code"]
            first = receive_until(host, is_state)
            assert first["host"]["name"] == "Ann" and first["host"]["public_id"] == ann["public_id"]
            assert first["players"] == []  # hosting is not a seat
            with socket_for(client, ann_token) as seat, socket_for(client, ben_token) as other:
                mine = sit(seat, code)["player_id"]
                sit(other, code, "Ben")

                # The host screen is still the host: the account sitting down didn't replace it.
                host.send_json({"type": "host_group_invite", "group": group})
                notice, seen = until(host, is_notice)
                assert not [m for m in seen if m["type"] == "error"]
                assert notice["message"] == "Invited 1 player to FinTech Club."  # never its own seat

                card = receive_until(other, has_card)["you"]["group_invites"][0]
                assert (card["host"], card["name"], card["member_count"]) == ("Ann", "FinTech Club", 1)
                assert card["icon"]["glyph"] == "letters" and card["sign_in_first"] is False
                assert social.notifications(db, ben["id"])["items"][0]["kind"] == "group_invite"
                seated = receive_until(seat, lambda m: is_state(m) and m["invites"])
                assert seated["you"]["group_invites"] == [] and seated["host"]["name"] == "Ann"
                assert [p["signed_in"] for p in seated["players"] if p["id"] == mine] == [True]

                # Not now, before the game. Pressing again in this lobby leaves Ben alone.
                other.send_json({"type": "answer_group_invite", "group": group, "accept": False})
                receive_until(other, no_card)
                host.send_json({"type": "host_group_invite", "group": group})
                assert receive_until(host, is_notice)["message"].startswith("Everyone here is already in FinTech Club")

                # The account plays from its seat while the same account runs the game.
                host.send_json({"type": "host_start"})
                host.send_json({"type": "host_advance"})
                receive_until(seat, lambda m: is_state(m) and m["phase"] == "QUOTING")
                seat.send_json({"type": "submit_quote", "bid": "90", "ask": "110"})
                quoting = receive_until(host, lambda m: is_state(m) and any(p["quoted"] for p in m["players"]))
                assert [p["name"] for p in quoting["players"] if p["quoted"]] == ["Ann"]

                # After the game the host may offer again, and this time Ben joins.
                host.send_json({"type": "host_end"})
                receive_until(host, lambda m: is_state(m) and m["phase"] == "GAME_OVER")
                host.send_json({"type": "host_group_invite", "group": group})
                assert receive_until(host, is_notice)["message"] == "Invited 1 player to FinTech Club."
                again = receive_until(other, has_card)
                assert again["phase"] == "GAME_OVER"
                other.send_json({"type": "answer_group_invite", "group": group, "accept": True})
                done = receive_until(other, no_card)
                assert done["invites"][0] == {"group": group, "name": "FinTech Club", "invited": 1, "joined": 1}
                assert social.role_in(db, group, ben["id"]) == "member"

    def test_a_member_who_is_not_the_owner_offers_the_group(self, app_db):
        db = app_db
        ann, _ = account(db, "Ann")
        ben, ben_token = account(db, "Ben")
        cat, cat_token = account(db, "Cat")
        group = social.create_group(db, ann["id"], "Quants")["public_id"]
        social.join(db, ben["id"], group, via_room=True)
        client = TestClient(app_module.app)
        with socket_for(client, ben_token) as host:
            code = host_room(host)["room_code"]
            with socket_for(client, cat_token) as player, client.websocket_connect("/ws") as guest:
                sit(player, code, "Cat")
                sit(guest, code, "Gus")
                host.send_json({"type": "host_group_invite", "group": group})
                notice = receive_until(host, is_notice)["message"]
                assert notice == "Invited 2 players to Quants. 1 guest can accept after signing in."
                assert receive_until(player, has_card)["you"]["group_invites"][0]["host"] == "Ben"
                assert social.notifications(db, cat["id"])["items"][0]["actor"]["name"] == "Ben"
                player.send_json({"type": "answer_group_invite", "group": group, "accept": True})
                receive_until(player, no_card)
                assert social.role_in(db, group, cat["id"]) == "member"
                assert receive_until(guest, has_card)["you"]["group_invites"][0]["sign_in_first"] is True

    def test_a_host_screen_that_is_not_signed_in_hosts_as_nobody(self, app_db):
        db = app_db
        ann, ann_token = account(db, "Ann")
        group = social.create_group(db, ann["id"], "Quants")["public_id"]
        client = TestClient(app_module.app)
        with client.websocket_connect("/ws") as host:
            hosted = host_room(host)
            assert receive_until(host, is_state)["host"] is None
            host.send_json({"type": "host_group_invite", "group": group})
            assert receive_until(host, lambda m: m["type"] == "error")["code"] == "sign_in"
        # Signing in on that screen reconnects its socket, and the room then has its host.
        with socket_for(client, ann_token) as host:
            host.send_json({"type": "host_resume", "room_code": hosted["room_code"], "token": hosted["token"]})
            assert receive_until(host, is_state)["host"]["name"] == "Ann"
