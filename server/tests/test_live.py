import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from server import anticheat, live
from server import app as app_module
from server.db import Database
from server.rooms import EMPTY_ROOM_TTL_MS, Hub, Phase, Room, RoomError, save_game
from server.tests.test_rooms import QUESTIONS, Clock, advance_to
from server.tests.test_social import account, app_db, client_for  # noqa: F401  (fixture)


def utc(*parts):
    return datetime(*parts, tzinfo=timezone.utc)


def user(db, name):
    found, _ = account(db, name)
    return {"id": found["id"], "name": name}


def live_room(clock=None, starts_in=600_000):
    clock = clock or Clock()
    room = Room(live.LIVE_CODE, live.live_config(), QUESTIONS, clock)
    room.schedule_live(clock.now + starts_in)
    return room, clock


class TestSchedule:
    def test_before_nine_eastern_it_is_tonight(self):
        start = live.next_start(utc(2026, 11, 10, 20, 0))  # 3pm EST
        assert start.isoformat() == "2026-11-10T21:00:00-05:00"

    def test_after_nine_eastern_it_is_tomorrow(self):
        start = live.next_start(utc(2026, 11, 11, 2, 30))  # 9:30pm EST on the 10th
        assert start.isoformat() == "2026-11-11T21:00:00-05:00"

    def test_daylight_saving_moves_the_utc_hour(self):
        summer = live.next_start(utc(2026, 7, 1, 12))
        winter = live.next_start(utc(2026, 12, 1, 12))
        assert summer.astimezone(timezone.utc).hour == 1  # 9pm EDT is 1am UTC
        assert winter.astimezone(timezone.utc).hour == 2  # 9pm EST is 2am UTC

    def test_the_live_game_is_five_standard_questions(self):
        config = live.live_config()
        assert (config.rounds, config.case_mode) == (5, "off")

    def test_the_scheduler_opens_the_lobby_ten_minutes_early(self, monkeypatch):
        opened, waits = [], []

        class FakeHub:
            async def open_live(self, code, config, starts_at):
                opened.append((code, starts_at))

        async def sleep(seconds):
            waits.append(seconds)
            if len(waits) == 2:
                raise asyncio.CancelledError

        monkeypatch.setattr(live.asyncio, "sleep", sleep)
        now = lambda: utc(2026, 11, 11, 1, 0)  # 8pm EST: the lobby opens at 8:50
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(live.run(FakeHub(), now))
        assert waits[0] == 50 * 60
        assert opened == [("LIVE", live.ms(utc(2026, 11, 11, 2, 0)))]


class TestLiveRoom:
    def test_only_signed_in_players_may_sit(self, tmp_path):
        db = Database(tmp_path / "live.db")
        room, _ = live_room()
        with pytest.raises(RoomError) as caught:
            room.join("Guest")
        assert caught.value.code == "sign_in"
        player = room.join("", user=user(db, "Ann"))
        assert player.name == "Ann"

    def test_the_lobby_counts_down_and_the_timer_starts_the_game(self, tmp_path):
        db = Database(tmp_path / "live.db")
        room, clock = live_room()
        room.join("", user=user(db, "Ann")), room.join("", user=user(db, "Ben"))
        state = room.snapshot()
        assert state.phase == "LOBBY" and state.timer_ends_at == clock.now + 600_000
        assert state.live.starts_at == clock.now + 600_000 and not state.live.cancelled
        room.on_timer()
        assert room.phase is Phase.QUESTION and room.round_no == 1

    def test_too_few_players_calls_it_off(self, tmp_path):
        db = Database(tmp_path / "live.db")
        room, _ = live_room()
        room.join("", user=user(db, "Ann"))
        room.on_timer()
        assert room.phase is Phase.GAME_OVER and room.cancelled and room.snapshot().live.cancelled
        assert room.rounds_scored == 0

    def test_an_ordinary_room_is_not_live(self):
        room = Room("ABCD", live.live_config(), QUESTIONS, Clock())
        assert room.snapshot().live is None


