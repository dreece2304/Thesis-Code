"""Kalshi side of the weather model: discovery, rules parsing, order-book
snapshots, settlements, and the paper order simulator. READ ONLY against the
exchange; paper orders live in our own DuckDB table.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from shared.data import kalshi as kx
from shared.ledger import Ledger

from ..fees import kalshi_fee
from .stations import ACTIVE, BY_SERIES, Station

_RE_EVENT_DATE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})(?:-|$)")
_RE_TITLE_GT = re.compile(r">\s*(-?\d+)\s*°")
_RE_TITLE_LT = re.compile(r"<\s*(-?\d+)\s*°")
_RE_TITLE_RANGE = re.compile(r"(-?\d+)\s*-\s*(-?\d+)\s*°")
_RE_RULES_STATION = re.compile(r"\(([A-Z]{3,6})\)")


def parse_event_date(ticker: str) -> date:
    """``KXHIGHNY-26SEP02-T82`` -> 2026-09-02."""
    m = _RE_EVENT_DATE.search(ticker)
    if not m:
        raise ValueError(f"no date in {ticker!r}")
    return datetime.strptime(f"{m.group(1)}{m.group(2)}{m.group(3)}", "%y%b%d").date()


def parse_strike(row: dict) -> tuple[str, int | None, int | None]:
    """(side, threshold, upper) from Kalshi strike fields, else from the title.

    ``above``: settlement >= threshold (floor_strike + 1, "greater").
    ``below``: settlement <= threshold (cap_strike - 1, "less").
    ``between``: threshold..upper inclusive.
    """
    st = row.get("strike_type")
    fl, cp = row.get("floor_strike"), row.get("cap_strike")
    if st == "greater" and fl is not None and not pd.isna(fl):
        return "above", int(round(float(fl))) + 1, None
    if st == "less" and cp is not None and not pd.isna(cp):
        return "below", int(round(float(cp))) - 1, None
    if st == "between" and fl is not None and cp is not None and not pd.isna(fl) and not pd.isna(cp):
        # Kalshi range buckets are "81-82" for floor 80.5? Use the title when it exists.
        title = row.get("title") or ""
        m = _RE_TITLE_RANGE.search(title)
        if m:
            return "between", int(m.group(1)), int(m.group(2))
        return "between", int(round(float(fl))), int(round(float(cp)))
    title = row.get("title") or ""
    m = _RE_TITLE_RANGE.search(title)
    if m:
        return "between", int(m.group(1)), int(m.group(2))
    m = _RE_TITLE_GT.search(title)
    if m:
        return "above", int(m.group(1)) + 1, None
    m = _RE_TITLE_LT.search(title)
    if m:
        return "below", int(m.group(1)) - 1, None
    raise ValueError(f"cannot parse strike from {row.get('ticker')!r}: {title!r}")


def rules_station(rules: str | None) -> str | None:
    m = _RE_RULES_STATION.search(rules or "")
    return m.group(1) if m else None


def discover(stations=ACTIVE, status: str = "open", **kw) -> pd.DataFrame:
    """Open markets for each station with parsed strike, date and station check."""
    frames = []
    for st in stations:
        mk = kx.markets(status=status, series_ticker=st.series, **kw)
        if mk.empty:
            continue
        mk = mk.copy()
        mk["station"] = st.key
        mk["target_date"] = mk["ticker"].map(parse_event_date)
        parsed = [parse_strike(r) for r in mk.to_dict("records")]
        mk["side"] = [p[0] for p in parsed]
        mk["threshold"] = [p[1] for p in parsed]
        mk["upper"] = [p[2] for p in parsed]
        mk["rules_station"] = mk["rules_primary"].map(rules_station)
        mk["station_ok"] = mk["rules_station"].fillna(st.cli) == st.cli
        frames.append(mk)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def settled_values(station: Station, max_pages: int = 5, **kw) -> pd.DataFrame:
    """(station, target_date, kalshi_value) from settled markets' expiration_value."""
    mk = kx.markets(status="settled", series_ticker=station.series, max_pages=max_pages, **kw)
    if mk.empty or "expiration_value" not in mk:
        return pd.DataFrame(columns=["station", "target_date", "kalshi_value"])
    df = mk[["ticker", "expiration_value", "result"]].copy()
    df["target_date"] = df["ticker"].map(parse_event_date)
    df["kalshi_value"] = pd.to_numeric(df["expiration_value"], errors="coerce")
    df = df.dropna(subset=["kalshi_value"]).drop_duplicates("target_date")
    df["station"] = station.key
    return df[["station", "target_date", "kalshi_value"]].reset_index(drop=True)


