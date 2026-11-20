import asyncio
import math
import random
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server import app as app_module
from server.engine.models import BookSnapshot, PositionLimitError, Question, Side
from server.protocol import RoomConfig, Timers
from server.room_codes import ROOM_WORDS
from server.questions.validate import check_bank, load_bank, servable
from server.rooms import (
    MAX_PLAYERS,
    ROOM_CODE_ALPHABET,
    Hub,
    Phase,
    Room,
    RoomError,
    make_hint,
    pick_questions,
    reading_seconds,
    round_multipliers,
    drinks_for,
    bot_order,
    bot_quote,
    MAX_DRINKS_PER_ROUND,
    save_game,
)


def make_question(index=0, answer=100, status="verified", tick=1, category="test"):
    return Question(
        id=f"q{index}",
        text=f"Question {index}?",
        unit="widgets",
        answer=None if answer is None else Decimal(str(answer)),
        tick=Decimal(str(tick)),
        source_url="https://example.com",
        source_note="note",
        category=category,
        difficulty=1,
        as_of="2026",
        status=status,
    )


QUESTIONS = [make_question(i) for i in range(20)]


class Clock:
    def __init__(self):
        self.now = 1_000_000

    def __call__(self):
        return self.now


def make_room(players=3, rounds=3, code="ABCD", questions=QUESTIONS):
    clock = Clock()
    room = Room(code, RoomConfig(rounds=rounds), questions, clock)
    seated = [room.join(f"P{i}") for i in range(players)]
    return room, seated


def advance_to(room, phase):
    if room.phase is Phase.LOBBY:
        room.start()
    while room.phase is not phase:
        room.advance()


def error_code(call, *args):
    with pytest.raises(RoomError) as caught:
        call(*args)
    return caught.value.code


def view(snapshot, player):
    return next(p for p in snapshot.players if p.id == player.id)


class TestStateMachine:
    def test_starts_in_lobby_without_a_timer(self):
        room, _ = make_room()
        assert room.phase is Phase.LOBBY
        assert room.timer_ends_at is None

    def test_needs_two_players_to_start(self):
        room, _ = make_room(players=1)
        assert error_code(room.start) == "not_enough_players"

    def test_phases_run_in_order_through_every_round(self):
        room, _ = make_room(rounds=3)
        room.start()
        seen = [(room.round_no, room.phase)]
        while room.phase is not Phase.GAME_OVER:
            room.advance()
            seen.append((room.round_no, room.phase))
        round_phases = [
            Phase.QUESTION,
            Phase.QUOTING,
            Phase.TRADING,
            Phase.REVEAL,
            Phase.SCORES,
        ]
        expected = [(n, phase) for n in (1, 2, 3) for phase in round_phases]
        assert seen == expected + [(3, Phase.GAME_OVER)]

    def test_each_phase_sets_its_default_deadline(self):
        room, _ = make_room()
        room.start()
        for phase, seconds in [
            (Phase.QUESTION, 5),
            (Phase.QUOTING, 20),
            (Phase.TRADING, 45),
            (Phase.REVEAL, 10),
            (Phase.SCORES, 10),
        ]:
            assert room.phase is phase
            assert room.timer_ends_at == room.clock() + seconds * 1000
            room.advance()

    def test_game_over_has_no_timer_and_cannot_advance(self):
        room, _ = make_room()
        advance_to(room, Phase.GAME_OVER)
        assert room.timer_ends_at is None
        assert error_code(room.advance) == "wrong_phase"

    def test_lobby_cannot_advance(self):
        room, _ = make_room()
        assert error_code(room.advance) == "wrong_phase"

    def test_host_can_end_at_any_time(self):
        room, _ = make_room()
        advance_to(room, Phase.TRADING)
        room.end()
        assert room.phase is Phase.GAME_OVER

    def test_each_round_uses_a_different_question(self):
        room, _ = make_room(rounds=5)
        assert len({question.id for question in room.questions}) == 5

    def test_at_most_one_geography_question_per_game(self):
        bank = [make_question(i, category="places") for i in range(10)]
        bank += [make_question(i, category="food") for i in range(10, 20)]
        for seed in range(20):
            picked = pick_questions(bank, 7, random.Random(seed))
            assert len(picked) == 7
            assert len({q.id for q in picked}) == 7
            assert sum(q.category == "places" for q in picked) == 1

    def test_the_cap_gives_way_when_the_bank_runs_short(self):
        bank = [make_question(i, category="places") for i in range(5)]
        bank += [make_question(i, category="food") for i in range(5, 8)]
        picked = pick_questions(bank, 7, random.Random(0))
        assert len({q.id for q in picked}) == 7
        assert sum(q.category == "places" for q in picked) == 4

    def test_spicy_questions_only_come_out_in_drinks_mode(self):
        bank = [make_question(i, category="spicy") for i in range(5)]
        bank += [make_question(i, category="food") for i in range(5, 15)]
        for seed in range(10):
            tame = pick_questions(bank, 7, random.Random(seed))
            assert not any(q.category == "spicy" for q in tame)
            hot = pick_questions(bank, 7, random.Random(seed), spicy=True)
            assert sum(q.category == "spicy" for q in hot) == 5  # every one, then tame padding
            assert len({q.id for q in hot}) == 7

    def test_turning_drinks_on_in_the_lobby_redraws_the_questions(self):
        bank = [make_question(i, category="spicy") for i in range(100, 103)] + QUESTIONS
        room = Room("ABCD", RoomConfig(rounds=3), bank, Clock())
        assert not any(q.category == "spicy" for q in room.questions)
        room.configure(drinks=True)
        assert all(q.category == "spicy" for q in room.questions)
        room.configure(drink_strength=5)  # unrelated settings leave the draw alone
        assert all(q.category == "spicy" for q in room.questions)
        room.configure(drinks=False)
        assert not any(q.category == "spicy" for q in room.questions)

    def test_the_same_code_can_get_different_questions(self):
        games = {tuple(q.id for q in make_room(rounds=5)[0].questions) for _ in range(5)}
        assert len(games) > 1

    def test_new_round_clears_the_last_one(self):
        room, (a, b, _) = make_room()
        advance_to(room, Phase.TRADING)
        room.place_order(a, Side.SELL, Decimal(90), 1)
        room.place_order(b, Side.BUY, Decimal(90), 1)
        advance_to(room, Phase.QUESTION)
        snapshot = room.snapshot(a)
        assert snapshot.round_no == 2
        assert snapshot.tape == []
        assert snapshot.you.position == 0
        assert snapshot.you.round_points is None
        assert snapshot.question.answer is None


