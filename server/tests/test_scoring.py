from decimal import Decimal

import pytest
from pydantic import ValidationError

from server.engine.models import Fill, Order, Quote, Side
from server.engine.scoring import BEST_QUOTE_BONUS, best_quote, buyer_points, round_points


def fill(price, size=1, buyer="alice", seller="bob"):
    return Fill(
        price=Decimal(str(price)),
        size=size,
        buyer_id=buyer,
        seller_id=seller,
        buy_order_id="b",
        sell_order_id="s",
        seq=1,
    )


def quote(player, bid, ask, submitted_at=0):
    return Quote(
        player_id=player,
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        submitted_at=submitted_at,
    )


class TestLogScoring:
    def test_buying_at_half_the_truth_earns_69(self):
        assert buyer_points(fill(50), Decimal(100)) == Decimal("69.31")

    def test_buying_at_double_the_truth_loses_69(self):
        assert buyer_points(fill(200), Decimal(100)) == Decimal("-69.31")

    def test_buying_at_the_truth_scores_zero(self):
        assert buyer_points(fill(100), Decimal(100)) == 0

    def test_scales_linearly_with_size(self):
        assert buyer_points(fill(50, size=3), Decimal(100)) == Decimal("207.94")

    def test_same_ratio_scores_the_same_at_any_magnitude(self):
        small = buyer_points(fill("1.5"), Decimal(3))
        large = buyer_points(fill(1_500_000), Decimal(3_000_000))
        assert small == large

    def test_clamped_on_the_upside(self):
        assert buyer_points(fill(1), Decimal(100)) == 200

    def test_clamped_on_the_downside(self):
        assert buyer_points(fill(100), Decimal(1)) == -200

    def test_clamp_applies_per_lot_before_size(self):
        assert buyer_points(fill(1, size=3), Decimal(100)) == 600

    def test_just_inside_the_clamp_is_not_clamped(self):
        assert buyer_points(fill(1), Decimal(7)) == Decimal("194.59")


class TestLinearScoring:
    def test_is_size_times_distance(self):
        assert buyer_points(fill(40, size=2), Decimal(100), mode="linear") == 120

    def test_loses_when_buying_above_the_truth(self):
        assert buyer_points(fill(130), Decimal(100), mode="linear") == -30

    def test_is_not_clamped(self):
        assert buyer_points(fill(1), Decimal(10_000), mode="linear") == 9999


class TestBadInput:
    def test_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError):
            buyer_points(fill(10), Decimal(10), mode="quadratic")

    @pytest.mark.parametrize("answer", [0, -5])
    def test_non_positive_answer_is_rejected(self, answer):
        with pytest.raises(ValueError):
            buyer_points(fill(10), Decimal(answer))


class TestBestQuote:
    def test_no_quotes_means_no_winner(self):
        assert best_quote([], Decimal(10)) is None

    def test_no_winner_when_nobody_contains_the_answer(self):
        assert best_quote([quote("a", 1, 2), quote("b", 20, 30)], Decimal(10)) is None

    def test_tighter_containing_quote_wins(self):
        wide = quote("a", 1, 100)
        tight = quote("b", 8, 12)
        assert best_quote([wide, tight], Decimal(10)) == tight

    def test_tightness_is_a_ratio_not_a_width(self):
        narrow_ratio = quote("a", 900, 1000)  # ratio 1.11, width 100
        wide_ratio = quote("b", 500, 1000)  # ratio 2, width 500
        small_numbers = quote("c", 1, 1000)  # ratio 1000, width 999
        assert best_quote([wide_ratio, small_numbers, narrow_ratio], Decimal(950)) == narrow_ratio

    def test_tighter_quote_that_misses_does_not_win(self):
        tight_miss = quote("a", 11, 12)
        wide_hit = quote("b", 1, 100)
        assert best_quote([tight_miss, wide_hit], Decimal(10)) == wide_hit

    @pytest.mark.parametrize("answer", [8, 12])
    def test_quote_contains_its_own_endpoints(self, answer):
        q = quote("a", 8, 12)
        assert best_quote([q], Decimal(answer)) == q

    def test_tie_goes_to_the_earlier_submission(self):
        later = quote("a", 10, 20, submitted_at=200)
        earlier = quote("b", 5, 10, submitted_at=100)
        assert best_quote([later, earlier], Decimal(10)) == earlier


class TestRoundPoints:
    def test_fills_are_zero_sum_exactly(self):
        fills = [
            fill(37, size=2, buyer="a", seller="b"),
            fill(61, size=1, buyer="b", seller="c"),
            fill(13, size=5, buyer="c", seller="a"),
        ]
        points = round_points(fills, [], Decimal(29))
        assert sum(points.values()) == 0

    def test_nets_a_players_buys_and_sells(self):
        fills = [
            fill(50, buyer="a", seller="b"),
            fill(200, buyer="c", seller="a"),
        ]
        points = round_points(fills, [], Decimal(100))
        assert points == {
            "a": Decimal("138.62"),
            "b": Decimal("-69.31"),
            "c": Decimal("-69.31"),
        }

    def test_bonus_is_added_to_fill_points(self):
        points = round_points(
            [fill(50, buyer="a", seller="b")],
            [quote("a", 90, 110)],
            Decimal(100),
        )
        assert points["a"] == Decimal("69.31") + BEST_QUOTE_BONUS
        assert points["b"] == Decimal("-69.31")

    def test_bonus_is_25_and_needs_no_fills(self):
        assert round_points([], [quote("a", 90, 110)], Decimal(100)) == {"a": Decimal(25)}

    def test_no_activity_scores_nobody(self):
        assert round_points([], [], Decimal(100)) == {}

    def test_mode_is_passed_through(self):
        points = round_points([fill(40)], [], Decimal(100), mode="linear")
        assert points == {"alice": Decimal(60), "bob": Decimal(-60)}

    def test_a_case_round_multiplies_fills_and_the_bonus(self):
        points = round_points(
            [fill(50, buyer="a", seller="b")], [quote("c", 90, 110)], Decimal(100), multiplier=Decimal("2.5")
        )
        assert points == {"a": Decimal("173.29"), "b": Decimal("-173.29"), "c": Decimal("62.50")}

    def test_the_clamp_scales_with_the_multiplier(self):
        assert buyer_points(fill(1), Decimal(10_000), multiplier=Decimal(2)) == Decimal(400)

    def test_a_multiplied_round_stays_zero_sum(self):
        fills = [fill(37, size=2, buyer="a", seller="b"), fill(13, size=5, buyer="c", seller="a")]
        assert sum(round_points(fills, [], Decimal(29), multiplier=Decimal("1.7")).values()) == 0


class TestModels:
    @pytest.mark.parametrize(("bid", "ask"), [(10, 10), (12, 10), (0, 10), (-1, 10)])
    def test_quote_requires_positive_bid_below_ask(self, bid, ask):
        with pytest.raises(ValidationError):
            quote("a", bid, ask)

    def test_order_remaining_defaults_to_size(self):
        order = Order(id="1", player_id="a", side=Side.BUY, price=Decimal(10), size=3, seq=1)
        assert order.remaining == 3

    @pytest.mark.parametrize("size", [0, 6])
    def test_order_size_must_be_one_to_five(self, size):
        with pytest.raises(ValidationError):
            Order(id="1", player_id="a", side=Side.BUY, price=Decimal(10), size=size, seq=1)