# -- order book snapshots -----------------------------------------------------------
def snapshot_dir() -> Path:
    return Path(os.environ.get("DATA_CACHE_DIR", "data_cache")) / "weather" / "orderbooks"


def snapshot_orderbook(ticker: str, depth: int = 10, persist: bool = True, now: datetime | None = None) -> dict:
    """Full book plus best quotes; appended to a daily JSONL file."""
    now = now or datetime.now(timezone.utc)
    book = kx.orderbook(ticker, depth=depth)
    q = kx.best_quotes(book)
    snap = {"id": uuid.uuid4().hex, "ts": now.isoformat(), "ticker": ticker, **q, "book": book}
    if persist:
        d = snapshot_dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / f"{now:%Y-%m-%d}.jsonl").open("a") as f:
            f.write(json.dumps(snap) + "\n")
    return snap


# -- paper order simulator -----------------------------------------------------------
PAPER_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_orders (
    id           VARCHAR PRIMARY KEY,
    ts           TIMESTAMP NOT NULL,
    ticker       VARCHAR NOT NULL,
    station      VARCHAR,
    target_date  DATE,
    side         VARCHAR NOT NULL,      -- 'yes' or 'no'
    limit_price  DOUBLE NOT NULL,
    contracts    DOUBLE NOT NULL,
    fair         DOUBLE,
    status       VARCHAR NOT NULL,      -- 'filled', 'resting', 'cancelled'
    fill_price   DOUBLE,
    fee          DOUBLE,
    snapshot_id  VARCHAR,
    bet_key      VARCHAR,
    settled      INTEGER,               -- 1 yes, 0 no, NULL open
    pnl          DOUBLE,
    notes        VARCHAR
);
"""


@dataclass
class Fill:
    filled: bool
    price: float | None
    fee: float
    reason: str


def maker_fill(side: str, limit_price: float, quotes: dict, contracts: float) -> Fill:
    """Spec fill rule: fill only if our limit is at or better than the best opposing quote.

    Buying YES at L fills if L >= best YES ask; buying NO at L fills if
    L >= best NO ask (= 1 - best YES bid). Fill price is our limit; fee is the
    maker fee on the fill.
    """
    if side == "yes":
        opp = quotes.get("yes_ask")
    elif side == "no":
        opp = None if quotes.get("yes_bid") is None else round(1 - quotes["yes_bid"], 4)
    else:
        raise ValueError(side)
    if opp is None:
        return Fill(False, None, 0.0, "no opposing quote")
    if limit_price + 1e-9 >= opp:
        return Fill(True, limit_price, kalshi_fee(limit_price, contracts, maker=True), "limit at or through best opposing quote")
    return Fill(False, None, 0.0, f"limit {limit_price:.2f} below best opposing {opp:.2f}")


class PaperBook:
    """Paper order log in the weather ledger's DuckDB file."""

    def __init__(self, ledger: Ledger):
        self.ledger = ledger
        self.con = ledger.con
        self.con.execute(PAPER_SCHEMA)

    def place(self, ticker: str, side: str, limit_price: float, contracts: float, quotes: dict,
              fair: float | None = None, station: str | None = None, target_date: date | None = None,
              snapshot_id: str | None = None, bet_key: str | None = None, notes: str | None = None,
              now: datetime | None = None) -> dict:
        now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
        if not 0 < limit_price < 1 or contracts <= 0:
            raise ValueError("limit_price in (0,1) and contracts > 0 required")
        f = maker_fill(side, limit_price, quotes, contracts)
        oid = uuid.uuid4().hex
        row = {"id": oid, "ts": now, "ticker": ticker, "station": station, "target_date": target_date,
               "side": side, "limit_price": limit_price, "contracts": contracts, "fair": fair,
               "status": "filled" if f.filled else "resting", "fill_price": f.price, "fee": f.fee,
               "snapshot_id": snapshot_id, "bet_key": bet_key, "settled": None, "pnl": None,
               "notes": json.dumps({"fill": f.reason, **(json.loads(notes) if notes else {})})}
        self.con.execute(
            "INSERT INTO paper_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            list(row.values()))
        return row

    def cancel_resting(self, ticker: str | None = None) -> int:
        sql = "UPDATE paper_orders SET status = 'cancelled' WHERE status = 'resting'"
        params = []
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker)
        rows = self.con.execute(sql, params).fetchall()
        return int(rows[0][0]) if rows else 0

    def orders(self, status: str | None = None) -> pd.DataFrame:
        sql = "SELECT * FROM paper_orders"
        params = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        return self.con.execute(sql + " ORDER BY ts", params).df()

    def open_exposure(self) -> pd.DataFrame:
        """Cost basis of filled, unsettled orders by bet_key."""
        df = self.orders("filled")
        df = df[df.settled.isna()]
        if df.empty:
            return pd.DataFrame(columns=["bet_key", "cost"])
        df["cost"] = df.fill_price * df.contracts + df.fee
        return df.groupby("bet_key", as_index=False)["cost"].sum()

    def settle(self, ticker: str, yes_won: bool) -> int:
        """Mark filled orders on ``ticker`` settled and compute P&L after fees."""
        df = self.orders("filled")
        df = df[(df.ticker == ticker) & df.settled.isna()]
        n = 0
        for r in df.itertuples():
            won = yes_won if r.side == "yes" else not yes_won
            pnl = (r.contracts * (1 - r.fill_price) if won else -r.contracts * r.fill_price) - r.fee
            self.con.execute("UPDATE paper_orders SET settled = ?, pnl = ? WHERE id = ?",
                             [int(yes_won), pnl, r.id])
            n += 1
        return n

    def pnl_summary(self) -> dict:
        df = self.orders("filled")
        done = df[df.settled.notna()]
        return {"filled": int(len(df)), "settled": int(len(done)),
                "pnl": float(done.pnl.sum()) if len(done) else 0.0,
                "fees": float(df.fee.sum()) if len(df) else 0.0,
                "wins": int((done.pnl > 0).sum()) if len(done) else 0}


def resolve_settled(ledger: Ledger, book: PaperBook | None, stations=ACTIVE, **kw) -> int:
    """Resolve ledger rows and paper orders from Kalshi's settled results."""
    pending = ledger.predictions(project="weather", resolved=False)
    open_orders = book.orders("filled") if book is not None else pd.DataFrame(columns=["ticker", "settled"])
    open_orders = open_orders[open_orders.settled.isna()] if len(open_orders) else open_orders
    tickers = set(pending.market_or_asset) | set(open_orders.ticker)
    if not tickers:
        return 0
    n = 0
    for st in stations:
        mine = {t for t in tickers if t.startswith(st.series + "-")}
        if not mine:
            continue
        settled = kx.markets(status="settled", series_ticker=st.series, **kw)
        for _, m in settled.iterrows():
            if m["ticker"] in mine and m.get("result") in ("yes", "no"):
                yes = m["result"] == "yes"
                n += ledger.resolve_market(m["ticker"], yes)
                if book is not None:
                    book.settle(m["ticker"], yes)
    return n