class TestJoining:
    def test_names_are_trimmed(self):
        room, _ = make_room(players=0)
        assert room.join("  Sam  ").name == "Sam"

    @pytest.mark.parametrize("name", ["", "   ", "x" * 17])
    def test_bad_names_are_rejected(self, name):
        room, _ = make_room(players=0)
        assert error_code(room.join, name) == "bad_name"

    def test_names_are_unique_ignoring_case(self):
        room, _ = make_room(players=0)
        room.join("Sam")
        assert error_code(room.join, "sam") == "name_taken"

    def test_room_holds_twelve(self):
        room, _ = make_room(players=MAX_PLAYERS)
        assert error_code(room.join, "Extra") == "room_full"

    def test_late_joiners_sit_out_the_round_then_play(self):
        room, _ = make_room(rounds=3)
        advance_to(room, Phase.TRADING)
        late = room.join("Late")
        assert late.plays_from == 2
        assert room.snapshot(late).you.sitting_out is True
        assert error_code(room.place_order, late, Side.BUY, Decimal(90), 1) == "sitting_out"
        advance_to(room, Phase.QUOTING)  # round 2
        assert room.round_no == 2 and room.snapshot(late).you.sitting_out is False
        room.submit_quote(late, Decimal(90), Decimal(110))
        assert view(room.snapshot(), late).quoted is True

    def test_joining_while_the_question_is_up_plays_that_round(self):
        room, _ = make_room(rounds=3)
        room.start()
        early = room.join("Early")
        assert early.plays_from == 1 and room.snapshot(early).you.sitting_out is False
        room.advance()  # QUOTING
        room.submit_quote(early, Decimal(90), Decimal(110))
        after_quotes = room.join("Later")
        assert error_code(room.submit_quote, after_quotes, Decimal(90), Decimal(110)) == "sitting_out"

    def test_token_reclaims_the_seat_mid_game(self):
        room, (a, _, _) = make_room()
        advance_to(room, Phase.TRADING)
        assert room.join("anything", a.token) is a

    def test_bad_token_mid_game_is_a_new_seat(self):
        room, _ = make_room()
        room.start()
        late = room.join("Late", "wrong-token")  # an unknown token is just a new seat
        benched = room.phase is not Phase.QUESTION
        assert late.plays_from == (room.round_no + 1 if benched else room.round_no)


class TestQuoting:
    def test_quotes_only_during_quoting(self):
        room, (a, _, _) = make_room()
        room.start()
        assert error_code(room.submit_quote, a, Decimal(90), Decimal(110)) == "wrong_phase"

    @pytest.mark.parametrize(
        ("bid", "ask"),
        [("110", "90"), ("90", "90"), ("0", "90"), ("-5", "90"), ("90.5", "110"), ("1e999999", "2e999999")],
    )
    def test_bad_quotes_are_rejected(self, bid, ask):
        room, (a, _, _) = make_room()
        advance_to(room, Phase.QUOTING)
        assert error_code(room.submit_quote, a, Decimal(bid), Decimal(ask)) == "invalid_quote"

    def test_resubmitting_replaces_the_quote(self):
        room, (a, _, _) = make_room()
        advance_to(room, Phase.QUOTING)
        room.submit_quote(a, Decimal(90), Decimal(110))
        room.submit_quote(a, Decimal(95), Decimal(105))
        assert room.snapshot(a).you.quote.bid == 95

    def test_quotes_stay_sealed_from_other_players_and_the_host(self):
        room, (a, b, _) = make_room()
        advance_to(room, Phase.QUOTING)
        room.submit_quote(a, Decimal(91), Decimal(113))
        assert view(room.snapshot(b), a).quoted is True
        for snapshot in (room.snapshot(b), room.snapshot()):
            text = snapshot.model_dump_json()
            assert "91" not in text
            assert "113" not in text

    def test_quoting_is_optional(self):
        room, (a, b, _) = make_room()
        advance_to(room, Phase.QUOTING)
        room.submit_quote(a, Decimal(90), Decimal(110))
        room.advance()
        assert room.snapshot(b).you.resting_orders == []


class TestOpeningTheBook:
    def quote_and_open(self, code="ABCD"):
        room, (a, b, c) = make_room(code=code)
        advance_to(room, Phase.QUOTING)
        room.submit_quote(a, Decimal(90), Decimal(110))
        room.submit_quote(b, Decimal(120), Decimal(130))
        room.submit_quote(c, Decimal(80), Decimal(140))
        room.advance()
        return room, a, b, c

    def test_every_quote_rests_on_both_sides(self):
        room, (a, b, _) = make_room()
        advance_to(room, Phase.QUOTING)
        room.submit_quote(a, Decimal(90), Decimal(110))
        room.submit_quote(b, Decimal(85), Decimal(115))
        room.advance()
        snapshot = room.snapshot(a)
        assert room.fills == []
        assert [level.price for level in snapshot.book.bids] == [90, 85]
        assert [level.price for level in snapshot.book.asks] == [110, 115]

    def test_crossing_quotes_fill_at_the_open(self):
        room, a, b, _ = self.quote_and_open()
        [fill] = room.fills
        assert (fill.buyer_id, fill.seller_id) == (b.id, a.id)
        assert fill.size == 1
        assert room.snapshot(a).you.position == -1

    def test_the_open_is_reproducible_for_the_same_room_and_round(self):
        first, *_ = self.quote_and_open()
        second, *_ = self.quote_and_open()
        assert first.fills == second.fills

    def test_the_shuffle_depends_on_the_room_code(self):
        prices = {
            self.quote_and_open(code=code)[0].fills[0].price
            for code in ("ABCD", "EFGH", "JKLM", "NPQR", "STUV", "WXYZ")
        }
        assert prices == {Decimal(110), Decimal(120)}

    def test_a_low_position_limit_cannot_break_the_open(self):
        clock = Clock()
        room = Room("ABCD", RoomConfig(rounds=3, position_limit=1), QUESTIONS, clock)
        a, b, c = room.join("A"), room.join("B"), room.join("C")
        advance_to(room, Phase.QUOTING)
        room.submit_quote(a, Decimal(90), Decimal(91))
        room.submit_quote(b, Decimal(92), Decimal(93))
        room.submit_quote(c, Decimal(94), Decimal(95))
        room.advance()
        assert room.phase is Phase.TRADING


class TestTrading:
    def test_orders_only_during_trading(self):
        room, (a, _, _) = make_room()
        advance_to(room, Phase.QUOTING)
        assert error_code(room.place_order, a, Side.BUY, Decimal(90), 1) == "wrong_phase"

    def test_tape_shows_names_newest_first(self):
        room, (a, b, c) = make_room()
        advance_to(room, Phase.TRADING)
        room.place_order(a, Side.SELL, Decimal(90), 2)
        room.place_order(b, Side.BUY, Decimal(90), 1)
        room.place_order(c, Side.BUY, Decimal(90), 1)
        tape = room.snapshot().tape
        assert [(t.buyer, t.seller) for t in tape] == [("P2", "P0"), ("P1", "P0")]

    def test_cancel_only_during_trading(self):
        room, (a, _, _) = make_room()
        advance_to(room, Phase.TRADING)
        room.place_order(a, Side.BUY, Decimal(90), 1)
        order_id = room.snapshot(a).you.resting_orders[0].id
        room.advance()
        assert error_code(room.cancel_order, a, order_id) == "wrong_phase"


