from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from server import app as app_module
from server.cosmetics import BUNDLES_BY_ID, DEFAULT_AVATAR, ITEMS, WELCOME_COINS, round_price
from server.db import Database, GameResult
from server.tests.test_auth import fake_verify
from server.tests.test_rooms import QUESTIONS, host_room, receive_until


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app.state, "db", Database(tmp_path / "test.db"))
    monkeypatch.setattr(app_module.app.state, "verify_google", fake_verify)
    monkeypatch.setattr(app_module.hub, "questions", QUESTIONS)
    monkeypatch.setattr(app_module.hub, "publish_interval", 0)
    app_module.hub.rooms.clear()
    with TestClient(app_module.app) as test_client:
        yield test_client


def signed_in(client, extra_coins=0):
    """Signs in and tops the balance up by `extra_coins` through a recorded game."""
    user = client.post("/api/auth/google", json={"credential": "good"}).json()["user"]
    if extra_coins:
        app_module.app.state.db.record_game(
            "ATOM", 1, 2,
            [GameResult(user["id"], "Ryan", Decimal(0), Decimal(extra_coins - 20), 2, 0, 0)],
        )
    return user


def coins(client):
    return client.get("/api/me").json()["user"]["coins"]


def test_the_catalog_is_public(client):
    body = client.get("/api/catalog").json()
    assert len(body["items"]) == len(ITEMS)
    assert body["rarity_colors"]["mythical"] == "#8b5cf6"
    assert [bundle["id"] for bundle in body["bundles"]] == list(BUNDLES_BY_ID)


def test_the_trophy_road_unlocks_banners_that_coins_cannot_buy(client):
    user = signed_in(client)
    assert client.post("/api/shop/buy", json={"item_id": "banner_knowitall"}).status_code == 400
    assert client.put("/api/avatar", json={"avatar": {"banner": "banner_knowitall"}}).status_code == 400
    road = client.get("/api/road").json()
    assert not any(m["unlocked"] for m in road["levels"] + road["prestige"])
    assert [r["id"] for r in road["reserved"]] == ["banner_podium", "banner_primetime"]
    # Seven levels and 500 prestige later (set directly: this is the standing, not the games).
    app_module.app.state.db.conn.execute(
        "UPDATE users SET xp = 3600, prestige = 500 WHERE id = ?", (user["id"],)
    )
    locker = client.get("/api/locker").json()
    assert locker["user"]["level"] == 7
    assert set(locker["unlocked"]) == {"banner_luck", "banner_suspect", "banner_knowitall", "banner_close", "banner_spoton"}
    assert client.put("/api/avatar", json={"avatar": {"banner": "banner_spoton"}}).status_code == 200
    assert client.get("/api/me").json()["user"]["avatar"]["banner"] == "banner_spoton"
    road = client.get("/api/road").json()
    assert [m["unlocked"] for m in road["levels"]] == [True, True, True, False, False]
    assert client.put("/api/avatar", json={"avatar": {"banner": "banner_reckoning"}}).status_code == 400


def test_a_bought_banner_is_worn_like_any_other_item(client):
    signed_in(client, extra_coins=200)
    assert client.post("/api/shop/buy", json={"item_id": "banner_envelope"}).status_code == 200
    assert client.put("/api/avatar", json={"avatar": {"banner": "banner_envelope"}}).status_code == 200


def test_the_locker_needs_a_sign_in(client):
    assert client.get("/api/locker").status_code == 401


def test_a_new_account_starts_with_welcome_coins_and_the_default_look(client):
    signed_in(client)
    body = client.get("/api/locker").json()
    assert body["owned"] == []
    assert body["user"]["coins"] == WELCOME_COINS
    assert body["user"]["avatar"] == DEFAULT_AVATAR


def test_buying_spends_coins_and_adds_to_the_locker(client):
    signed_in(client)
    response = client.post("/api/shop/buy", json={"item_id": "eye_sunglasses"})
    assert response.status_code == 200
    assert response.json()["user"]["coins"] == WELCOME_COINS - ITEMS["eye_sunglasses"].price
    assert response.json()["owned"] == ["eye_sunglasses"]


def test_you_cannot_afford_what_you_cannot_afford(client):
    signed_in(client)
    response = client.post("/api/shop/buy", json={"item_id": "effect_void"})  # 1750, above the welcome coins
    assert response.status_code == 400
    assert "more coins" in response.json()["detail"]
    assert coins(client) == WELCOME_COINS


def test_items_are_bought_once(client):
    signed_in(client)
    client.post("/api/shop/buy", json={"item_id": "ears_studs"})
    response = client.post("/api/shop/buy", json={"item_id": "ears_studs"})
    assert response.status_code == 400
    assert coins(client) == WELCOME_COINS - 20


def test_free_and_unknown_items_cannot_be_bought(client):
    signed_in(client)
    assert client.post("/api/shop/buy", json={"item_id": "skin_1"}).status_code == 400
    assert client.post("/api/shop/buy", json={"item_id": "hat_of_doom"}).status_code == 404


def test_a_bundle_grants_every_item_at_the_discount(client):
    signed_in(client, extra_coins=400)
    bundle = BUNDLES_BY_ID["bundle_builder"]
    response = client.post("/api/shop/buy-bundle", json={"bundle_id": bundle.id})
    assert response.status_code == 200
    assert set(response.json()["owned"]) == set(bundle.items)
    assert response.json()["user"]["coins"] == WELCOME_COINS + 400 - bundle.price_for(set())


