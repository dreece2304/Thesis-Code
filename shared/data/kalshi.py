"""Kalshi public market data. READ ONLY.

This module must never gain order placement, authentication headers, or any
POST/PUT/DELETE call. ``tests/test_no_live_trading.py`` enforces that.
"""
from __future__ import annotations

import os
from datetime import datetime

import numpy as np
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


def _first_numeric(df: pd.DataFrame, candidates: list[tuple[str, float]]) -> pd.Series:
    """First present column among (name, scale) pairs, converted to float and scaled."""
    for name, scale in candidates:
        if name in df:
            return (pd.to_numeric(df[name], errors="coerce") * scale).round(4)
    return pd.Series(np.nan, index=df.index, dtype=float)


def _markets_frame(items: list[dict], include_mve: bool = False) -> pd.DataFrame:
    """Normalise the API's mixed field styles (cents ints, *_dollars strings, *_fp).

    Prices come out in dollars. Multivariate combo markets (``mve_collection_ticker``)
    are dropped unless ``include_mve`` is set: they are not modelable and flood
    the unfiltered listing.
    """
    df = pd.DataFrame(items)
    if df.empty:
        return pd.DataFrame(columns=MARKET_COLUMNS)
    if not include_mve and "mve_collection_ticker" in df:
        df = df[df["mve_collection_ticker"].fillna("").astype(str).str.len() == 0].copy()
    for c in ("yes_bid", "yes_ask", "no_bid", "no_ask", "last_price"):
        df[c] = _first_numeric(df, [(f"{c}_dollars", 1.0), (c, 0.01)])
    df["volume"] = _first_numeric(df, [("volume_fp", 1.0), ("volume", 1.0)])
    df["open_interest"] = _first_numeric(df, [("open_interest_fp", 1.0), ("open_interest", 1.0)])
    df["liquidity"] = _first_numeric(df, [("liquidity_dollars", 1.0), ("liquidity", 0.01)])
    for c in MARKET_COLUMNS:
        if c not in df:
            df[c] = None
    for c in ("open_time", "close_time", "expiration_time"):
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df[MARKET_COLUMNS + [c for c in df.columns if c not in MARKET_COLUMNS]].reset_index(drop=True)


def _ts(x) -> int | None:
    if x is None:
        return None
    return int(pd.Timestamp(x).timestamp())


@cached_frame("kalshi_markets", ttl_seconds=600)
def markets(status: str = "open", series_ticker: str | None = None,
            event_ticker: str | None = None, limit: int = 200,
            max_pages: int = 100, min_close: datetime | str | None = None,
            max_close: datetime | str | None = None, include_mve: bool = False) -> pd.DataFrame:
    """All markets matching filters, paginated. Prices in dollars.

    Use ``max_close`` to bound the listing (the unfiltered feed is tens of
    thousands of rows). Combo (MVE) markets are dropped by default.
    """
    items: list[dict] = []
    cursor = None
    for _ in range(max_pages):
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if min_close is not None:
            params["min_close_ts"] = _ts(min_close)
        if max_close is not None:
            params["max_close_ts"] = _ts(max_close)
        if cursor:
            params["cursor"] = cursor
        js = http.get_json(f"{base_url()}/markets", params=params, source="kalshi")
        items.extend(js.get("markets", []))
        cursor = js.get("cursor")
        if not cursor:
            break
    return _markets_frame(items, include_mve=include_mve)


def market(ticker: str) -> dict:
    js = http.get_json(f"{base_url()}/markets/{ticker}", source="kalshi")
    return js.get("market", js)


def orderbook(ticker: str, depth: int = 10) -> dict:
    """Resting bids as ``{'yes': [(price, qty), ...], 'no': [...]}`` in dollars.

    Kalshi lists YES bids and NO bids. A NO bid at price q is an offer to sell
    YES at 1 - q, so the best YES ask is 1 - max(no price). See ``best_quotes``.
    """
    js = http.get_json(f"{base_url()}/markets/{ticker}/orderbook",
                       params={"depth": depth}, source="kalshi")
    if "orderbook_fp" in js:
        ob = js["orderbook_fp"]
        return {side: [(round(float(lvl[0]), 4), float(lvl[1])) for lvl in (ob.get(f"{side}_dollars") or [])]
                for side in ("yes", "no")}
    ob = js.get("orderbook", js)
    return {side: [(lvl[0] / 100.0, float(lvl[1])) for lvl in (ob.get(side) or [])] for side in ("yes", "no")}


def best_quotes(book: dict) -> dict:
    """Best YES bid/ask (dollars) and the size at each, from an ``orderbook`` result."""
    yes = sorted(book.get("yes") or [], key=lambda x: -x[0])
    no = sorted(book.get("no") or [], key=lambda x: -x[0])
    return {
        "yes_bid": yes[0][0] if yes else None, "yes_bid_qty": yes[0][1] if yes else 0.0,
        "yes_ask": round(1 - no[0][0], 4) if no else None, "yes_ask_qty": no[0][1] if no else 0.0,
    }


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