class TestHub:
    def test_opening_replaces_last_night_s_room_and_publishes(self):
        clock = Clock()
        hub = Hub(QUESTIONS, clock=clock)
        hub.publish_interval = 0

        async def go():
            first = await hub.open_live(live.LIVE_CODE, live.live_config(), clock.now + 1000)
            second = await hub.open_live(live.LIVE_CODE, live.live_config(), clock.now + 5000)
            return first, second

        first, second = asyncio.run(go())
        assert hub.rooms[live.LIVE_CODE] is second and second is not first
        assert second.starts_at == clock.now + 5000

    def test_an_empty_live_lobby_is_never_dropped(self):
        clock = Clock()
        hub = Hub(QUESTIONS, clock=clock)
        room = Room(live.LIVE_CODE, live.live_config(), QUESTIONS, clock)
        room.schedule_live(clock.now + 10)
        room.empty_since = clock.now
        hub.rooms[live.LIVE_CODE] = room
        clock.now += EMPTY_ROOM_TTL_MS + 1
        hub._drop_expired_rooms()
        assert live.LIVE_CODE in hub.rooms


def play_live_game(db, names, points_order=None):
    """Plays a whole live game in which the first named player sells to the second at 50."""
    room, _ = live_room()
    seats = [room.join("", user=user(db, name)) for name in names]
    room.on_timer()
    advance_to(room, Phase.TRADING)
    room.place_order(seats[0], "SELL", Decimal(50), 1)
    room.place_order(seats[1], "BUY", Decimal(50), 1)
    advance_to(room, Phase.GAME_OVER)
    save_game(db, room)
    return seats


class TestTables:
    def test_a_saved_live_game_is_marked_and_tabled(self, tmp_path):
        db = Database(tmp_path / "live.db")
        play_live_game(db, ["Ann", "Ben", "Cal"])
        assert db.conn.execute("SELECT live FROM games").fetchone()[0] == 1
        last = live.last_game(db)
        assert [row["name"] for row in last["table"]] == ["Ben", "Cal", "Ann"]
        assert [row["place"] for row in last["table"]] == [1, 2, 3]
        board = live.standings(db)
        assert board[0]["name"] == "Ben" and board[0]["wins"] == 1 and board[0]["games"] == 1

    def test_ordinary_games_stay_off_the_live_tables(self, tmp_path):
        db = Database(tmp_path / "live.db")
        room = Room("ABCD", live.live_config(), QUESTIONS, Clock())
        a = room.join("", user=user(db, "Ann"))
        b = room.join("", user=user(db, "Ben"))
        room.start()
        advance_to(room, Phase.TRADING)
        room.place_order(a, "SELL", Decimal(50), 1)
        room.place_order(b, "BUY", Decimal(50), 1)
        advance_to(room, Phase.GAME_OVER)
        save_game(db, room)
        assert live.last_game(db) is None and live.standings(db) == []

    def test_a_confirmed_flag_keeps_someone_off_both_tables(self, tmp_path):
        db = Database(tmp_path / "live.db")
        play_live_game(db, ["Ann", "Ben", "Cal"])
        ben = db.conn.execute("SELECT id FROM users WHERE name = 'Ben'").fetchone()[0]
        db.conn.execute(
            "INSERT INTO accuracy_flags (user_id, status, quotes, bullseyes, baseline, p_value, after_quote_id, "
            "last_quote_id, created_at, updated_at) VALUES (?, 'confirmed', 20, 20, 0.05, 1e-9, 0, 0, 'x', 'x')",
            (ben,),
        )
        last = live.last_game(db)
        assert [(row["name"], row["place"]) for row in last["table"]] == [("Cal", 1), ("Ann", 2)]
        assert "Ben" not in [row["name"] for row in live.standings(db)]
        assert anticheat.standing(db, ben) == "confirmed"


class TestApi:
    def test_the_overview_shows_the_next_start_and_tonight_s_room(self, app_db):
        anon = TestClient(app_module.app)
        answer = anon.get("/api/live").json()
        assert answer["hour"] == 21 and answer["rounds"] == 5 and answer["room"] is None
        assert answer["next_start"] > 0 and answer["signed_in"] is False and answer["last"] is None
        room = Room(live.LIVE_CODE, live.live_config(), QUESTIONS, Clock())
        room.schedule_live(123)
        app_module.hub.rooms[live.LIVE_CODE] = room
        try:
            tonight = client_for("Ann").get("/api/live").json()
        finally:
            app_module.hub.rooms.pop(live.LIVE_CODE, None)
        assert tonight["signed_in"] is True
        assert tonight["room"] == {
            "code": "LIVE", "phase": "LOBBY", "round_no": 0, "rounds_total": 5, "players": 0, "starts_at": 123, "cancelled": False,
        }

    def test_the_word_list_never_hands_out_the_live_code(self):
        from server.room_codes import ROOM_WORDS

        assert live.LIVE_CODE not in ROOM_WORDS
