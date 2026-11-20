"""The contract server/engine/orderbook.py must satisfy.

Conventions these tests fix, beyond what the spec says outright:
- The caller assigns Order.id and Order.seq. Tests always submit in seq order.
- The engine numbers Fill.seq itself: strictly increasing across the book's life.
- Exceptions come from server.engine.models.
- position() is 0 and resting_orders() is [] for a player the book has not seen.
"""

import random
from collections import Counter
from decimal import Decimal
from itertools import count

import pytest

from server.engine.models import (
    BookSnapshot,
    EngineError,
    InvalidPriceError,
    Level,
    NotFoundError,
    NotOwnerError,
    Order,
    PositionLimitError,
    SelfTradeError,
    Side,
)
from server.engine.orderbook import OrderBook

_next_seq = count(1)


def make_book(tick="1", max_position=10):
    return OrderBook(tick=Decimal(tick), max_position=max_position)


def order(player, side, price, size=1):
    seq = next(_next_seq)
    return Order(
        id=f"o{seq}",
        player_id=player,
        side=side,
        price=Decimal(str(price)),
        size=size,
        seq=seq,
    )


def buy(player, price, size=1):
    return order(player, Side.BUY, price, size)


def sell(player, price, size=1):
    return order(player, Side.SELL, price, size)


def levels(*pairs):
    return [Level(price=Decimal(str(price)), size=size) for price, size in pairs]


def remaining_by_id(book, player):
    return {o.id: o.remaining for o in book.resting_orders(player)}


class TestResting:
    def test_empty_book(self):
        assert make_book().snapshot() == BookSnapshot(bids=[], asks=[])

    def test_unseen_player_is_flat(self):
        book = make_book()
        assert book.position("nobody") == 0
        assert book.resting_orders("nobody") == []

    def test_non_crossing_orders_rest_without_fills(self):
        book = make_book()
        assert book.submit(buy("alice", 9)) == []
        assert book.submit(sell("bob", 11)) == []
        assert book.snapshot() == BookSnapshot(bids=levels((9, 1)), asks=levels((11, 1)))

    def test_resting_orders_are_listed_for_their_owner_only(self):
        book = make_book()
        mine = buy("alice", 9, size=2)
        book.submit(mine)
        book.submit(buy("bob", 8))
        assert remaining_by_id(book, "alice") == {mine.id: 2}


class TestMatching:
    def test_buy_crossing_fills_at_resting_price(self):
        book = make_book()
        book.submit(sell("bob", 10))
        fills = book.submit(buy("alice", 12))
        assert [f.price for f in fills] == [Decimal(10)]

    def test_sell_crossing_fills_at_resting_price(self):
        book = make_book()
        book.submit(buy("bob", 10))
        fills = book.submit(sell("alice", 8))
        assert [f.price for f in fills] == [Decimal(10)]

    def test_equal_prices_cross(self):
        book = make_book()
        book.submit(sell("bob", 10))
        assert len(book.submit(buy("alice", 10))) == 1

    def test_fill_names_both_sides_when_buyer_aggresses(self):
        book = make_book()
        resting = sell("bob", 10)
        incoming = buy("alice", 10)
        book.submit(resting)
        [fill] = book.submit(incoming)
        assert (fill.buyer_id, fill.seller_id) == ("alice", "bob")
        assert (fill.buy_order_id, fill.sell_order_id) == (incoming.id, resting.id)
        assert fill.size == 1

    def test_fill_names_both_sides_when_seller_aggresses(self):
        book = make_book()
        resting = buy("bob", 10)
        incoming = sell("alice", 10)
        book.submit(resting)
        [fill] = book.submit(incoming)
        assert (fill.buyer_id, fill.seller_id) == ("bob", "alice")
        assert (fill.buy_order_id, fill.sell_order_id) == (resting.id, incoming.id)

    def test_full_match_empties_the_book(self):
        book = make_book()
        book.submit(sell("bob", 10, size=2))
        book.submit(buy("alice", 10, size=2))
        assert book.snapshot() == BookSnapshot(bids=[], asks=[])
        assert book.resting_orders("alice") == []
        assert book.resting_orders("bob") == []

    def test_positions_follow_fills(self):
        book = make_book()
        book.submit(sell("bob", 10, size=3))
        book.submit(buy("alice", 10, size=2))
        assert book.position("alice") == 2
        assert book.position("bob") == -2

    def test_resting_orders_do_not_change_position(self):
        book = make_book()
        book.submit(buy("alice", 10, size=3))
        assert book.position("alice") == 0

    def test_fill_seq_increases_within_and_across_submits(self):
        book = make_book()
        book.submit(sell("bob", 10))
        book.submit(sell("carol", 11))
        book.submit(sell("dave", 12))
        fills = book.submit(buy("alice", 11, size=2))
        fills += book.submit(buy("alice", 12))
        seqs = [f.seq for f in fills]
        assert seqs == sorted(set(seqs))
        assert len(seqs) == 3


