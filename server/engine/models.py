"""Data types and exceptions shared by the engine, scoring, and rooms."""

from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

MAX_ORDER_SIZE = 5


class EngineError(Exception):
    """Base class for every rejection the order book can raise."""


class SelfTradeError(EngineError):
    """The order would cross one of the same player's resting orders."""


class PositionLimitError(EngineError):
    """The order would take the player's exposure past the position limit."""


class InvalidPriceError(EngineError):
    """The price is not positive or is not a multiple of the tick."""


class NotFoundError(EngineError):
    """No resting order has this id."""


class NotOwnerError(EngineError):
    """The resting order belongs to a different player."""


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Order(BaseModel):
    id: str
    player_id: str
    side: Side
    # Unbounded on purpose: the engine is what raises InvalidPriceError.
    price: Decimal
    size: int = Field(ge=1, le=MAX_ORDER_SIZE)
    remaining: int = Field(ge=0)
    seq: int

    @model_validator(mode="before")
    @classmethod
    def default_remaining_to_size(cls, data: Any) -> Any:
        if isinstance(data, dict) and "remaining" not in data:
            return {**data, "remaining": data.get("size")}
        return data


class Fill(BaseModel):
    price: Decimal
    size: int = Field(ge=1)
    buyer_id: str
    seller_id: str
    buy_order_id: str
    sell_order_id: str
    seq: int


class Quote(BaseModel):
    player_id: str
    bid: Decimal
    ask: Decimal
    submitted_at: int  # epoch ms

    @model_validator(mode="after")
    def check_bid_below_ask(self) -> "Quote":
        if not 0 < self.bid < self.ask:
            raise ValueError("quote must satisfy 0 < bid < ask")
        return self


class Question(BaseModel):
    id: str
    text: str
    unit: str
    answer: Decimal | None = Field(gt=0)  # None until a candidate is researched
    tick: Decimal = Field(gt=0)
    source_url: str
    source_note: str
    category: str
    difficulty: int
    as_of: str
    status: Literal["unverified", "needs_review", "disputed", "agent_verified", "verified"]
    verification: dict | None = None  # evidence recorded by questions/verify.py
    # Case questions (Nov 9, 2026): a short setup shown with the question, more time to read
    # and trade, and a hint that is a related figure instead of a range. The setup's figure and
    # the hint's figure each carry their own source and the sentence on it that states them.
    kind: Literal["standard", "case"] = "standard"
    context: str = ""
    context_source_url: str = ""
    context_source_quote: str = ""
    hint_text: str = ""
    hint_source_url: str = ""
    hint_source_quote: str = ""


class Level(BaseModel):
    price: Decimal
    size: int


class BookSnapshot(BaseModel):
    bids: list[Level]
    asks: list[Level]