class TestSettlement:
    def test_answer_is_hidden_until_reveal(self):
        room, (a, _, _) = make_room()
        for phase in (Phase.QUESTION, Phase.QUOTING, Phase.TRADING):
            advance_to(room, phase)
            for snapshot in (room.snapshot(a), room.snapshot()):
                assert snapshot.question.answer is None
                assert snapshot.question.source_url is None

    def test_reveal_shows_answer_and_source(self):
        room, _ = make_room()
        advance_to(room, Phase.REVEAL)
        assert room.snapshot().question.answer == 100
        assert room.snapshot().question.source_url

    def test_round_points_include_fills_and_best_quote(self):
        room, (a, b, c) = make_room()
        advance_to(room, Phase.QUOTING)
        room.submit_quote(a, Decimal(90), Decimal(110))
        room.submit_quote(b, Decimal(50), Decimal(150))
        advance_to(room, Phase.TRADING)
        room.place_order(c, Side.SELL, Decimal(50), 1)
        advance_to(room, Phase.REVEAL)
        snapshot = room.snapshot()
        assert snapshot.best_quote.name == "P0"
        assert view(snapshot, a).round_points == Decimal("35.54")  # bought at 90, plus bonus
        assert view(snapshot, b).round_points == 0
        assert view(snapshot, c).round_points == Decimal("-10.54")

    def test_totals_accumulate_across_rounds(self):
        room, (a, b, _) = make_room()
        for _round in range(2):
            advance_to(room, Phase.TRADING)
            room.place_order(a, Side.SELL, Decimal(50), 1)
            room.place_order(b, Side.BUY, Decimal(50), 1)
            advance_to(room, Phase.SCORES)
            if _round == 0:
                room.advance()
        snapshot = room.snapshot()
        assert view(snapshot, b).total_points == Decimal("138.62")
        assert view(snapshot, a).total_points == Decimal("-138.62")

    def test_ending_mid_trading_does_not_reveal(self):
        room, _ = make_room()
        advance_to(room, Phase.TRADING)
        room.end()
        assert room.snapshot().question.answer is None

    def test_drinks_scale_with_losses_and_strength(self):
        assert drinks_for(Decimal("10"), 2) == 0
        assert drinks_for(Decimal("-49"), 2) == 0
        assert drinks_for(Decimal("-50"), 2) == 1
        assert drinks_for(Decimal("-100"), 1) == 1
        assert drinks_for(Decimal("-100"), 5) == 5
        assert drinks_for(Decimal("-1000"), 5) == MAX_DRINKS_PER_ROUND

    def test_settlement_hands_out_drinks_in_drinks_mode(self):
        room, (a, b, c) = make_room()
        room.configure(drinks=True, drink_strength=2)
        advance_to(room, Phase.TRADING)
        # The answer is 100: a buys at 200 and loses 100 ln 2 = 69 points, which b gains.
        room.place_order(b, Side.SELL, Decimal(200), 1)
        room.place_order(a, Side.BUY, Decimal(200), 1)
        room.advance()
        assert room.phase is Phase.REVEAL
        assert view(room.snapshot(), a).drinks == 1
        assert view(room.snapshot(), b).drinks == 0
        assert view(room.snapshot(), c).drinks == 0
        advance_to(room, Phase.QUOTING)
        assert view(room.snapshot(), a).drinks is None  # a new round, nothing settled yet
        assert view(room.snapshot(), a).drinks_total == 1

    def test_drinks_are_off_by_default(self):
        room, (a, _, _) = make_room()
        advance_to(room, Phase.REVEAL)
        assert view(room.snapshot(), a).drinks is None
        assert view(room.snapshot(), a).drinks_total == 0

    def test_a_phone_sees_the_leaders_and_itself_but_the_host_sees_everyone(self):
        room, seated = make_room(players=15)
        for index, player in enumerate(seated):
            player.total_points = Decimal(index)  # P14 leads, P0 is last
        base = room.snapshot()
        assert len(base.players) == 15 and base.player_count == 15 and base.you is None
        ranked = sorted(base.players, key=lambda view: view.total_points, reverse=True)
        leaders = ranked[:10]
        last = room.view_for(seated[0], base, leaders)
        assert [view.id for view in last.players][:10] == [view.id for view in leaders]
        assert last.players[-1].id == seated[0].id and len(last.players) == 11
        assert last.you.player_id == seated[0].id and last.player_count == 15
        leader = room.view_for(seated[14], base, leaders)
        assert len(leader.players) == 10 and leader.players[0].id == seated[14].id

    def test_rounds_timers_and_limits_change_from_the_drawer(self):
        room, (a, _, _) = make_room(rounds=3)
        room.configure(rounds=5)
        assert len(room.questions) == 5
        small = Room("WXYZ", RoomConfig(rounds=3), QUESTIONS[:4], Clock())
        with pytest.raises(RoomError) as short:
            small.configure(rounds=5)
        assert short.value.code == "not_enough_questions"
        room.configure(timers={"question": 10, "quoting": 40})
        room.configure(timers={"trading": 60})
        assert (room.config.timers.question, room.config.timers.quoting, room.config.timers.trading) == (10, 40, 60)
        assert room.config.timers.reveal == 10  # untouched
        room.configure(hint_seconds_left=0, position_limit=2)
        room.start()
        assert room.timer_ends_at == room.clock() + 10 * 1000
        room.advance()
        room.advance()  # TRADING with no hint
        assert room.hint_at is None
        room.place_order(a, Side.BUY, Decimal(90), 2)
        with pytest.raises(PositionLimitError):
            room.place_order(a, Side.BUY, Decimal(90), 1)
        with pytest.raises(RoomError) as started:
            room.configure(rounds=4)
        assert started.value.code == "wrong_phase"

    def test_the_host_can_cap_the_seats(self):
        room, _ = make_room(players=3)
        room.configure(max_players=3)
        assert error_code(room.join, "Late") == "room_full"
        room.configure(max_players=4)
        room.join("Late")

    def test_chosen_categories_come_first_and_the_rest_pad(self):
        bank = [make_question(i, category="food") for i in range(3)]
        bank += [make_question(i, category="sports") for i in range(3, 13)]
        picked = pick_questions(bank, 7, random.Random(1), categories=["food"])
        assert [q.category for q in picked[:3]] == ["food"] * 3
        assert len({q.id for q in picked}) == 7
        room = Room("ABCD", RoomConfig(rounds=3), bank, Clock())
        room.configure(categories=["food"])
        assert all(q.category == "food" for q in room.questions)
        room.configure(categories=[])  # none ticked means all of them
        assert len(room.questions) == 3

    def test_bots_take_seats_and_ids_never_repeat(self):
        room, _ = make_room()
        room.set_bots(3, level=3)
        bots = [p for p in room.players if p.is_bot]
        assert [p.name for p in bots] == ["Bot Ada", "Bot Turing", "Bot Hopper"]
        assert all(p.connected and p.bot_level == 3 for p in bots)
        room.set_bots(1, level=1)
        assert sum(p.is_bot for p in room.players) == 1
        late = room.join("Late")
        assert len({p.id for p in room.players}) == len(room.players)
        assert late.id == "p8"
        room.set_bots(25, 2)
        assert sum(p.is_bot for p in room.players) == 20  # capped at MAX_BOTS, not refused
        room.configure(max_players=5)
        room.set_bots(10, 2)
        assert len(room.players) == 5  # seats, not bots, are the limit

    def test_bots_cannot_win_best_quote_and_show_as_bots(self):
        room, (a, _, _) = make_room()
        room.set_bots(1, level=3)
        bot = next(p for p in room.players if p.is_bot)
        advance_to(room, Phase.QUOTING)
        room.submit_quote(bot, Decimal(99), Decimal(101))
        room.submit_quote(a, Decimal(80), Decimal(120))
        advance_to(room, Phase.REVEAL)
        assert room.best.player_id == a.id
        assert view(room.snapshot(), bot).bot is True
        assert view(room.snapshot(), a).bot is False
        assert all(result.name != bot.name for result in room.results())

    def test_bot_quotes_and_orders_are_on_tick_and_sane(self):
        rng = random.Random(0)
        tick = Decimal("0.5")
        for level in (1, 2, 3):
            for _ in range(50):
                bid, ask = bot_quote(level, Decimal(100), tick, rng)
                assert Decimal(0) < bid < ask
                assert bid % tick == 0 and ask % tick == 0
        side, price, size = bot_order(2, Decimal(100), BookSnapshot(bids=[], asks=[]), tick, rng)
        assert side in (Side.BUY, Side.SELL) and price > 0 and 1 <= size <= 2

    def test_hard_bots_quote_tighter_than_easy_ones(self):
        rng = random.Random(1)
        errors = {}
        for level in (1, 3):
            mids = [bot_quote(level, Decimal(1000), Decimal(1), rng) for _ in range(200)]
            errors[level] = sum(abs(math.log(float(b * a) ** 0.5 / 1000)) for b, a in mids) / 200
        assert errors[3] < errors[1] / 2

    def test_play_again_keeps_the_seats_and_resets_the_rest(self):
        room, (a, b, c) = make_room(rounds=3)
        assert error_code(room.restart) == "wrong_phase"
        advance_to(room, Phase.TRADING)
        room.place_order(a, Side.SELL, Decimal(200), 1)
        room.place_order(b, Side.BUY, Decimal(200), 1)
        advance_to(room, Phase.GAME_OVER)
        assert a.total_points != 0
        room.restart()
        assert room.phase is Phase.LOBBY and room.round_no == 0 and room.timer_ends_at is None
        assert [p.id for p in room.players] == [a.id, b.id, c.id]
        assert all(p.total_points == 0 and p.round_points is None for p in room.players)
        assert room.rounds_scored == 0 and room.quote_log == [] and room.recorded is False
        room.start()
        assert (room.round_no, room.phase) == (1, Phase.QUESTION)

    def test_signed_in_quotes_are_logged_for_anti_cheat(self):
        room, (a, b, _) = make_room()
        a.user_id = 7
        advance_to(room, Phase.QUOTING)
        room.submit_quote(a, Decimal(50), Decimal(200))
        room.submit_quote(b, Decimal(90), Decimal(110))
        advance_to(room, Phase.REVEAL)
        log = room.quote_log
        assert [(record.user_id, record.name) for record in log] == [(7, "P0"), (None, "P1")]
        assert abs(log[0].mid_error) < 1e-9  # sqrt(50 * 200) is exactly the answer, 100
        assert log[1].fills == 0 and log[1].answer == 100

    def test_you_lists_your_own_fills_from_your_side(self):
        room = Room("ABCD", RoomConfig(rounds=3), QUESTIONS, Clock())
        a, b, c = room.join("A"), room.join("B"), room.join("C")
        advance_to(room, Phase.TRADING)
        room.place_order(a, Side.SELL, Decimal(60), 2)
        room.place_order(b, Side.BUY, Decimal(60), 1)
        mine = room.snapshot(a).you.fills
        assert [(f.side, f.size, f.counterparty) for f in mine] == [(Side.SELL, 1, "B")]
        theirs = room.snapshot(b).you.fills
        assert [(f.side, f.price, f.counterparty) for f in theirs] == [(Side.BUY, Decimal(60), "A")]
        assert room.snapshot(c).you.fills == []

    def test_scoring_mode_comes_from_config(self):
        room = Room("ABCD", RoomConfig(rounds=3, scoring="linear"), QUESTIONS, Clock())
        a, b = room.join("A"), room.join("B")
        advance_to(room, Phase.TRADING)
        room.place_order(a, Side.SELL, Decimal(60), 2)
        room.place_order(b, Side.BUY, Decimal(60), 2)
        advance_to(room, Phase.REVEAL)
        assert view(room.snapshot(), b).round_points == 80