class TestPartialFills:
    def test_incoming_remainder_rests_at_its_limit(self):
        book = make_book()
        book.submit(sell("bob", 10, size=2))
        incoming = buy("alice", 11, size=5)
        fills = book.submit(incoming)
        assert sum(f.size for f in fills) == 2
        assert remaining_by_id(book, "alice") == {incoming.id: 3}
        assert book.snapshot() == BookSnapshot(bids=levels((11, 3)), asks=[])

    def test_resting_order_keeps_its_remainder(self):
        book = make_book()
        resting = sell("bob", 10, size=5)
        book.submit(resting)
        [fill] = book.submit(buy("alice", 10, size=2))
        assert fill.size == 2
        assert remaining_by_id(book, "bob") == {resting.id: 3}
        assert book.snapshot() == BookSnapshot(bids=[], asks=levels((10, 3)))

    def test_partial_fill_keeps_original_size(self):
        book = make_book()
        book.submit(sell("bob", 10, size=5))
        book.submit(buy("alice", 10, size=2))
        [resting] = book.resting_orders("bob")
        assert (resting.size, resting.remaining) == (5, 3)


class TestWalkingTheBook:
    def test_marketable_order_walks_levels_best_price_first(self):
        book = make_book()
        book.submit(sell("bob", 12))
        book.submit(sell("carol", 10))
        book.submit(sell("dave", 11, size=2))
        fills = book.submit(buy("alice", 12, size=3))
        assert [(f.price, f.size) for f in fills] == [(Decimal(10), 1), (Decimal(11), 2)]
        assert book.snapshot() == BookSnapshot(bids=[], asks=levels((12, 1)))

    def test_sell_walks_bids_highest_first(self):
        book = make_book()
        book.submit(buy("bob", 8))
        book.submit(buy("carol", 10))
        book.submit(buy("dave", 9, size=2))
        fills = book.submit(sell("alice", 8, size=3))
        assert [(f.price, f.size) for f in fills] == [(Decimal(10), 1), (Decimal(9), 2)]

    def test_walk_stops_at_the_limit_and_rests(self):
        book = make_book()
        book.submit(sell("bob", 10))
        book.submit(sell("carol", 11))
        book.submit(sell("dave", 12))
        fills = book.submit(buy("alice", 11, size=5))
        assert [f.price for f in fills] == [Decimal(10), Decimal(11)]
        assert book.snapshot() == BookSnapshot(bids=levels((11, 3)), asks=levels((12, 1)))
        assert book.position("alice") == 2


