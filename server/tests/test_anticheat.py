import math
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from server import anticheat
from server import app as app_module
from server.db import Database, GameResult, QuoteRecord, RoundRecord
from server.protocol import RoomConfig
from server.rooms import Phase, Room, save_game
from server.tests.test_rooms import QUESTIONS, Clock, advance_to
from server.tests.test_social import account, app_db, client_for  # noqa: F401  (fixture)


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "anticheat.db")


def uid(db, name):
    return account(db, name)[0]["id"]


BULLSEYE = ("98", "102")  # holds 100, ask/bid about 1.04
WIDE = ("50", "200")  # holds 100 but four times wide
MISS = ("150", "170")  # tight but wrong


def play(db, user_id, quotes, question="How many?"):
    """Saves one game in which `user_id` sealed each (bid, ask) in turn, the answer always 100."""
    records = [
        QuoteRecord(
            round_no=i + 1, user_id=user_id, name="x", bid=Decimal(bid), ask=Decimal(ask), answer=Decimal(100),
            mid_error=math.log(math.sqrt(float(bid) * float(ask)) / 100), fills=0, question_id=f"q{i}", quote_ms=4000,
        )
        for i, (bid, ask) in enumerate(quotes)
    ]
    rounds = [RoundRecord(round_no=i + 1, question=question, unit="widgets", answer=Decimal(100)) for i in range(len(quotes))]
    result = GameResult(user_id=user_id, name="x", points=Decimal(0), positive_points=Decimal(0), rank=1, best_quotes=0, trades=0)
    db.record_game("ABCD", len(quotes), 2, [result], records, rounds_played=rounds)


def honest_crowd(db, players=5, games=4):
    """Players who land a bullseye now and then: one in ten quotes."""
    for n in range(players):
        player = uid(db, f"Honest{n}")
        for _ in range(games):
            play(db, player, [BULLSEYE] + [WIDE] * 5 + [MISS] * 4)


class TestBullseyes:
    @pytest.mark.parametrize(
        "bid, ask, hit",
        [("98", "102", True), ("100", "100", True), ("80", "100", True), ("79", "100", False), ("101", "120", False), ("50", "200", False)],
    )
    def test_a_bullseye_holds_the_answer_and_is_tight(self, bid, ask, hit):
        assert anticheat.is_bullseye(bid, ask, "100") is hit

    def test_the_binomial_tail_matches_a_hand_count(self):
        # P(X >= 2) for 3 trials at 0.5 is 4/8.
        assert anticheat.binomial_tail(2, 3, 0.5) == pytest.approx(0.5)
        assert anticheat.binomial_tail(0, 10, 0.1) == 1.0
        assert anticheat.binomial_tail(20, 20, 0.05) == pytest.approx(0.05 ** 20)

    def test_a_long_record_does_not_overflow(self):
        assert 0 < anticheat.binomial_tail(300, 2000, 0.1) < 1e-10


class TestFlagging:
    def test_someone_who_keeps_hitting_bullseyes_is_flagged_quietly(self, db):
        honest_crowd(db)
        cheat = uid(db, "Cheat")
        for _ in range(3):
            play(db, cheat, [BULLSEYE] * 7)
        assert anticheat.review(db, cheat) == "flagged"
        (flag,) = anticheat.queue(db)
        assert flag["status"] == "open" and flag["quotes"] == 21 and flag["bullseyes"] == 21
        assert flag["p_value"] < anticheat.ALPHA and flag["player"]["name"] == "Cheat"
        assert flag["recent"][0]["bullseye"] and flag["recent"][0]["seconds"] == 4.0
        assert flag["recent"][0]["question"] == "How many?"

    def test_nobody_is_judged_before_enough_quotes(self, db):
        honest_crowd(db)
        sharp = uid(db, "Sharp")
        play(db, sharp, [BULLSEYE] * (anticheat.MIN_QUOTES - 1))
        assert anticheat.review(db, sharp) is None
        assert anticheat.queue(db) == []

    def test_an_honest_good_player_is_not_flagged(self, db):
        honest_crowd(db)
        good = uid(db, "Good")
        for _ in range(4):
            play(db, good, [BULLSEYE] * 2 + [WIDE] * 6 + [MISS] * 2)  # twice the crowd's rate
        assert anticheat.review(db, good) is None

    def test_a_tiny_player_base_cannot_make_luck_look_impossible(self, db):
        # Nobody else has played: the prior (5 in 100) stands in for everyone else's rate.
        lucky = uid(db, "Lucky")
        play(db, lucky, [BULLSEYE] * 3 + [WIDE] * 17)
        assert anticheat.review(db, lucky) is None

    def test_a_cleared_player_is_judged_only_on_new_quotes(self, db):
        honest_crowd(db)
        sharp = uid(db, "Sharp")
        for _ in range(3):
            play(db, sharp, [BULLSEYE] * 7)
        anticheat.review(db, sharp)
        flag_id = anticheat.queue(db)[0]["id"]
        anticheat.resolve(db, flag_id, "clear")
        play(db, sharp, [BULLSEYE] * 7)
        assert anticheat.review(db, sharp) is None  # 7 new quotes: too few to judge again
        play(db, sharp, [BULLSEYE] * 14)
        assert anticheat.review(db, sharp) == "flagged"
        open_flags = [f for f in anticheat.queue(db) if f["status"] == "open"]
        assert open_flags[0]["quotes"] == 21

    def test_an_open_flag_keeps_its_figures_current(self, db):
        honest_crowd(db)
        cheat = uid(db, "Cheat")
        for _ in range(3):
            play(db, cheat, [BULLSEYE] * 7)
        anticheat.review(db, cheat)
        play(db, cheat, [WIDE] * 5)
        assert anticheat.review(db, cheat) == "updated"
        (flag,) = anticheat.queue(db)
        assert (flag["quotes"], flag["bullseyes"]) == (26, 21)

    def test_confirming_is_recorded_for_live_mode(self, db):
        honest_crowd(db)
        cheat = uid(db, "Cheat")
        for _ in range(3):
            play(db, cheat, [BULLSEYE] * 7)
        anticheat.review(db, cheat)
        anticheat.resolve(db, anticheat.queue(db)[0]["id"], "confirm")
        assert anticheat.standing(db, cheat) == "confirmed"
        assert anticheat.standing(db, uid(db, "Honest0")) is None
        with pytest.raises(Exception):
            anticheat.resolve(db, 999, "clear")

    def test_the_flag_ranks_them_against_regular_players(self, db):
        honest_crowd(db)
        cheat = uid(db, "Cheat")
        for _ in range(3):
            play(db, cheat, [BULLSEYE] * 7)
        anticheat.review(db, cheat)
        (flag,) = anticheat.queue(db)
        assert (flag["beats"], flag["regulars"]) == (5, 5)
        assert flag["recent"][0]["spread"] == pytest.approx(1.04)