class TestHint:
    def test_hint_is_scheduled_fifteen_seconds_before_trading_ends(self):
        room, _ = make_room()
        advance_to(room, Phase.TRADING)
        assert room.next_event_at == room.timer_ends_at - 15_000
        assert room.snapshot().hint is None

    def test_the_first_timer_reveals_the_hint_without_ending_trading(self):
        room, _ = make_room()
        advance_to(room, Phase.TRADING)
        before = room.transitions
        room.on_timer()
        assert room.phase is Phase.TRADING
        assert room.transitions == before + 1
        hint = room.snapshot().hint
        assert hint.low < 100 < hint.high
        assert room.next_event_at == room.timer_ends_at

    def test_the_next_timer_ends_trading_and_the_hint_stays_through_the_round(self):
        room, _ = make_room()
        advance_to(room, Phase.TRADING)
        room.on_timer()
        room.on_timer()
        assert room.phase is Phase.REVEAL
        assert room.snapshot().hint is not None

    def test_skipping_ahead_before_the_hint_ends_trading(self):
        room, _ = make_room()
        advance_to(room, Phase.TRADING)
        room.advance()
        assert room.phase is Phase.REVEAL
        assert room.snapshot().hint is None

    def test_each_round_gets_a_fresh_hint(self):
        room, _ = make_room()
        advance_to(room, Phase.TRADING)
        room.on_timer()
        advance_to(room, Phase.QUESTION)
        assert room.snapshot().hint is None

    def test_a_short_trading_phase_gets_its_hint_at_once(self):
        timers = Timers(trading=10)
        room = Room("ABCD", RoomConfig(rounds=3, timers=timers), QUESTIONS, Clock())
        room.join("A"), room.join("B")
        advance_to(room, Phase.TRADING)
        assert room.next_event_at == room.clock()

    def test_hints_can_be_turned_off(self):
        room = Room("ABCD", RoomConfig(rounds=3, hint_seconds_left=0), QUESTIONS, Clock())
        room.join("A"), room.join("B")
        advance_to(room, Phase.TRADING)
        assert room.next_event_at == room.timer_ends_at
        room.on_timer()
        assert room.phase is Phase.REVEAL

    @pytest.mark.parametrize(
        "answer",
        ["0.49", "1", "7", "11", "27", "42.195", "164.8", "828", "8848.86", "6779", "1280", "384400"],
    )
    def test_the_range_always_contains_the_answer_off_center(self, answer):
        rng = random.Random(answer)
        for _ in range(200):
            hint = make_hint(Decimal(answer), rng)
            assert 0 < hint.low < Decimal(answer) < hint.high
            assert hint.high / hint.low <= Decimal("2.5")

    def test_the_answer_lands_in_different_parts_of_the_range(self):
        rng = random.Random(1)
        spots = set()
        for _ in range(50):
            hint = make_hint(Decimal(828), rng)
            spots.add(round(math.log(828 / float(hint.low)) / math.log(float(hint.high / hint.low)), 1))
        assert len(spots) > 3

    @pytest.mark.parametrize("answer", ["0.49", "42.195", "828", "384400"])
    def test_bounds_are_round_numbers_in_plain_digits(self, answer):
        hint = make_hint(Decimal(answer), random.Random(3))
        for bound in (str(hint.low), str(hint.high)):
            assert "E" not in bound
            assert len(bound.replace(".", "").strip("0")) <= 2