class TestPriority:
    def test_better_price_beats_earlier_time_on_asks(self):
        book = make_book()
        book.submit(sell("bob", 11))
        book.submit(sell("carol", 10))
        [fill] = book.submit(buy("alice", 11))
        assert fill.seller_id == "carol"

    def test_better_price_beats_earlier_time_on_bids(self):
        book = make_book()
        book.submit(buy("bob", 9))
        book.submit(buy("carol", 10))
        [fill] = book.submit(sell("alice", 9))
        assert fill.buyer_id == "carol"

    def test_earlier_order_fills_first_at_the_same_ask(self):
        book = make_book()
        book.submit(sell("bob", 10))
        book.submit(sell("carol", 10))
        [fill] = book.submit(buy("alice", 10))
        assert fill.seller_id == "bob"

    def test_earlier_order_fills_first_at_the_same_bid(self):
        book = make_book()
        book.submit(buy("bob", 10))
        book.submit(buy("carol", 10))
        [fill] = book.submit(sell("alice", 10))
        assert fill.buyer_id == "bob"

    def test_partially_filled_order_keeps_its_place_in_line(self):
        book = make_book()
        book.submit(sell("bob", 10, size=2))
        book.submit(sell("carol", 10))
        book.submit(buy("dave", 10))
        fills = book.submit(buy("erin", 10, size=2))
        assert [f.seller_id for f in fills] == ["bob", "carol"]


class TestSelfTrade:
    def test_buy_crossing_own_ask_is_rejected(self):
        book = make_book()
        book.submit(sell("alice", 10))
        with pytest.raises(SelfTradeError):
            book.submit(buy("alice", 10))

    def test_sell_crossing_own_bid_is_rejected(self):
        book = make_book()
        book.submit(buy("alice", 10))
        with pytest.raises(SelfTradeError):
            book.submit(sell("alice", 9))

    def test_own_quote_on_both_sides_without_crossing_is_allowed(self):
        book = make_book()
        book.submit(buy("alice", 9))
        assert book.submit(sell("alice", 10)) == []

    def test_rejected_before_any_fill(self):
        book = make_book()
        book.submit(sell("bob", 10))
        book.submit(sell("alice", 11))
        with pytest.raises(SelfTradeError):
            book.submit(buy("alice", 11, size=2))
        assert book.snapshot() == BookSnapshot(bids=[], asks=levels((10, 1), (11, 1)))
        assert book.position("alice") == 0
        assert book.position("bob") == 0

    def test_crossing_any_own_order_rejects_even_if_it_would_not_be_reached(self):
        # Bob's 10 would absorb the whole order, but the limit still crosses Alice's 11.
        book = make_book()
        book.submit(sell("bob", 10))
        book.submit(sell("alice", 11))
        with pytest.raises(SelfTradeError):
            book.submit(buy("alice", 11))
        assert book.snapshot().asks == levels((10, 1), (11, 1))

    def test_rejected_order_does_not_rest(self):
        book = make_book()
        resting = sell("alice", 10)
        book.submit(resting)
        with pytest.raises(SelfTradeError):
            book.submit(buy("alice", 10))
        assert remaining_by_id(book, "alice") == {resting.id: 1}


