import pytest
from fastapi.testclient import TestClient

from server import app as app_module
from server import auth
from server.auth import SESSION_COOKIE
from server.cosmetics import WELCOME_COINS
from server.db import Database
from server.tests.test_rooms import QUESTIONS, host_room, receive_until


def fake_verify(credential):
    if credential == "good":
        return {"sub": "g1", "email": "ryan@example.com", "name": "Ryan Corle", "picture": ""}
    raise ValueError("bad token")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app.state, "db", Database(tmp_path / "test.db"))
    monkeypatch.setattr(app_module.app.state, "verify_google", fake_verify)
    monkeypatch.setattr(app_module.hub, "questions", QUESTIONS)
    monkeypatch.setattr(app_module.hub, "publish_interval", 0)
    app_module.hub.rooms.clear()
    with TestClient(app_module.app) as test_client:
        yield test_client


def test_config_tells_the_client_what_sign_in_exists(client):
    body = client.get("/api/config").json()
    assert set(body) == {"google_client_id", "dev_login"}


def test_signed_out_me_is_nobody(client):
    assert client.get("/api/me").json() == {"user": None}


def test_google_sign_in_starts_a_session(client):
    response = client.post("/api/auth/google", json={"credential": "good"})
    assert response.status_code == 200
    assert response.json()["user"]["name"] == "Ryan Corle"
    assert SESSION_COOKIE in response.cookies
    assert client.get("/api/me").json()["user"]["email"] == "ryan@example.com"


def test_a_bad_credential_is_refused(client):
    response = client.post("/api/auth/google", json={"credential": "forged"})
    assert response.status_code == 401
    assert client.get("/api/me").json() == {"user": None}


def test_logout_ends_the_session(client):
    client.post("/api/auth/google", json={"credential": "good"})
    client.post("/api/auth/logout")
    assert client.get("/api/me").json() == {"user": None}


def test_profile_needs_a_sign_in(client):
    assert client.get("/api/profile").status_code == 401
    client.post("/api/auth/google", json={"credential": "good"})
    profile = client.get("/api/profile").json()
    assert profile["games"] == 0
    assert profile["user"]["name"] == "Ryan Corle"


def test_dev_sign_in_is_off_unless_allowed(client, monkeypatch):
    assert client.post("/api/auth/dev", json={"name": "Tester"}).status_code == 404
    monkeypatch.setattr(auth, "ALLOW_DEV_LOGIN", True)
    assert client.post("/api/auth/dev", json={"name": "Tester"}).status_code == 200
    assert client.get("/api/me").json()["user"]["name"] == "Tester"


def sign_in(client):
    """Signs in, then empties the jar: it would otherwise sign in every socket, guests included."""
    client.post("/api/auth/google", json={"credential": "good"})
    token = client.cookies[SESSION_COOKIE]
    client.cookies.clear()
    return {"cookie": f"{SESSION_COOKIE}={token}"}


def test_a_signed_in_socket_joins_with_its_account(client):
    cookie = sign_in(client)
    with client.websocket_connect("/ws") as host, client.websocket_connect("/ws", headers=cookie) as phone:
        code, _ = host_room(host)
        phone.send_json({"type": "join", "room_code": code, "name": "", "token": None})
        joined = receive_until(phone, lambda m: m["type"] == "joined")
        state = receive_until(host, lambda m: m["type"] == "state" and m["players"])
        assert state["players"][0]["name"] == "Ryan Corle"
        assert state["players"][0]["signed_in"] is True
        # The account reclaims the seat without the seat token, as from a second device.
        with client.websocket_connect("/ws", headers=cookie) as laptop:
            laptop.send_json({"type": "join", "room_code": code, "name": "Someone", "token": None})
            again = receive_until(laptop, lambda m: m["type"] == "joined")
            assert again["player_id"] == joined["player_id"]


def test_guests_are_not_signed_in(client):
    with client.websocket_connect("/ws") as host, client.websocket_connect("/ws") as phone:
        code, _ = host_room(host)
        phone.send_json({"type": "join", "room_code": code, "name": "Guest", "token": None})
        receive_until(phone, lambda m: m["type"] == "joined")
        state = receive_until(host, lambda m: m["type"] == "state" and m["players"])
        assert state["players"][0]["signed_in"] is False