CASE = dict(
    kind="case",
    context="A shop sold 40 widgets a day in 2025.",
    context_source_url="https://example.com/shop",
    context_source_quote="sold 40 widgets a day",
    hint_text="Its busiest rival sold 250 that year.",
    hint_source_url="https://example.com/rival",
    hint_source_quote="sold 250 widgets",
)


def case_room(**config):
    cases = [make_question(i).model_copy(update=CASE) for i in range(5)]
    room = Room("ABCD", RoomConfig(rounds=3, **config), cases, Clock())
    room.join("A"), room.join("B")
    return room


class TestCaseQuestions:
    def test_a_case_question_gets_longer_to_read_and_to_trade(self):
        room = case_room()
        advance_to(room, Phase.QUESTION)
        assert room.timer_ends_at - room.clock() == 15_000
        assert room.snapshot().phase_seconds == 15
        advance_to(room, Phase.QUOTING)
        assert room.timer_ends_at - room.clock() == 20_000
        advance_to(room, Phase.TRADING)
        assert room.timer_ends_at - room.clock() == 75_000
        assert room.snapshot().phase_seconds == 75

    def test_a_plain_question_keeps_the_plain_timers(self):
        room, _ = make_room()
        advance_to(room, Phase.QUESTION)
        assert room.snapshot().phase_seconds == 5
        advance_to(room, Phase.TRADING)
        assert room.timer_ends_at - room.clock() == 45_000

    def test_the_host_can_change_the_case_timers(self):
        room = case_room()
        room.configure(timers=Timers(case_trading=120).model_dump(include={"case_trading"}))
        advance_to(room, Phase.TRADING)
        assert room.timer_ends_at - room.clock() == 120_000
        assert room.config.timers.trading == 45

    def test_the_setup_is_shown_with_the_question_from_the_start(self):
        room = case_room()
        advance_to(room, Phase.QUESTION)
        question = room.snapshot().question
        assert question.kind == "case"
        assert question.context == CASE["context"]
        assert question.answer is None

    def test_a_plain_question_has_no_setup(self):
        room, _ = make_room()
        advance_to(room, Phase.QUESTION)
        question = room.snapshot().question
        assert (question.kind, question.context) == ("standard", None)

    def test_the_hint_is_the_question_s_own_figure_not_a_range(self):
        room = case_room()
        advance_to(room, Phase.TRADING)
        assert room.snapshot().hint is None
        room.on_timer()
        hint = room.snapshot().hint
        assert hint.text == CASE["hint_text"]
        assert (hint.low, hint.high) == (None, None)
        assert room.phase is Phase.TRADING

    def test_the_hint_comes_at_the_same_point_of_the_longer_round(self):
        room = case_room()
        advance_to(room, Phase.TRADING)
        assert room.snapshot().hint_at == room.timer_ends_at - 25_000
        room.on_timer()
        assert room.snapshot().hint_at is None  # nothing more to wait for

    def test_a_shorter_case_round_never_brings_the_hint_later_than_usual(self):
        room = case_room(timers=Timers(case_trading=30))
        advance_to(room, Phase.TRADING)
        assert room.snapshot().hint_at == room.timer_ends_at - 15_000

    def test_hints_off_means_no_case_hint_either(self):
        room = case_room(hint_seconds_left=0)
        advance_to(room, Phase.TRADING)
        assert room.snapshot().hint_at is None
        room.on_timer()
        assert room.phase is Phase.REVEAL

    def test_a_plain_hint_still_says_when_it_is_due(self):
        room, _ = make_room()
        advance_to(room, Phase.TRADING)
        assert room.snapshot().hint_at == room.timer_ends_at - 15_000

    def test_a_case_question_needs_its_setup_hint_and_sources(self):
        bare = make_question(1).model_copy(update={"kind": "case", "context": "Some setup."})
        assert check_bank([bare]) == [
            "q1: case question without context_source_url, context_source_quote, hint_text, "
            "hint_source_url, hint_source_quote"
        ]
        assert check_bank([make_question(1).model_copy(update=CASE)]) == []

    def test_a_plain_question_cannot_carry_a_case_s_fields(self):
        stray = make_question(1).model_copy(update={"hint_text": "A figure."})
        assert check_bank([stray]) == ["q1: hint_text on a question that isn't a case"]


def case_question(index, words):
    """A case question whose setup runs `words` words, so its reading time is known."""
    setup = " ".join(["word"] * words)
    return make_question(index).model_copy(update={**CASE, "context": setup})


MIXED_BANK = [make_question(i) for i in range(20)] + [case_question(100 + i, 5 + 3 * i) for i in range(8)]


class TestCaseModes:
    def test_default_puts_three_case_questions_last_longest_last(self):
        for seed in range(20):
            picked = pick_questions(MIXED_BANK, 7, random.Random(seed), case_mode="default")
            assert [q.kind for q in picked] == ["standard"] * 4 + ["case"] * 3
            times = [reading_seconds(q) for q in picked[4:]]
            assert times == sorted(times)

    def test_off_never_draws_a_case_question(self):
        for seed in range(20):
            picked = pick_questions(MIXED_BANK, 7, random.Random(seed), case_mode="off")
            assert len(picked) == 7 and all(q.kind == "standard" for q in picked)

    def test_extra_lets_case_questions_land_anywhere_in_reading_order(self):
        early = False
        for seed in range(40):
            picked = pick_questions(MIXED_BANK, 7, random.Random(seed), case_mode="extra")
            cases = [q for q in picked if q.kind == "case"]
            assert [reading_seconds(q) for q in cases] == sorted(reading_seconds(q) for q in cases)
            early |= any(q.kind == "case" for q in picked[:4])
        assert early

    def test_default_falls_back_to_more_cases_when_standard_questions_run_out(self):
        bank = [make_question(i) for i in range(2)] + [case_question(100 + i, 5 + i) for i in range(6)]
        picked = pick_questions(bank, 7, random.Random(0), case_mode="default")
        assert [q.kind for q in picked] == ["standard"] * 2 + ["case"] * 5

    def test_reading_time_counts_words_and_the_setup_s_figures(self):
        plain = case_question(1, 7).model_copy(update={"text": "How many?"})
        figures = plain.model_copy(update={"context": "It sold 40 in 2025 and 7."})
        assert reading_seconds(plain) == pytest.approx(9 / 3.5)  # 7 words of setup, 2 of question
        assert reading_seconds(figures) == pytest.approx(9 / 3.5 + 3)  # and 3 figures

    def test_case_rounds_rise_from_one_and_a_half_to_two_and_a_half(self):
        questions = [make_question(i) for i in range(4)] + [case_question(100 + i, 5) for i in range(3)]
        assert round_multipliers(questions) == [1, 1, 1, 1, Decimal("1.5"), Decimal("2.0"), Decimal("2.5")]
        five = [case_question(100 + i, 5) for i in range(5)]
        assert round_multipliers(five) == [Decimal(m) for m in ("1.5", "1.8", "2.0", "2.3", "2.5")]
        assert round_multipliers([make_question(1), case_question(100, 5)]) == [1, Decimal("2.0")]
        assert round_multipliers(QUESTIONS[:3]) == [1, 1, 1]

    def test_a_case_round_pays_its_multiplier(self):
        room = Room("ABCD", RoomConfig(rounds=7), MIXED_BANK, Clock())
        a, b = room.join("A"), room.join("B")
        room.start()
        while room.round_no < 7:
            room.skip_round()
            room.advance()
        assert room.snapshot().question.multiplier == Decimal("2.5")
        advance_to(room, Phase.TRADING)
        room.place_order(a, Side.SELL, Decimal(50), 1)
        room.place_order(b, Side.BUY, Decimal(50), 1)
        advance_to(room, Phase.REVEAL)
        assert view(room.snapshot(), b).round_points == Decimal("173.29")  # 2.5 x 100 ln 2
        assert room.game_fills[-1].buyer_points == Decimal("173.29")

    def test_a_standard_round_is_worth_one(self):
        room = Room("ABCD", RoomConfig(rounds=7), MIXED_BANK, Clock())
        room.join("A"), room.join("B")
        advance_to(room, Phase.QUESTION)
        assert room.snapshot().question.multiplier == 1

    def test_the_switch_redraws_in_the_lobby_and_is_locked_after(self):
        room = Room("ABCD", RoomConfig(rounds=7), MIXED_BANK, Clock())
        room.join("A"), room.join("B")
        assert sum(q.kind == "case" for q in room.questions) == 3
        room.configure(case_mode="off")
        assert not any(q.kind == "case" for q in room.questions)
        room.start()
        with pytest.raises(RoomError) as caught:
            room.configure(case_mode="extra")
        assert caught.value.code == "wrong_phase"

    def test_off_is_refused_when_the_bank_would_be_too_small(self):
        bank = [make_question(i) for i in range(2)] + [case_question(100 + i, 5) for i in range(6)]
        room = Room("ABCD", RoomConfig(rounds=7), bank, Clock())
        with pytest.raises(RoomError) as caught:
            room.configure(case_mode="off")
        assert caught.value.code == "not_enough_questions"

    def test_the_default_mode_is_default(self):
        assert RoomConfig().case_mode == "default"