class TestPositionLimit:
    def test_buy_exactly_to_the_limit_is_allowed(self):
        book = make_book(max_position=5)
        assert book.submit(buy("alice", 10, size=5)) == []

    def test_sell_exactly_to_the_limit_is_allowed(self):
        book = make_book(max_position=5)
        assert book.submit(sell("alice", 10, size=5)) == []

    def test_filled_position_counts_on_the_long_side(self):
        book = make_book(max_position=5)
        book.submit(sell("bob", 10, size=5))
        book.submit(sell("carol", 10))
        book.submit(buy("alice", 10, size=5))
        with pytest.raises(PositionLimitError):
            book.submit(buy("alice", 10))

    def test_filled_position_counts_on_the_short_side(self):
        book = make_book(max_position=5)
        book.submit(buy("bob", 10, size=5))
        book.submit(buy("carol", 10))
        book.submit(sell("alice", 10, size=5))
        with pytest.raises(PositionLimitError):
            book.submit(sell("alice", 10))

    def test_resting_buys_count_with_no_position(self):
        book = make_book(max_position=5)
        book.submit(buy("alice", 10, size=3))
        book.submit(buy("alice", 9, size=2))
        assert book.position("alice") == 0
        with pytest.raises(PositionLimitError):
            book.submit(buy("alice", 8))

    def test_resting_sells_count_with_no_position(self):
        book = make_book(max_position=5)
        book.submit(sell("alice", 10, size=3))
        book.submit(sell("alice", 11, size=2))
        assert book.position("alice") == 0
        with pytest.raises(PositionLimitError):
            book.submit(sell("alice", 12))

    def test_position_and_resting_buys_add_together(self):
        book = make_book(max_position=5)
        book.submit(sell("bob", 10, size=2))
        book.submit(buy("alice", 10, size=2))
        book.submit(buy("alice", 9, size=3))
        with pytest.raises(PositionLimitError):
            book.submit(buy("alice", 8))

    def test_position_and_resting_sells_add_together(self):
        book = make_book(max_position=5)
        book.submit(buy("bob", 10, size=2))
        book.submit(sell("alice", 10, size=2))
        book.submit(sell("alice", 11, size=3))
        with pytest.raises(PositionLimitError):
            book.submit(sell("alice", 12))

    def test_opposite_side_resting_does_not_count(self):
        book = make_book(max_position=5)
        book.submit(sell("alice", 20, size=5))
        assert book.submit(buy("alice", 10, size=5)) == []

    def test_buying_back_from_max_short_is_allowed(self):
        book = make_book(max_position=5)
        book.submit(buy("bob", 10, size=5))
        book.submit(sell("alice", 10, size=5))
        book.submit(sell("carol", 11, size=5))
        fills = book.submit(buy("alice", 11, size=5))
        assert sum(f.size for f in fills) == 5
        assert book.position("alice") == 0

    def test_a_long_position_makes_room_on_the_short_side(self):
        book = make_book(max_position=5)
        book.submit(sell("bob", 10, size=3))
        book.submit(buy("alice", 10, size=3))
        assert book.submit(sell("alice", 20, size=5)) == []
        assert book.submit(sell("alice", 21, size=3)) == []
        with pytest.raises(PositionLimitError):
            book.submit(sell("alice", 22))

    def test_cancel_frees_exposure(self):
        book = make_book(max_position=5)
        resting = buy("alice", 10, size=5)
        book.submit(resting)
        with pytest.raises(PositionLimitError):
            book.submit(buy("alice", 9))
        book.cancel(resting.id, "alice")
        assert book.submit(buy("alice", 9, size=5)) == []

    def test_filling_a_resting_order_does_not_change_exposure(self):
        book = make_book(max_position=5)
        book.submit(buy("alice", 10, size=5))
        book.submit(sell("bob", 10, size=2))
        assert book.position("alice") == 2
        with pytest.raises(PositionLimitError):
            book.submit(buy("alice", 9))

    def test_over_limit_order_is_rejected_whole(self):
        book = make_book(max_position=5)
        book.submit(sell("bob", 10, size=3))
        book.submit(buy("alice", 9, size=3))
        with pytest.raises(PositionLimitError):
            book.submit(buy("alice", 10, size=3))
        assert book.position("alice") == 0
        assert book.position("bob") == 0
        assert book.snapshot() == BookSnapshot(bids=levels((9, 3)), asks=levels((10, 3)))

    def test_limit_is_per_player(self):
        book = make_book(max_position=5)
        book.submit(buy("alice", 10, size=5))
        assert book.submit(buy("bob", 10, size=5)) == []


class TestPrices:
    @pytest.mark.parametrize("price", [0, -1, "-0.5"])
    def test_non_positive_price_is_rejected(self, price):
        book = make_book(tick="0.5")
        with pytest.raises(InvalidPriceError):
            book.submit(buy("alice", price))

    @pytest.mark.parametrize("price", ["10.25", "0.1", "3.01"])
    def test_off_tick_price_is_rejected(self, price):
        book = make_book(tick="0.5")
        with pytest.raises(InvalidPriceError):
            book.submit(sell("alice", price))

    @pytest.mark.parametrize("price", ["0.5", "10", "10.5", "9999.5"])
    def test_on_tick_price_is_accepted(self, price):
        book = make_book(tick="0.5")
        assert book.submit(buy("alice", price)) == []

    def test_tick_check_is_exact_decimal(self):
        # 0.07 % 0.01 is not 0 in binary floating point.
        book = make_book(tick="0.01")
        assert book.submit(buy("alice", "0.07")) == []

    def test_rejected_price_does_not_rest(self):
        book = make_book(tick="0.5")
        with pytest.raises(InvalidPriceError):
            book.submit(buy("alice", "10.25"))
        assert book.snapshot() == BookSnapshot(bids=[], asks=[])
        assert book.resting_orders("alice") == []