class TestFromTheRoom:
    def test_each_quote_records_its_question_and_timing(self):
        clock = Clock()
        room = Room("ABCD", RoomConfig(rounds=3), QUESTIONS, clock)
        a, b = room.join("A"), room.join("B")
        a.user_id = 7
        advance_to(room, Phase.QUOTING)
        clock.now += 6500
        room.submit_quote(a, Decimal(90), Decimal(110))
        advance_to(room, Phase.REVEAL)
        (record, *_) = room.quote_log
        assert record.question_id == room.question.id and record.quote_ms == 6500

    def test_a_saved_game_checks_everyone_signed_in(self, db, monkeypatch):
        checked = []
        monkeypatch.setattr(anticheat, "review", lambda _db, user_id: checked.append(user_id))
        room = Room("ABCD", RoomConfig(rounds=3), QUESTIONS, Clock())
        a = room.join("", user={"id": uid(db, "Ann"), "name": "Ann"})
        room.join("Guest")
        advance_to(room, Phase.QUOTING)
        room.submit_quote(a, Decimal(90), Decimal(110))
        advance_to(room, Phase.GAME_OVER)
        save_game(db, room)
        assert checked == [a.user_id]

    def test_older_databases_get_the_new_columns(self, tmp_path):
        path = tmp_path / "old.db"
        Database(path).conn.execute("ALTER TABLE quote_log DROP COLUMN quote_ms")
        reopened = Database(path)
        columns = {row["name"] for row in reopened.conn.execute("PRAGMA table_info(quote_log)")}
        assert {"question_id", "quote_ms"} <= columns


class TestApi:
    def test_only_the_admin_sees_the_queue(self, app_db, monkeypatch):
        assert TestClient(app_module.app).get("/api/admin/flags").status_code == 401
        ann = client_for("Ann")
        assert ann.get("/api/admin/flags").status_code == 403
        monkeypatch.setenv("ADMIN_EMAILS", "ann@example.com")
        answer = ann.get("/api/admin/flags").json()
        assert answer["flags"] == [] and answer["min_quotes"] == anticheat.MIN_QUOTES

    def test_the_admin_clears_a_flag(self, app_db, monkeypatch):
        honest_crowd(app_db)
        cheat = uid(app_db, "Cheat")
        for _ in range(3):
            play(app_db, cheat, [BULLSEYE] * 7)
        anticheat.review(app_db, cheat)
        monkeypatch.setenv("ADMIN_EMAILS", "ann@example.com")
        ann = client_for("Ann")
        flag_id = ann.get("/api/admin/flags").json()["flags"][0]["id"]
        assert ann.post(f"/api/admin/flags/{flag_id}", json={"action": "clear"}).json() == {"ok": True}
        assert ann.get("/api/admin/flags").json()["flags"][0]["status"] == "cleared"
        assert ann.post(f"/api/admin/flags/{flag_id}", json={"action": "ban"}).status_code == 400