class TestSavedResults:
    def seated(self):
        room = Room("ABCD", RoomConfig(rounds=3), QUESTIONS, Clock())
        a = room.join("", user={"id": 11, "name": "Ann"})
        b = room.join("Ben", user={"id": 12, "name": "Benjamin"})
        guest = room.join("Guest")
        return room, a, b, guest

    def test_accounts_link_to_seats_and_names_default_to_the_account(self):
        room, a, b, guest = self.seated()
        assert (a.user_id, a.name) == (11, "Ann")
        assert (b.user_id, b.name) == (12, "Ben")
        assert guest.user_id is None
        assert [p.signed_in for p in room.snapshot().players] == [True, True, False]

    def test_long_account_names_are_trimmed_to_fit(self):
        room = Room("ABCD", RoomConfig(rounds=3), QUESTIONS, Clock())
        player = room.join("", user={"id": 1, "name": "Bartholomew Fitzgerald"})
        assert player.name == "Bartholomew Fitz"

    def test_an_account_reclaims_its_seat_mid_game(self):
        room, a, _, _ = self.seated()
        advance_to(room, Phase.TRADING)
        assert room.join("Anyone", user={"id": 11, "name": "Ann"}) is a
        newcomer = room.join("New", None, {"id": 99, "name": "New"})  # a new account joins late
        assert newcomer.user_id == 99 and newcomer.plays_from == room.round_no + 1

    def test_results_rank_everyone_and_count_what_happened(self):
        room, a, b, guest = self.seated()
        advance_to(room, Phase.QUOTING)
        room.submit_quote(a, Decimal(95), Decimal(105))
        advance_to(room, Phase.TRADING)
        # Inside Ann's 95/105 spread, so her resting quote stays out of it.
        room.place_order(guest, Side.SELL, Decimal(98), 1)
        room.place_order(b, Side.BUY, Decimal(98), 1)
        advance_to(room, Phase.SCORES)
        results = {result.user_id: result for result in room.results()}
        assert set(results) == {11, 12}
        assert results[11].rank == 1 and results[11].best_quotes == 1 and results[11].trades == 0
        assert results[11].positive_points == Decimal("25.00")
        assert results[12].rank == 2 and results[12].trades == 1
        assert results[12].positive_points == Decimal("2.02")

    def test_ties_share_a_rank(self):
        room, a, b, _ = self.seated()
        advance_to(room, Phase.SCORES)
        assert {r.user_id: r.rank for r in room.results()} == {11: 1, 12: 1}

    def test_positive_points_only_count_winning_rounds(self):
        room, a, b, guest = self.seated()
        for prices in ((50, 200), (200, 50)):
            advance_to(room, Phase.TRADING)
            room.place_order(guest, Side.SELL, Decimal(prices[0]), 1)
            room.place_order(a, Side.BUY, Decimal(prices[0]), 1)
            advance_to(room, Phase.SCORES)
            if room.round_no < 2:
                room.advance()
        [result] = [r for r in room.results() if r.user_id == 11]
        assert result.points == Decimal("0.00")
        assert result.positive_points == Decimal("69.31")

    def test_save_game_pays_coins_and_tells_the_player(self, tmp_path):
        from server.db import Database

        db = Database(tmp_path / "t.db")
        ann, _ = db.sign_in_google("g1", "ann@example.com", "Ann")
        room = Room("ABCD", RoomConfig(rounds=3), QUESTIONS, Clock())
        player = room.join("", user=ann)
        room.join("Guest")
        advance_to(room, Phase.GAME_OVER)
        save_game(db, room)
        assert player.coins_awarded == 70
        assert room.snapshot(player).you.coins_awarded == 70
        assert db.profile(ann["id"])["games"] == 1

    def test_a_game_that_never_scored_is_not_saved(self, tmp_path):
        from server.db import Database

        db = Database(tmp_path / "t.db")
        ann, _ = db.sign_in_google("g1", "ann@example.com", "Ann")
        room = Room("ABCD", RoomConfig(rounds=3), QUESTIONS, Clock())
        room.join("", user=ann)
        room.join("Guest")
        room.start()
        room.end()
        save_game(db, room)
        assert db.profile(ann["id"])["games"] == 0

    def test_the_hub_saves_a_game_once(self):
        saved = []
        hub = Hub(QUESTIONS, Clock(), on_game_over=saved.append)
        room = hub._create_room(RoomConfig(rounds=3))
        room.join("A"), room.join("B")
        advance_to(room, Phase.GAME_OVER)
        asyncio.run(hub.publish(room))
        asyncio.run(hub.publish(room))
        assert saved == [room]


