"""
Trading Platform Schemas

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
- WatchlistItem -> "watchlistitem"
- Order -> "order"
- Position -> "position"
- Layout -> "layout"
"""
from typing import Optional, Literal, List
from pydantic import BaseModel, Field
from datetime import datetime

class WatchlistItem(BaseModel):
    user_id: str = Field("demo", description="Owner identifier")
    symbol: str = Field(..., description="Ticker symbol, e.g., AAPL, BTCUSD")
    exchange: Optional[str] = Field(None, description="Exchange or venue")
    note: Optional[str] = None

class Order(BaseModel):
    user_id: str = Field("demo")
    symbol: str
    side: Literal["buy", "sell"]
    type: Literal["market", "limit"] = "market"
    qty: float = Field(..., gt=0)
    limit_price: Optional[float] = Field(None, gt=0)
    status: Literal["open", "filled", "canceled"] = "open"
    created_at: Optional[datetime] = None

class Position(BaseModel):
    user_id: str = Field("demo")
    symbol: str
    qty: float = 0
    avg_price: float = 0
    realized_pnl: float = 0

class Layout(BaseModel):
    user_id: str = Field("demo")
    name: str
    data: dict