class TestCancel:
    def test_removes_the_order(self):
        book = make_book()
        resting = buy("alice", 10)
        book.submit(resting)
        book.cancel(resting.id, "alice")
        assert book.resting_orders("alice") == []
        assert book.snapshot() == BookSnapshot(bids=[], asks=[])

    def test_removes_exactly_one_order(self):
        book = make_book()
        first = buy("alice", 10)
        second = buy("alice", 10)
        other = buy("bob", 10)
        book.submit(first)
        book.submit(second)
        book.submit(other)
        book.cancel(first.id, "alice")
        assert remaining_by_id(book, "alice") == {second.id: 1}
        assert remaining_by_id(book, "bob") == {other.id: 1}
        assert book.snapshot().bids == levels((10, 2))

    def test_unknown_id_raises_not_found(self):
        with pytest.raises(NotFoundError):
            make_book().cancel("missing", "alice")

    def test_other_players_order_raises_not_owner_and_stays(self):
        book = make_book()
        resting = buy("alice", 10)
        book.submit(resting)
        with pytest.raises(NotOwnerError):
            book.cancel(resting.id, "bob")
        assert remaining_by_id(book, "alice") == {resting.id: 1}

    def test_cancelling_twice_raises_not_found(self):
        book = make_book()
        resting = buy("alice", 10)
        book.submit(resting)
        book.cancel(resting.id, "alice")
        with pytest.raises(NotFoundError):
            book.cancel(resting.id, "alice")

    def test_fully_filled_order_raises_not_found(self):
        book = make_book()
        resting = sell("bob", 10)
        book.submit(resting)
        book.submit(buy("alice", 10))
        with pytest.raises(NotFoundError):
            book.cancel(resting.id, "bob")

    def test_partially_filled_order_can_be_cancelled(self):
        book = make_book()
        resting = sell("bob", 10, size=3)
        book.submit(resting)
        book.submit(buy("alice", 10))
        book.cancel(resting.id, "bob")
        assert book.snapshot() == BookSnapshot(bids=[], asks=[])
        assert book.position("bob") == -1

    def test_cancelled_order_cannot_be_filled(self):
        book = make_book()
        resting = sell("bob", 10)
        book.submit(resting)
        book.cancel(resting.id, "bob")
        assert book.submit(buy("alice", 10)) == []


class TestSnapshot:
    def test_bids_descend_and_asks_ascend(self):
        book = make_book()
        for price in (8, 10, 9):
            book.submit(buy("alice", price))
        for price in (13, 11, 12):
            book.submit(sell("bob", price))
        snapshot = book.snapshot()
        assert [level.price for level in snapshot.bids] == [10, 9, 8]
        assert [level.price for level in snapshot.asks] == [11, 12, 13]

    def test_aggregates_size_per_level_across_players(self):
        book = make_book()
        book.submit(buy("alice", 10, size=2))
        book.submit(buy("bob", 10, size=3))
        book.submit(buy("carol", 9))
        assert book.snapshot().bids == levels((10, 5), (9, 1))

    def test_aggregates_remaining_not_original_size(self):
        book = make_book()
        book.submit(sell("bob", 10, size=5))
        book.submit(sell("carol", 10, size=2))
        book.submit(buy("alice", 10, size=3))
        assert book.snapshot().asks == levels((10, 4))

    def test_default_depth_is_five_per_side(self):
        book = make_book()
        for offset in range(7):
            book.submit(buy(f"b{offset}", 10 - offset))
            book.submit(sell(f"s{offset}", 20 + offset))
        snapshot = book.snapshot()
        assert [level.price for level in snapshot.bids] == [10, 9, 8, 7, 6]
        assert [level.price for level in snapshot.asks] == [20, 21, 22, 23, 24]

    def test_depth_truncates_levels_not_orders(self):
        book = make_book()
        book.submit(buy("alice", 10))
        book.submit(buy("bob", 10))
        book.submit(buy("carol", 9))
        assert book.snapshot(depth=1).bids == levels((10, 2))

    def test_snapshot_does_not_change_the_book(self):
        book = make_book()
        book.submit(buy("alice", 10))
        assert book.snapshot() == book.snapshot()
        assert len(book.submit(sell("bob", 10))) == 1