class TestQuestionBank:
    def test_only_verified_questions_are_servable(self):
        verified = make_question(1)
        unverified = make_question(2, status="unverified")
        assert servable([verified, unverified]) == [verified]

    def test_unanswered_questions_are_never_servable(self):
        draft = make_question(1, answer=None, status="unverified")
        assert servable([draft], allow_unverified=True) == []

    def test_verified_needs_answer_and_source(self):
        question = make_question(1, answer=None)
        assert check_bank([question]) == ["q1: verified without answer"]

    def test_duplicate_ids_are_caught(self):
        assert check_bank([make_question(1), make_question(1)]) == ["q1: duplicate id"]

    def test_the_real_bank_is_well_formed(self):
        questions = load_bank()
        assert check_bank(questions) == []
        for question in questions:
            assert question.answer is None or question.answer > 0
            assert 0 < question.tick


FAST = Timers(question=0.01, quoting=0.01, trading=0.01, reveal=0.01, scores=0.01)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module.hub, "questions", QUESTIONS)
    monkeypatch.setattr(app_module.hub, "publish_interval", 0)  # every snapshot, in order
    app_module.hub.rooms.clear()
    with TestClient(app_module.app) as test_client:
        yield test_client


def receive_until(socket, predicate):
    while True:
        message = socket.receive_json()
        if predicate(message):
            return message


def host_room(socket, config=None):
    socket.send_json({"type": "host_create", "config": config or {}})
    hosted = receive_until(socket, lambda m: m["type"] == "hosted")
    return hosted["room_code"], hosted["token"]


def join(socket, code, name, token=None):
    socket.send_json({"type": "join", "room_code": code, "name": name, "token": token})
    return receive_until(socket, lambda m: m["type"] == "joined")


def has_error(code):
    return lambda m: m["type"] == "error" and m["code"] == code


class TestWebSocket:
    def test_room_code_is_a_word_from_the_list(self, client):
        with client.websocket_connect("/ws") as host:
            code, _ = host_room(host)
        assert code in ROOM_WORDS

    def test_the_word_list_is_clean(self):
        assert len(set(ROOM_WORDS)) == len(ROOM_WORDS)
        assert all(len(word) == 4 and word.isascii() and word.isupper() for word in ROOM_WORDS)

    def test_rooms_never_share_a_code(self, client):
        for word in ROOM_WORDS[1:]:
            app_module.hub.rooms[word] = SimpleNamespace(empty_since=None)
        with client.websocket_connect("/ws") as host:
            assert host_room(host)[0] == ROOM_WORDS[0]

    def test_codes_fall_back_to_clear_letters_when_every_word_is_taken(self, client):
        for word in ROOM_WORDS:
            app_module.hub.rooms[word] = SimpleNamespace(empty_since=None)
        with client.websocket_connect("/ws") as host:
            code, _ = host_room(host)
        assert code not in ROOM_WORDS
        assert len(code) == 4
        assert set(code) <= set(ROOM_CODE_ALPHABET)

    @pytest.mark.parametrize(
        "raw",
        [
            "not json",
            "{}",
            '{"type": "nonsense"}',
            '{"type": "place_order", "side": "HOLD", "price": "1", "size": 1}',
            '{"type": "place_order", "side": "BUY", "price": "NaN", "size": 1}',
            '{"type": "place_order", "side": "BUY", "price": "1", "size": 6}',
        ],
    )
    def test_malformed_messages_get_an_error_and_the_socket_lives(self, client, raw):
        with client.websocket_connect("/ws") as socket:
            socket.send_text(raw)
            assert socket.receive_json()["code"] == "bad_message"
            socket.send_bytes(b"\xff")
            assert socket.receive_json()["code"] == "bad_message"
            host_room(socket)

    def test_unknown_room_is_an_error(self, client):
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"type": "join", "room_code": "ZZZZ", "name": "Sam"})
            assert socket.receive_json()["code"] == "room_not_found"

    def test_room_codes_are_case_insensitive(self, client):
        with client.websocket_connect("/ws") as host, client.websocket_connect("/ws") as player:
            code, _ = host_room(host)
            assert join(player, code.lower(), "Sam")["room_code"] == code

    def test_players_cannot_use_host_controls(self, client):
        with client.websocket_connect("/ws") as host, client.websocket_connect("/ws") as player:
            code, _ = host_room(host)
            join(player, code, "Sam")
            player.send_json({"type": "host_start"})
            receive_until(player, has_error("not_host"))

    def test_host_screen_gets_no_you(self, client):
        with client.websocket_connect("/ws") as host:
            host_room(host)
            assert receive_until(host, lambda m: m["type"] == "state")["you"] is None

    def test_too_few_verified_questions_stops_the_room(self, client, monkeypatch):
        monkeypatch.setattr(app_module.hub, "questions", QUESTIONS[:2])
        with client.websocket_connect("/ws") as host:
            host.send_json({"type": "host_create", "config": {}})
            assert host.receive_json()["code"] == "not_enough_questions"

    def test_a_socket_whose_seat_moves_elsewhere_is_told_first(self, client):
        with client.websocket_connect("/ws") as host, client.websocket_connect("/ws") as phone:
            code, host_token = host_room(host)
            seat = join(phone, code, "A")
            with client.websocket_connect("/ws") as tablet:
                tablet.send_json({"type": "join", "room_code": code, "name": "A", "token": seat["token"]})
                receive_until(tablet, lambda m: m["type"] == "joined")
                told = receive_until(phone, lambda m: m["type"] == "error")
                assert told["code"] == "replaced"
                with pytest.raises(WebSocketDisconnect):
                    phone.receive_json()
            with client.websocket_connect("/ws") as screen:
                screen.send_json({"type": "host_resume", "room_code": code, "token": host_token})
                receive_until(screen, lambda m: m["type"] == "hosted")
                assert receive_until(host, lambda m: m["type"] == "error")["code"] == "replaced"

    def test_dropping_marks_disconnected_and_token_reclaims_the_seat(self, client):
        with client.websocket_connect("/ws") as host:
            code, _ = host_room(host)
            with client.websocket_connect("/ws") as phone:
                joined = join(phone, code, "Sam")
            state = receive_until(
                host,
                lambda m: m["type"] == "state"
                and m["players"]
                and not m["players"][0]["connected"],
            )
            assert state["players"][0]["name"] == "Sam"
            with client.websocket_connect("/ws") as phone:
                again = join(phone, code, "Sam", joined["token"])
            assert again["player_id"] == joined["player_id"]

    def test_only_the_host_changes_the_recall_setting(self, client):
        with client.websocket_connect("/ws") as host, client.websocket_connect("/ws") as a:
            code, _ = host_room(host)
            assert receive_until(host, lambda m: m["type"] == "state")["config"]["recall_on_start"] is True
            join(a, code, "A")
            host.send_json({"type": "host_configure", "recall_on_start": False})
            state = receive_until(a, lambda m: m["type"] == "state" and not m["config"]["recall_on_start"])
            assert state["config"]["recall_on_start"] is False
            host.send_json({"type": "host_configure", "drinks": True, "drink_strength": 4})
            state = receive_until(a, lambda m: m["type"] == "state" and m["config"]["drinks"])
            assert state["config"]["drink_strength"] == 4
            assert state["config"]["recall_on_start"] is False  # a field left out stays put
            host.send_json({"type": "host_configure", "drink_strength": 9})
            assert receive_until(host, lambda m: m["type"] == "error")["code"] == "bad_message"
            a.send_json({"type": "host_configure", "recall_on_start": True})
            assert receive_until(a, lambda m: m["type"] == "error")["code"] == "not_host"

    def test_host_can_resume_with_its_token(self, client):
        with client.websocket_connect("/ws") as host:
            code, token = host_room(host)
        with client.websocket_connect("/ws") as host:
            host.send_json({"type": "host_resume", "room_code": code, "token": token})
            assert receive_until(host, lambda m: m["type"] == "hosted")["room_code"] == code
        with client.websocket_connect("/ws") as stranger:
            stranger.send_json({"type": "host_resume", "room_code": code, "token": "wrong"})
            assert stranger.receive_json()["code"] == "not_host"

    def test_host_advance_skips_the_timer(self, client):
        config = {"timers": {"question": 600}}
        with client.websocket_connect("/ws") as host, client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            code, _ = host_room(host, config)
            join(a, code, "A")
            join(b, code, "B")
            host.send_json({"type": "host_start"})
            receive_until(host, lambda m: m.get("phase") == "QUESTION")
            host.send_json({"type": "host_advance"})
            receive_until(host, lambda m: m.get("phase") == "QUOTING")

    def test_the_hint_arrives_over_the_socket_during_trading(self, client):
        timers = {"question": 600, "quoting": 600, "trading": 0.3, "reveal": 600, "scores": 600}
        config = {"timers": timers, "hint_seconds_left": 0.2}
        with client.websocket_connect("/ws") as host, client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            code, _ = host_room(host, config)
            join(a, code, "A")
            join(b, code, "B")
            host.send_json({"type": "host_start"})
            host.send_json({"type": "host_advance"})
            receive_until(host, lambda m: m.get("phase") == "QUOTING")
            host.send_json({"type": "host_advance"})
            hinted = receive_until(a, lambda m: m.get("phase") == "TRADING" and m["hint"])
            assert float(hinted["hint"]["low"]) < 100 < float(hinted["hint"]["high"])
            receive_until(host, lambda m: m.get("phase") == "REVEAL")

    def test_timers_drive_a_whole_game_to_game_over(self, client):
        config = {"rounds": 3, "timers": FAST.model_dump()}
        with client.websocket_connect("/ws") as host, client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            code, _ = host_room(host, config)
            join(a, code, "A")
            join(b, code, "B")
            host.send_json({"type": "host_start"})
            final = receive_until(host, lambda m: m.get("phase") == "GAME_OVER")
            assert final["round_no"] == 3
            assert final["timer_ends_at"] is None

    def test_a_played_round_over_sockets(self, client):
        slow = {"question": 600, "quoting": 600, "trading": 600, "reveal": 600, "scores": 600}
        with client.websocket_connect("/ws") as host, client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            code, _ = host_room(host, {"timers": slow})
            join(a, code, "A")
            join(b, code, "B")
            host.send_json({"type": "host_start"})
            host.send_json({"type": "host_advance"})
            receive_until(host, lambda m: m.get("phase") == "QUOTING")

            a.send_json({"type": "submit_quote", "bid": "90", "ask": "110"})
            receive_until(host, lambda m: m.get("players") and m["players"][0]["quoted"])
            host.send_json({"type": "host_advance"})
            receive_until(host, lambda m: m.get("phase") == "TRADING")

            b.send_json({"type": "place_order", "side": "BUY", "price": "110", "size": 1})
            state = receive_until(b, lambda m: m["type"] == "state" and m["tape"])
            assert state["you"]["position"] == 1
            assert state["tape"][0]["price"] == "110"

            host.send_json({"type": "host_advance"})
            reveal = receive_until(a, lambda m: m.get("phase") == "REVEAL")
            assert reveal["question"]["answer"] == "100"
            assert reveal["best_quote"]["name"] == "A"
            assert reveal["you"]["round_points"] == str(Decimal("34.53"))


