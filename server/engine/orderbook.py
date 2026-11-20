"""Price-time priority limit order book. Pure: no I/O, clocks, or randomness."""

from bisect import insort
from collections import Counter
from decimal import Decimal, InvalidOperation

from server.engine.models import (
    BookSnapshot,
    Fill,
    InvalidPriceError,
    Level,
    NotFoundError,
    NotOwnerError,
    Order,
    PositionLimitError,
    SelfTradeError,
    Side,
)


def _bid_priority(order: Order) -> tuple[Decimal, int]:
    return (-order.price, order.seq)


def _ask_priority(order: Order) -> tuple[Decimal, int]:
    return (order.price, order.seq)


def _crosses(incoming: Order, resting: Order) -> bool:
    if incoming.side is Side.BUY:
        return incoming.price >= resting.price
    return incoming.price <= resting.price


class OrderBook:
    def __init__(self, tick: Decimal, max_position: int):
        self._tick = tick
        self._max_position = max_position
        # Best order first on each side.
        self._bids: list[Order] = []
        self._asks: list[Order] = []
        self._resting: dict[str, Order] = {}
        self._positions: Counter[str] = Counter()
        self._fill_seq = 0

    def submit(self, order: Order) -> list[Fill]:
        self._check_price(order)
        self._check_self_trade(order)
        self._check_position_limit(order)

        incoming = order.model_copy()  # the caller's object never changes under them
        fills = self._match(incoming)
        if incoming.remaining > 0:
            self._rest(incoming)
        return fills

    def cancel(self, order_id: str, player_id: str) -> None:
        order = self._resting.get(order_id)
        if order is None:
            raise NotFoundError(order_id)
        if order.player_id != player_id:
            raise NotOwnerError(order_id)
        self._remove(order)

    def snapshot(self, depth: int = 5) -> BookSnapshot:
        return BookSnapshot(
            bids=self._levels(self._bids, depth),
            asks=self._levels(self._asks, depth),
        )

    def position(self, player_id: str) -> int:
        return self._positions[player_id]

    def resting_orders(self, player_id: str) -> list[Order]:
        return [
            order.model_copy()
            for order in self._resting.values()
            if order.player_id == player_id
        ]

    def _check_price(self, order: Order) -> None:
        try:
            valid = order.price > 0 and order.price % self._tick == 0
        except InvalidOperation:  # too large for Decimal's context to divide
            valid = False
        if not valid:
            raise InvalidPriceError(str(order.price))

    def _check_self_trade(self, order: Order) -> None:
        for resting in self._opposite_side(order):
            if resting.player_id == order.player_id and _crosses(order, resting):
                raise SelfTradeError(order.id)

    def _check_position_limit(self, order: Order) -> None:
        position = self._positions[order.player_id]
        same_side = self._bids if order.side is Side.BUY else self._asks
        resting = sum(o.remaining for o in same_side if o.player_id == order.player_id)
        if order.side is Side.BUY:
            over_limit = position + resting + order.remaining > self._max_position
        else:
            over_limit = position - resting - order.remaining < -self._max_position
        if over_limit:
            raise PositionLimitError(order.id)

    def _match(self, incoming: Order) -> list[Fill]:
        fills = []
        opposite = self._opposite_side(incoming)
        while incoming.remaining > 0 and opposite and _crosses(incoming, opposite[0]):
            resting = opposite[0]
            size = min(incoming.remaining, resting.remaining)
            fills.append(self._fill(incoming, resting, size))
            incoming.remaining -= size
            resting.remaining -= size
            if resting.remaining == 0:
                self._remove(resting)
        return fills

    def _fill(self, incoming: Order, resting: Order, size: int) -> Fill:
        buy, sell = (incoming, resting) if incoming.side is Side.BUY else (resting, incoming)
        self._fill_seq += 1
        self._positions[buy.player_id] += size
        self._positions[sell.player_id] -= size
        return Fill(
            price=resting.price,
            size=size,
            buyer_id=buy.player_id,
            seller_id=sell.player_id,
            buy_order_id=buy.id,
            sell_order_id=sell.id,
            seq=self._fill_seq,
        )

    def _rest(self, order: Order) -> None:
        if order.side is Side.BUY:
            insort(self._bids, order, key=_bid_priority)
        else:
            insort(self._asks, order, key=_ask_priority)
        self._resting[order.id] = order

    def _remove(self, order: Order) -> None:
        side = self._bids if order.side is Side.BUY else self._asks
        side.remove(order)
        del self._resting[order.id]

    def _opposite_side(self, order: Order) -> list[Order]:
        return self._asks if order.side is Side.BUY else self._bids

    @staticmethod
    def _levels(orders: list[Order], depth: int) -> list[Level]:
        sizes: dict[Decimal, int] = {}
        for order in orders:
            sizes[order.price] = sizes.get(order.price, 0) + order.remaining
        return [Level(price=price, size=size) for price, size in list(sizes.items())[:depth]]