def test_a_bundle_charges_only_for_what_you_lack(client):
    signed_in(client, extra_coins=400)
    client.post("/api/shop/buy", json={"item_id": "head_hardhat"})
    before = coins(client)
    response = client.post("/api/shop/buy-bundle", json={"bundle_id": "bundle_builder"})
    assert response.status_code == 200
    assert before - response.json()["user"]["coins"] == round_price(0.8 * ITEMS["top_hivis"].price)
    again = client.post("/api/shop/buy-bundle", json={"bundle_id": "bundle_builder"})
    assert again.status_code == 400
    assert "already own" in again.json()["detail"]


def test_a_bundle_you_cannot_afford_changes_nothing(client):
    signed_in(client)
    response = client.post("/api/shop/buy-bundle", json={"bundle_id": "bundle_business"})
    assert response.status_code == 400
    assert client.get("/api/locker").json()["owned"] == []
    assert coins(client) == WELCOME_COINS
    assert client.post("/api/shop/buy-bundle", json={"bundle_id": "bundle_nope"}).status_code == 404


def test_equipping_needs_ownership_but_free_parts_are_always_allowed(client):
    signed_in(client)
    denied = client.put("/api/avatar", json={"avatar": {**DEFAULT_AVATAR, "head": "head_cap"}})
    assert denied.status_code == 400
    client.post("/api/shop/buy", json={"item_id": "head_cap"})
    allowed = client.put(
        "/api/avatar", json={"avatar": {**DEFAULT_AVATAR, "head": "head_cap", "skin": "skin_6"}}
    )
    assert allowed.status_code == 200
    avatar = client.get("/api/me").json()["user"]["avatar"]
    assert avatar["head"] == "head_cap" and avatar["skin"] == "skin_6"


def test_the_avatar_travels_into_the_game(client):
    signed_in(client)
    client.put("/api/avatar", json={"avatar": {**DEFAULT_AVATAR, "skin": "skin_5"}})
    token = client.cookies["almanac_session"]
    client.cookies.clear()
    with client.websocket_connect("/ws") as host, client.websocket_connect(
        "/ws", headers={"cookie": f"almanac_session={token}"}
    ) as phone, client.websocket_connect("/ws") as guest:
        code, _ = host_room(host)
        phone.send_json({"type": "join", "room_code": code, "name": "", "token": None})
        receive_until(phone, lambda m: m["type"] == "joined")
        guest.send_json({"type": "join", "room_code": code, "name": "Guest", "token": None})
        receive_until(guest, lambda m: m["type"] == "joined")
        state = receive_until(host, lambda m: m["type"] == "state" and len(m["players"]) == 2)
        assert state["players"][0]["avatar"]["skin"] == "skin_5"
        assert state["players"][1]["avatar"] is None


@pytest.mark.skipif(not (app_module.CLIENT_DIST / "index.html").is_file(), reason="client not built")
def test_the_page_is_rechecked_every_load_and_hashed_assets_are_kept():
    # A stale page after a deploy ran the old client against the new catalog (Nov 4, 2026).
    with TestClient(app_module.app) as client:
        page = client.get("/locker")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
        asset = next((app_module.CLIENT_DIST / "assets").glob("*.js"))
        kept = client.get(f"/assets/{asset.name}")
        assert kept.status_code == 200 and "immutable" in kept.headers["cache-control"]

def test_a_purchase_can_earn_an_achievement_and_says_so(client):
    signed_in(client, extra_coins=2000)
    before = coins(client)
    body = client.post("/api/shop/buy", json={"item_id": "effect_void"}).json()  # 1750 coins
    got = {(a["id"], a["tier"]) for a in body["achievements"]}
    assert got == {("big_spender", "bronze"), ("big_spender", "silver")}
    assert body["user"]["coins"] == before - 1750 + 50 + 100
    again = client.post("/api/shop/buy", json={"item_id": "ears_studs"}).json()
    assert again["achievements"] == []


def test_the_achievements_page_and_the_profile_badges(client):
    signed_in(client, extra_coins=100)  # one game, second place
    page = client.get("/api/achievements").json()
    assert page["earned"] == 0 and page["total"] > 30
    assert any(row["id"] == "champion" and row["progress"] == 0 for row in page["achievements"])
    app_module.app.state.db.award_achievements(page["user"]["id"], [("champion", "bronze", 50, None)])
    profile = client.get("/api/profile").json()
    assert [(b["id"], b["tier"]) for b in profile["badges"]] == [("champion", "bronze")]
    assert profile["badges"][0]["requirement"] == "Win a game"
    assert client.get("/api/achievements").json()["earned"] == 1


def test_the_game_history_needs_a_sign_in_and_pages(client):
    assert client.get("/api/games").status_code == 401
    signed_in(client, extra_coins=100)  # one game, in room ATOM
    body = client.get("/api/games").json()
    assert body["total"] == 1 and body["next"] is None
    assert [game["room_code"] for game in body["games"]] == ["ATOM"]
    assert client.get(f"/api/games?before={body['games'][0]['game_id']}").json()["games"] == []
    assert client.get("/api/games?before=0").status_code == 422


def test_the_bio_is_saved_and_checked(client):
    signed_in(client)
    saved = client.put("/api/profile/bio", json={"bio": "  Prices first,  questions later. "})
    assert saved.status_code == 200 and saved.json()["user"]["bio"] == "Prices first, questions later."
    assert client.get("/api/profile").json()["user"]["bio"] == "Prices first, questions later."
    refused = client.put("/api/profile/bio", json={"bio": "f u c k"})
    assert refused.status_code == 200  # spaced-out letters aren't a word; the list is a first line only
    assert client.put("/api/profile/bio", json={"bio": "fuck this"}).status_code == 400
    assert client.put("/api/profile/bio", json={"bio": "x" * 161}).status_code == 400