import asyncio
import math
import random
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from server import anticheat, endless
from server import app as app_module
from server.db import Database, EndlessResult, endless_award
from server.engine.models import Side
from server.protocol import HintView
from server.rooms import (
    ENDLESS_CODE,
    HOUSE_TRADERS,
    SEAT_GRACE_MS,
    Hub,
    Phase,
    house_market,
    house_view,
    learn,
    save_endless_round,
)
from server.tests.test_rooms import Clock, make_question
from server.tests.test_social import account, app_db  # noqa: F401  (fixture)

BANK = [make_question(i) for i in range(20)]  # every answer is 100


def table(clock=None):
    hub = Hub(BANK, clock=clock or Clock())
    return hub, hub.endless_table()


def sit(room, name, user=None):
    player = room.join(name, user=user)
    player.session = object()  # connected, as Hub._attach_player would leave it
    room.wake()
    return player


def through(room, phase):
    while room.phase is not phase:
        room.advance()


class TestHouseBelief:
    def test_the_house_view_is_shared_and_never_the_answer(self):
        rng = random.Random(1)
        errors = sorted(abs(math.log(house_view(Decimal(100), rng) / 100)) for _ in range(2000))
        assert 0.2 < errors[len(errors) // 2] < 0.4  # a typical house view is 25-50% off
        assert errors[-1] > 0.9  # and now and then it's off by more than double

    def test_a_long_bot_quotes_lower_to_get_flat(self):
        flat = house_market(100, 0, Decimal(1), random.Random(3))
        long = house_market(100, 4, Decimal(1), random.Random(3))
        assert long[0] < flat[0] and long[1] < flat[1]
        assert flat[0] < 100 < flat[1]

    def test_belief_moves_toward_trades_and_into_the_hint(self):
        assert learn(100, 200, None) == pytest.approx(100 * 2 ** 0.3)
        hinted = learn(100, 100, HintView(low=Decimal(300), high=Decimal(600)))
        assert 300 <= hinted <= 600


class TestTable:
    def test_the_first_person_wakes_it_and_the_house_fills_the_seats(self):
        _, room = table()
        assert room.phase is Phase.LOBBY and room.endless
        sit(room, "Ann")
        assert room.phase is Phase.QUESTION and room.round_no == 1
        assert sum(p.is_bot for p in room.players) == HOUSE_TRADERS - 1
        state = room.snapshot()
        assert state.endless and state.rounds_total == 0
        assert room.bot_center() != room.question.answer  # the house prices around its own view

    def test_it_never_ends(self):
        _, room = table()
        sit(room, "Ann")
        for _ in range(30):
            through(room, Phase.SCORES)
            room.advance()
        assert room.round_no == 31 and room.phase is Phase.QUESTION

    def test_it_idles_when_everyone_has_gone_and_wakes_on_return(self):
        _, room = table()
        ann = sit(room, "Ann")
        ann.session, ann.left_at = None, room.clock()
        through(room, Phase.SCORES)
        room.advance()
        assert room.phase is Phase.LOBBY and room.round_no == 1
        ann.session = object()
        room.wake()
        assert room.phase is Phase.QUESTION and room.round_no == 2

    def test_bots_step_back_as_people_arrive(self):
        _, room = table()
        sit(room, "Ann")
        for name in ("Ben", "Cal", "Dee"):
            sit(room, name)
        through(room, Phase.SCORES)
        room.advance()
        assert sum(p.is_bot for p in room.players) == HOUSE_TRADERS - 4

    def test_a_dropped_seat_is_freed_after_the_grace_period(self):
        clock = Clock()
        _, room = table(clock)
        sit(room, "Ann")
        ben = sit(room, "Ben")
        ben.session, ben.left_at = None, clock.now
        clock.now += SEAT_GRACE_MS + 1
        through(room, Phase.SCORES)
        room.advance()
        assert "Ben" not in [p.name for p in room.players]

    def test_questions_do_not_repeat_until_half_the_pool_has_played(self):
        _, room = table()
        sit(room, "Ann")
        for _ in range(29):
            through(room, Phase.SCORES)
            room.advance()
        ids = [q.id for q in room.questions[: room.round_no]]
        for i in range(len(ids)):
            assert ids[i] not in ids[max(0, i - 10) : i]

    def test_late_arrivals_play_from_the_next_question(self):
        _, room = table()
        sit(room, "Ann")
        through(room, Phase.TRADING)
        ben = sit(room, "Ben")
        assert ben.plays_from == room.round_no + 1


class TestMarketMaking:
    def test_a_house_bot_keeps_a_bid_and_an_ask_around_the_house_view(self, monkeypatch):
        hub, room = table()
        sit(room, "Ann")
        through(room, Phase.TRADING)
        bot = next(p for p in room.players if p.is_bot)

        async def one_pass(_seconds):
            room.transitions += 1  # as if the phase moved on

        monkeypatch.setattr("server.rooms.asyncio.sleep", one_pass)

        async def publish(_room):
            return None

        monkeypatch.setattr(hub, "publish", publish)
        asyncio.run(hub._make_market(room, bot, room.transitions))
        orders = room.book.resting_orders(bot.id)
        sides = {o.side for o in orders}
        assert sides == {Side.BUY, Side.SELL} or room.book.position(bot.id) != 0
        view = float(room.house_view)
        for order in orders:
            assert 0.6 * view < float(order.price) < 1.6 * view


class TestPayouts:
    def test_points_off_the_house_pay_a_quarter(self):
        people = EndlessResult(user_id=1, points=Decimal(40), vs_people=Decimal(40), vs_house=Decimal(0), trades=1, best_quote=False)
        house = EndlessResult(user_id=1, points=Decimal(40), vs_people=Decimal(0), vs_house=Decimal(40), trades=1, best_quote=False)
        assert endless_award(people) == (40, 7)
        assert endless_award(house) == (10, 7)
        best = EndlessResult(user_id=1, points=Decimal(25), vs_people=Decimal(0), vs_house=Decimal(0), trades=0, best_quote=True)
        assert endless_award(best) == (35, 20)

    def test_a_round_is_paid_split_by_counterparty(self, tmp_path):
        db = Database(tmp_path / "endless.db")
        hub, room = table()
        user, _ = account(db, "Ann")
        ann = sit(room, "", user={"id": user["id"], "name": "Ann"})
        guest = sit(room, "Guest")
        bot = next(p for p in room.players if p.is_bot)
        through(room, Phase.TRADING)
        room.place_order(bot, Side.SELL, Decimal(50), 1)
        room.place_order(ann, Side.BUY, Decimal(50), 1)  # +69 off the house
        room.place_order(guest, Side.SELL, Decimal(200), 1)
        room.place_order(ann, Side.BUY, Decimal(200), 1)  # -69 to a person
        through(room, Phase.REVEAL)
        save_endless_round(db, room)
        row = db.conn.execute("SELECT * FROM endless_results").fetchone()
        assert float(row["vs_house"]) == pytest.approx(69.31) and float(row["vs_people"]) == pytest.approx(-69.31)
        assert row["trades"] == 2 and row["best_quote"] == 0
        assert (ann.coins_awarded, ann.xp_awarded) == (row["coins"], row["xp"])
        assert row["coins"] == 17  # nothing net from people, a quarter of 69 off the house
        assert row["xp"] == 5 + 2 * 2
        game = db.conn.execute("SELECT endless, rounds FROM games").fetchone()
        assert (game["endless"], game["rounds"]) == (1, 1)

    def test_quotes_go_to_the_log_for_anti_cheat(self, tmp_path, monkeypatch):
        db = Database(tmp_path / "endless.db")
        reviewed = []
        monkeypatch.setattr(anticheat, "review", lambda _db, user_id: reviewed.append(user_id))
        _, room = table()
        user, _ = account(db, "Ann")
        ann = sit(room, "", user={"id": user["id"], "name": "Ann"})
        through(room, Phase.QUOTING)
        room.submit_quote(ann, Decimal(90), Decimal(110))
        through(room, Phase.REVEAL)
        save_endless_round(db, room)
        quote = db.conn.execute("SELECT * FROM quote_log").fetchone()
        assert quote["question_id"] == room.question.id and quote["round_no"] == 1
        assert db.conn.execute("SELECT best_quote, coins FROM endless_results").fetchone()[:] == (1, 35)
        assert reviewed == [user["id"]]
        assert db.conn.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0  # not a game in history
        assert room.quote_log == [] and room.game_fills == []

    def test_sitting_at_the_table_earns_nothing(self, tmp_path):
        db = Database(tmp_path / "endless.db")
        _, room = table()
        user, _ = account(db, "Ann")
        sit(room, "", user={"id": user["id"], "name": "Ann"})
        through(room, Phase.REVEAL)
        save_endless_round(db, room)
        assert db.conn.execute("SELECT COUNT(*) FROM endless_results").fetchone()[0] == 0

    def test_the_hub_pays_each_round_once(self):
        paid = []
        hub = Hub(BANK, clock=Clock(), on_round_over=lambda room: paid.append(room.round_no))
        hub.publish_interval = 0
        room = hub.endless_table()
        sit(room, "Ann")

        async def go():
            through(room, Phase.REVEAL)
            await hub.publish(room)
            await hub.publish(room)
            through(room, Phase.SCORES)
            room.advance()
            through(room, Phase.REVEAL)
            await hub.publish(room)
            for task in room.bot_tasks:
                task.cancel()
            if room.timer_task:
                room.timer_task.cancel()

        asyncio.run(go())
        assert paid == [1, 2]


class TestBoards:
    def test_today_and_this_week_add_up_rounds_and_leave_out_confirmed_cheats(self, tmp_path):
        db = Database(tmp_path / "endless.db")
        from server.db import RoundRecord

        ann, _ = account(db, "Ann")
        ben, _ = account(db, "Ben")
        record = RoundRecord(round_no=1, question="Q?", unit="widgets", answer=Decimal(100))

        def round_for(user_id, points):
            result = EndlessResult(user_id=user_id, points=Decimal(points), vs_people=Decimal(points), vs_house=Decimal(0), trades=1, best_quote=False)
            db.record_endless_round("OPEN", record, 2, [result])

        round_for(ann["id"], 30)
        round_for(ann["id"], -10)
        round_for(ben["id"], 50)
        start = datetime(2000, 1, 1, tzinfo=timezone.utc)
        board = endless.board(db, start, viewer=ann["id"])
        assert [(row["name"], row["points"], row["rounds"]) for row in board["top"]] == [("Ben", 50, 1), ("Ann", 20, 2)]
        assert board["you"]["place"] == 2
        db.conn.execute(
            "INSERT INTO accuracy_flags (user_id, status, quotes, bullseyes, baseline, p_value, after_quote_id, "
            "last_quote_id, created_at, updated_at) VALUES (?, 'confirmed', 20, 20, 0.05, 1e-9, 0, 0, 'x', 'x')",
            (ben["id"],),
        )
        assert [row["name"] for row in endless.board(db, start)["top"]] == ["Ann"]

    def test_the_day_starts_at_midnight_eastern(self):
        now = datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)  # 10pm Nov 10 Eastern
        assert endless.day_start(now).isoformat() == "2026-11-10T05:00:00+00:00"
        assert endless.week_start(now).isoformat() == "2026-11-09T05:00:00+00:00"  # Monday


class TestApi:
    def test_the_overview_before_anyone_sits(self, app_db):
        app_module.hub.rooms.pop(ENDLESS_CODE, None)
        answer = TestClient(app_module.app).get("/api/open").json()
        assert answer["code"] == "OPEN" and answer["people"] == 0 and answer["running"] is False
        assert answer["today"]["top"] == [] and answer["signed_in"] is False

    def test_the_code_is_reserved(self):
        from server.room_codes import ROOM_WORDS

        assert ENDLESS_CODE not in ROOM_WORDS