class TestSkipQuestion:
    def test_skipping_settles_the_question_and_lands_on_its_scores(self):
        room, (a, b, c) = make_room()
        advance_to(room, Phase.QUOTING)
        room.submit_quote(a, Decimal(90), Decimal(110))
        room.submit_quote(b, Decimal(120), Decimal(130))
        room.skip_round()
        assert room.phase is Phase.SCORES
        assert room.round_no == 1
        assert room.timer_ends_at == room.clock() + 10 * 1000
        # The crossing quotes still filled at the open and settled against the answer (100).
        [fill] = room.fills
        assert (fill.buyer_id, fill.seller_id) == (b.id, a.id)
        snapshot = room.snapshot(a)
        assert Decimal(snapshot.you.round_points) > 0
        assert Decimal(view(snapshot, b).round_points) < 0

    def test_skipping_from_the_question_scores_nothing(self):
        room, players = make_room()
        advance_to(room, Phase.QUESTION)
        room.skip_round()
        assert room.phase is Phase.SCORES and room.fills == []
        assert all(Decimal(view(room.snapshot(players[0]), p).round_points) == 0 for p in players)

    def test_the_next_round_follows_as_usual(self):
        room, _ = make_room(rounds=3)
        advance_to(room, Phase.TRADING)
        room.skip_round()
        room.advance()
        assert (room.round_no, room.phase) == (2, Phase.QUESTION)

    @pytest.mark.parametrize("phase", [Phase.LOBBY, Phase.SCORES, Phase.GAME_OVER])
    def test_there_is_nothing_to_skip_outside_a_question(self, phase):
        room, _ = make_room()
        if phase is not Phase.LOBBY:
            advance_to(room, phase)
        assert error_code(room.skip_round) == "wrong_phase"

    def test_the_host_skips_over_the_socket(self, client):
        config = {"timers": {"question": 600, "quoting": 600, "trading": 600}}
        with client.websocket_connect("/ws") as host, client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            code, _ = host_room(host, config)
            join(a, code, "A")
            join(b, code, "B")
            host.send_json({"type": "host_start"})
            receive_until(host, lambda m: m.get("phase") == "QUESTION")
            host.send_json({"type": "host_skip_round"})
            scored = receive_until(a, lambda m: m.get("phase") == "SCORES")
            assert scored["round_no"] == 1
            a.send_json({"type": "host_skip_round"})
            assert receive_until(a, has_error("not_host"))

class TestGameAwards:
    def test_awards_name_the_leaders_once_the_game_is_over(self):
        room, (a, b, c) = make_room(rounds=3)
        room.start()
        assert room.awards() == []
        while room.phase is not Phase.GAME_OVER:
            if room.phase is Phase.QUOTING:
                room.submit_quote(a, Decimal(99), Decimal(101))  # holds the answer: Best Quote
                room.submit_quote(b, Decimal(120), Decimal(130))  # crosses a's ask: one trade each
            room.advance()
        awards = {award.id: award for award in room.snapshot().awards}
        assert awards["best_quotes"].names == ["P0"] and awards["best_quotes"].detail == "3 Best Quotes"
        assert awards["most_trades"].winners == [a.id, b.id] and awards["most_trades"].detail == "3 trades"
        assert awards["biggest_round"].winners == [a.id]
        assert awards["biggest_round"].detail.startswith("+") and "in one round" in awards["biggest_round"].detail

    def test_an_award_nobody_earned_is_left_out(self):
        room, _ = make_room(rounds=3)
        advance_to(room, Phase.GAME_OVER)  # nobody quoted or traded
        assert room.awards() == []