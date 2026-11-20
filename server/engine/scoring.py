"""Settlement: fill points, the Best Quote bonus, and round totals.

Points are Decimals rounded to 0.01 per fill, so a round's fill points sum to
exactly zero.
"""

from collections import defaultdict
from decimal import Decimal
from fractions import Fraction
from typing import Iterable, Literal

from server.engine.models import Fill, Quote

ScoringMode = Literal["log", "linear"]

BEST_QUOTE_BONUS = Decimal(25)
LOG_MULTIPLIER = Decimal(100)
MAX_POINTS_PER_LOT = Decimal(200)
POINTS_PRECISION = Decimal("0.01")


def buyer_points(
    fill: Fill,
    answer: Decimal,
    mode: ScoringMode = "log",
    multiplier: Decimal = Decimal(1),
) -> Decimal:
    """Points the buyer earns on a fill. The seller earns the negative. A case question's
    round multiplies everything, the clamp included, by its multiplier (1.5 to 2.5)."""
    if answer <= 0:
        raise ValueError("answer must be positive")
    if mode == "log":
        per_lot = LOG_MULTIPLIER * (answer / fill.price).ln()
        per_lot = max(-MAX_POINTS_PER_LOT, min(MAX_POINTS_PER_LOT, per_lot))
    elif mode == "linear":
        per_lot = answer - fill.price
    else:
        raise ValueError(f"unknown scoring mode: {mode}")
    return (fill.size * per_lot * multiplier).quantize(POINTS_PRECISION)


def best_quote(quotes: Iterable[Quote], answer: Decimal) -> Quote | None:
    """The tightest quote containing the answer; earlier submission wins ties."""
    containing = [q for q in quotes if q.bid <= answer <= q.ask]
    if not containing:
        return None
    return min(containing, key=lambda q: (Fraction(q.ask) / Fraction(q.bid), q.submitted_at))


def round_points(
    fills: Iterable[Fill],
    quotes: Iterable[Quote],
    answer: Decimal,
    mode: ScoringMode = "log",
    multiplier: Decimal = Decimal(1),
) -> dict[str, Decimal]:
    """Fill points plus Best Quote bonus, keyed by player. Inactive players are absent.
    The multiplier scales both, so a case round stays zero-sum apart from the bonus."""
    points: dict[str, Decimal] = defaultdict(Decimal)
    for fill in fills:
        earned = buyer_points(fill, answer, mode, multiplier)
        points[fill.buyer_id] += earned
        points[fill.seller_id] -= earned
    winner = best_quote(quotes, answer)
    if winner is not None:
        points[winner.player_id] += (BEST_QUOTE_BONUS * multiplier).quantize(POINTS_PRECISION)
    return dict(points)