def test_a_guest_seat_takes_the_account_it_signs_in_with(client):
    with client.websocket_connect("/ws") as host:
        code, _ = host_room(host)
        with client.websocket_connect("/ws") as phone:
            phone.send_json({"type": "join", "room_code": code, "name": "Guest", "token": None})
            seat = receive_until(phone, lambda m: m["type"] == "joined")
        cookie = sign_in(client)  # signing in from the lobby, then the socket reconnects
        with client.websocket_connect("/ws", headers=cookie) as phone:
            phone.send_json({"type": "join", "room_code": code, "name": "Guest", "token": seat["token"]})
            again = receive_until(phone, lambda m: m["type"] == "joined")
            assert again["player_id"] == seat["player_id"]
            me = receive_until(phone, lambda m: m["type"] == "state")["players"][0]
        assert me["name"] == "Guest"  # the name in the room stays
        assert me["signed_in"] is True
        assert me["avatar"] is not None


def test_an_account_already_seated_does_not_take_a_second_seat(client):
    cookie = sign_in(client)
    with client.websocket_connect("/ws") as host:
        code, _ = host_room(host)
        with client.websocket_connect("/ws", headers=cookie) as laptop:
            laptop.send_json({"type": "join", "room_code": code, "name": "", "token": None})
            receive_until(laptop, lambda m: m["type"] == "joined")
            with client.websocket_connect("/ws") as phone:
                phone.send_json({"type": "join", "room_code": code, "name": "Guest", "token": None})
                seat = receive_until(phone, lambda m: m["type"] == "joined")
            with client.websocket_connect("/ws", headers=cookie) as phone:
                phone.send_json({"type": "join", "room_code": code, "name": "Guest", "token": seat["token"]})
                again = receive_until(phone, lambda m: m["type"] == "joined")
                assert again["player_id"] == seat["player_id"]
                players = receive_until(phone, lambda m: m["type"] == "state")["players"]
            guest = next(player for player in players if player["name"] == "Guest")
            assert guest["signed_in"] is False
            assert sum(player["signed_in"] for player in players) == 1


def test_a_reconnecting_seat_picks_up_the_account_s_new_look(client):
    cookie = sign_in(client)
    with client.websocket_connect("/ws") as host:
        code, _ = host_room(host)
        with client.websocket_connect("/ws", headers=cookie) as phone:
            phone.send_json({"type": "join", "room_code": code, "name": "", "token": None})
            seat = receive_until(phone, lambda m: m["type"] == "joined")
            before = receive_until(phone, lambda m: m["type"] == "state")["players"][0]["avatar"]
        client.cookies.set(SESSION_COOKIE, cookie["cookie"].split("=", 1)[1])
        assert client.put("/api/avatar", json={"avatar": {**before, "skin": "skin_1"}}).status_code == 200
        client.cookies.clear()
        with client.websocket_connect("/ws", headers=cookie) as phone:
            phone.send_json({"type": "join", "room_code": code, "name": "", "token": seat["token"]})
            receive_until(phone, lambda m: m["type"] == "joined")
            after = receive_until(phone, lambda m: m["type"] == "state")["players"][0]["avatar"]
        assert before["skin"] != "skin_1" and after["skin"] == "skin_1"


def test_a_finished_game_is_saved_for_the_signed_in_player(client):
    cookie = sign_in(client)
    fast = {"question": 0.01, "quoting": 0.01, "trading": 0.01, "reveal": 0.01, "scores": 0.01}
    with client.websocket_connect("/ws") as host, client.websocket_connect("/ws", headers=cookie) as me, client.websocket_connect("/ws") as guest:
        code, _ = host_room(host, {"rounds": 3, "timers": fast})
        me.send_json({"type": "join", "room_code": code, "name": "", "token": None})
        receive_until(me, lambda m: m["type"] == "joined")
        guest.send_json({"type": "join", "room_code": code, "name": "Guest", "token": None})
        receive_until(guest, lambda m: m["type"] == "joined")
        host.send_json({"type": "host_start"})
        final = receive_until(me, lambda m: m.get("phase") == "GAME_OVER")
        assert final["you"]["coins_awarded"] == 20 + 50  # nobody traded: a tie for first
        assert final["you"]["xp_awarded"] == 50 + 5 * 3  # finishing, three rounds, no trades
        assert final["you"]["prestige_awarded"] == 100 and final["you"]["level_up"] is None
        mine = next(p for p in final["players"] if p["signed_in"])
        assert (mine["level"], mine["prestige"]) == (1, 0)  # standing when the seat was taken
        assert next(p for p in final["players"] if not p["signed_in"])["level"] is None
    profile = client.get("/api/profile", headers=cookie).json()
    assert profile["games"] == 1
    assert profile["user"]["coins"] == WELCOME_COINS + 70 + 50  # the first win also earns Champion bronze
    assert (profile["user"]["xp"], profile["user"]["prestige"], profile["user"]["level"]) == (65, 100, 1)
    assert profile["recent"][0]["room_code"] == code
