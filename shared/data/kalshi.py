"""Kalshi public market data. READ ONLY.

This module must never gain order placement, authentication headers, or any
POST/PUT/DELETE call. ``tests/test_no_live_trading.py`` enforces that.
"""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd

from . import http
from .cache import cached_frame


def base_url() -> str:
    return os.environ.get("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2").rstrip("/")


MARKET_COLUMNS = [
    "ticker", "event_ticker", "series_ticker", "title", "subtitle", "status", "category",
    "yes_bid", "yes_ask", "no_bid", "no_ask", "last_price", "volume", "volume_24h",
    "open_interest", "liquidity", "open_time", "close_time", "expiration_time",
    "rules_primary", "rules_secondary", "result",
]


def _markets_frame(items: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(items)
    for c in MARKET_COLUMNS:
        if c not in df:
            df[c] = None
    for c in ("yes_bid", "yes_ask", "no_bid", "no_ask", "last_price"):
        df[c] = pd.to_numeric(df[c], errors="coerce") / 100.0  # cents -> dollars
    for c in ("open_time", "close_time", "expiration_time"):
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df[MARKET_COLUMNS + [c for c in df.columns if c not in MARKET_COLUMNS]]


@cached_frame("kalshi_markets", ttl_seconds=600)
def markets(status: str = "open", series_ticker: str | None = None,
            event_ticker: str | None = None, limit: int = 200,
            max_pages: int = 100) -> pd.DataFrame:
    """All markets matching filters, paginated. Prices in dollars."""
    items: list[dict] = []
    cursor = None
    for _ in range(max_pages):
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if cursor:
            params["cursor"] = cursor
        js = http.get_json(f"{base_url()}/markets", params=params, source="kalshi")
        items.extend(js.get("markets", []))
        cursor = js.get("cursor")
        if not cursor:
            break
    return _markets_frame(items)


def market(ticker: str) -> dict:
    js = http.get_json(f"{base_url()}/markets/{ticker}", source="kalshi")
    return js.get("market", js)


def orderbook(ticker: str, depth: int = 10) -> dict:
    """Order book as ``{'yes': [(price_dollars, qty), ...], 'no': [...]}``."""
    js = http.get_json(f"{base_url()}/markets/{ticker}/orderbook",
                       params={"depth": depth}, source="kalshi")
    ob = js.get("orderbook", js)
    return {side: [(lvl[0] / 100.0, lvl[1]) for lvl in (ob.get(side) or [])] for side in ("yes", "no")}


@cached_frame("kalshi_trades", ttl_seconds=600)
def trades(ticker: str, limit: int = 1000, max_pages: int = 20) -> pd.DataFrame:
    items: list[dict] = []
    cursor = None
    for _ in range(max_pages):
        params = {"ticker": ticker, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        js = http.get_json(f"{base_url()}/markets/trades", params=params, source="kalshi")
        items.extend(js.get("trades", []))
        cursor = js.get("cursor")
        if not cursor:
            break
    df = pd.DataFrame(items)
    if not df.empty:
        df["created_time"] = pd.to_datetime(df["created_time"], utc=True, errors="coerce")
        for c in ("yes_price", "no_price"):
            if c in df:
                df[c] = pd.to_numeric(df[c], errors="coerce") / 100.0
    return df


@cached_frame("kalshi_candles", ttl_seconds=3600)
def candlesticks(series_ticker: str, ticker: str, start: datetime, end: datetime,
                 period_minutes: int = 60) -> pd.DataFrame:
    params = {"start_ts": int(pd.Timestamp(start).timestamp()),
              "end_ts": int(pd.Timestamp(end).timestamp()),
              "period_interval": period_minutes}
    js = http.get_json(f"{base_url()}/series/{series_ticker}/markets/{ticker}/candlesticks",
                       params=params, source="kalshi")
    df = pd.json_normalize(js.get("candlesticks", []))
    if not df.empty and "end_period_ts" in df:
        df["time"] = pd.to_datetime(df["end_period_ts"], unit="s", utc=True)
        df = df.set_index("time")
    return df