PLAYERS = ["alice", "bob", "carol", "dave"]
FUZZ_MAX_POSITION = 5


def random_ops(seed, steps=400):
    """A reproducible script of submits and cancels, some of which will be rejected."""
    rng = random.Random(seed)
    ops = []
    submitted = []
    for seq in range(1, steps + 1):
        if submitted and rng.random() < 0.25:
            target = rng.choice(submitted)
            # Mostly the real owner, sometimes someone else.
            player = target.player_id if rng.random() < 0.8 else rng.choice(PLAYERS)
            ops.append(("cancel", target.id, player))
            continue
        placed = Order(
            id=f"f{seq}",
            player_id=rng.choice(PLAYERS),
            side=rng.choice([Side.BUY, Side.SELL]),
            price=Decimal(rng.randint(1, 20)),
            size=rng.randint(1, 5),
            seq=seq,
        )
        submitted.append(placed)
        ops.append(("submit", placed))
    return ops


def apply_op(book, op):
    """Returns the fills an op produced, or the name of the error it raised."""
    try:
        if op[0] == "submit":
            return book.submit(op[1].model_copy(deep=True))
        book.cancel(op[1], op[2])
        return []
    except EngineError as error:
        return type(error).__name__


def assert_invariants(book, ledger):
    resting = {player: book.resting_orders(player) for player in PLAYERS}

    assert sum(book.position(player) for player in PLAYERS) == 0
    for player, orders in resting.items():
        position = book.position(player)
        assert position == ledger[player]
        buys = sum(o.remaining for o in orders if o.side is Side.BUY)
        sells = sum(o.remaining for o in orders if o.side is Side.SELL)
        assert position + buys <= FUZZ_MAX_POSITION
        assert position - sells >= -FUZZ_MAX_POSITION
        assert all(o.remaining > 0 for o in orders)

    snapshot = book.snapshot(depth=100)
    if snapshot.bids and snapshot.asks:
        assert snapshot.bids[0].price < snapshot.asks[0].price
    for side, book_levels in ((Side.BUY, snapshot.bids), (Side.SELL, snapshot.asks)):
        expected = Counter()
        for orders in resting.values():
            for o in orders:
                if o.side is side:
                    expected[o.price] += o.remaining
        assert {level.price: level.size for level in book_levels} == dict(expected)


class TestRandomSequences:
    @pytest.mark.parametrize("seed", range(5))
    def test_same_calls_give_same_results(self, seed):
        ops = random_ops(seed)
        first = make_book(max_position=FUZZ_MAX_POSITION)
        second = make_book(max_position=FUZZ_MAX_POSITION)
        for op in ops:
            assert apply_op(first, op) == apply_op(second, op)
        assert first.snapshot(depth=100) == second.snapshot(depth=100)
        for player in PLAYERS:
            assert first.position(player) == second.position(player)

    @pytest.mark.parametrize("seed", range(5))
    def test_invariants_hold_after_every_call(self, seed):
        book = make_book(max_position=FUZZ_MAX_POSITION)
        ledger = Counter()
        for op in random_ops(seed):
            result = apply_op(book, op)
            if not isinstance(result, str):
                for fill in result:
                    assert fill.buyer_id != fill.seller_id
                    ledger[fill.buyer_id] += fill.size
                    ledger[fill.seller_id] -= fill.size
            assert_invariants(book, ledger)
