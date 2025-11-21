import os
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import WatchlistItem, Order, Position, Layout

FINNHUB_BASE = "https://finnhub.io/api/v1"
API_KEY = os.getenv("MARKET_DATA_API_KEY") or os.getenv("FINNHUB_API_KEY")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Candle(BaseModel):
    t: int  # epoch seconds
    o: float
    h: float
    l: float
    c: float
    v: float


# --------- Utility functions ---------

def _ensure_api_key():
    if not API_KEY:
        raise HTTPException(status_code=400, detail="Market data API key not configured. Set FINNHUB_API_KEY or MARKET_DATA_API_KEY.")


def _finnhub_get(path: str, params: dict):
    _ensure_api_key()
    params = {**params, "token": API_KEY}
    r = requests.get(f"{FINNHUB_BASE}{path}", params=params, timeout=15)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


def timeframe_to_resolution(tf: str) -> str:
    mapping = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "4h": "240",
        "1d": "D",
        "1w": "W",
        "1mo": "M",
    }
    return mapping.get(tf, "1")


# --------- Health ---------
@app.get("/")
def root():
    return {"service": "trading-platform-backend", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/test")
def test_database():
    try:
        names = db.list_collection_names() if db else []
        return {"backend": "ok", "db": bool(db), "collections": names}
    except Exception as e:
        return {"backend": "ok", "db": False, "error": str(e)}


# --------- Market Data ---------
@app.get("/api/symbols")
def list_symbols(q: Optional[str] = Query(None, description="Search query")):
    # Finnhub stock symbol lookup (US)
    params = {"exchange": "US"}
    data = _finnhub_get("/stock/symbol", params)
    items = [
        {"symbol": it.get("symbol"), "description": it.get("description")}
        for it in data
        if not q or (q.lower() in (it.get("symbol", "").lower() + it.get("description", "").lower()))
    ]
    return items[:100]


@app.get("/api/candles")
def candles(symbol: str, timeframe: str = "1m", count: int = 500):
    to_ts = int(time.time())
    tf = timeframe_to_resolution(timeframe)
    # Map to seconds range
    sec_per = {"1":60, "5":300, "15":900, "30":1800, "60":3600, "240":14400}.get(tf, 60)
    if tf in ["D", "W", "M"]:
        sec_per = 86400
    frm = to_ts - sec_per * count
    data = _finnhub_get("/stock/candle", {"symbol": symbol, "resolution": tf, "from": frm, "to": to_ts})
    if data.get("s") != "ok":
        raise HTTPException(status_code=400, detail=f"No candle data: {data}")
    candles = [
        Candle(t=t, o=o, h=h, l=l, c=c, v=v).model_dump()
        for t, o, h, l, c, v in zip(data["t"], data["o"], data["h"], data["l"], data["c"], data["v"])
    ]
    return candles


@app.get("/api/quote")
def quote(symbol: str):
    data = _finnhub_get("/quote", {"symbol": symbol})
    return data


# --------- Indicators (simple server-side SMA/EMA) ---------
@app.get("/api/indicators/sma")
def sma(symbol: str, timeframe: str = "1m", length: int = 20):
    candles_data = candles(symbol, timeframe, 600)
    closes = [c["c"] for c in candles_data]
    out = []
    for i in range(len(closes)):
        if i + 1 < length:
            out.append(None)
        else:
            window = closes[i + 1 - length : i + 1]
            out.append(sum(window) / length)
    return {"values": out, "length": length}


@app.get("/api/indicators/ema")
def ema(symbol: str, timeframe: str = "1m", length: int = 20):
    candles_data = candles(symbol, timeframe, 600)
    closes = [c["c"] for c in candles_data]
    out: List[Optional[float]] = []
    k = 2 / (length + 1)
    ema_prev = None
    for i, price in enumerate(closes):
        if i == 0:
            ema_prev = price
        else:
            ema_prev = price * k + ema_prev * (1 - k)
        out.append(round(ema_prev, 6))
    return {"values": out, "length": length}


# --------- Watchlist ---------
@app.get("/api/watchlist")
def get_watchlist(user_id: str = "demo"):
    docs = get_documents("watchlistitem", {"user_id": user_id})
    return docs


@app.post("/api/watchlist")
def add_watchlist(item: WatchlistItem):
    _id = create_document("watchlistitem", item)
    return {"inserted_id": _id}


# --------- Paper Trading (simplified) ---------
@app.post("/api/orders")
def place_order(order: Order):
    # For market orders, we fill immediately at last price
    if order.type == "market":
        q = _finnhub_get("/quote", {"symbol": order.symbol})
        last = q.get("c")
        if not last:
            raise HTTPException(status_code=400, detail="No last price")
        order.limit_price = last
        order.status = "filled"
        order.created_at = datetime.now(timezone.utc)
    _id = create_document("order", order)
    return {"order_id": _id, "status": order.status, "fill_price": order.limit_price}


@app.get("/api/orders")
def list_orders(user_id: str = "demo"):
    return get_documents("order", {"user_id": user_id})


# --------- Layouts ---------
@app.get("/api/layouts")
def list_layouts(user_id: str = "demo"):
    return get_documents("layout", {"user_id": user_id})


@app.post("/api/layouts")
def save_layout(layout: Layout):
    _id = create_document("layout", layout)
    return {"layout_id": _id}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
