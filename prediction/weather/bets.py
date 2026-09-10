"""Track the small real bets Duncan places by hand, and score them.

This is a record, not an order path: nothing here talks to the exchange
except to read settlement results. Bets live in a ``manual_bets`` table in
the weather ledger. ``report`` gives hit rate, P&L after fees, and Brier of
the model probability we had at the time against the outcome, so the daily
bets double as calibration data.

    python -m prediction.weather.bets add KXRAIN-26SEP11-DC yes 0.72 5 --p 0.90 --note "rain model"
    python -m prediction.weather.bets settle
    python -m prediction.weather.bets report
"""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone

import pandas as pd

from shared.data import kalshi as kx
from shared.ledger import Ledger, brier_score

from ..fees import kalshi_fee
from .live import weather_ledger_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS manual_bets (
    id          VARCHAR PRIMARY KEY,
    ts          TIMESTAMP NOT NULL,
    ticker      VARCHAR NOT NULL,
    side        VARCHAR NOT NULL,     -- 'yes' or 'no'
    price       DOUBLE NOT NULL,      -- paid per contract, dollars
    contracts   DOUBLE NOT NULL,
    fee         DOUBLE NOT NULL,
    model_p     DOUBLE,               -- our P(YES) at the time, if any
    market_p    DOUBLE,               -- market P(YES) at the time, if any
    category    VARCHAR,
    note        VARCHAR,
    settled     INTEGER,              -- 1 YES, 0 NO, NULL open
    settled_at  TIMESTAMP,
    pnl         DOUBLE
);
"""


def _category(ticker: str) -> str:
    t = ticker.upper()
    if t.startswith("KXRAIN"):
        return "rain"
    if t.startswith("KXHIGH") or t.startswith("KXLOW"):
        return "temperature"
    if "FED" in t or "EFFR" in t:
        return "fed"
    if "HUR" in t:
        return "hurricane"
    return "other"


class Bets:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger
        self.con = ledger.con
        self.con.execute(SCHEMA)

    def add(self, ticker: str, side: str, price: float, contracts: float, model_p: float | None = None,
            market_p: float | None = None, note: str | None = None, ts: datetime | None = None,
            maker: bool = True) -> dict:
        side = side.lower()
        if side not in ("yes", "no"):
            raise ValueError("side must be yes or no")
        if not 0 < price < 1 or contracts <= 0:
            raise ValueError("price in (0,1) and contracts > 0")
        ts = (ts or datetime.now(timezone.utc)).replace(tzinfo=None)
        fee = kalshi_fee(price, contracts, maker=maker)
        row = {"id": uuid.uuid4().hex, "ts": ts, "ticker": ticker, "side": side, "price": float(price),
               "contracts": float(contracts), "fee": fee, "model_p": model_p, "market_p": market_p,
               "category": _category(ticker), "note": note, "settled": None, "settled_at": None, "pnl": None}
        self.con.execute("INSERT INTO manual_bets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(row.values()))
        return row

    def frame(self) -> pd.DataFrame:
        return self.con.execute("SELECT * FROM manual_bets ORDER BY ts").df()

    def settle_one(self, ticker: str, yes_won: bool, when: datetime | None = None) -> int:
        when = (when or datetime.now(timezone.utc)).replace(tzinfo=None)
        df = self.frame()
        df = df[(df.ticker == ticker) & df.settled.isna()]
        for r in df.itertuples():
            won = yes_won if r.side == "yes" else not yes_won
            pnl = (r.contracts * (1 - r.price) if won else -r.contracts * r.price) - r.fee
            self.con.execute("UPDATE manual_bets SET settled = ?, settled_at = ?, pnl = ? WHERE id = ?",
                             [int(yes_won), when, pnl, r.id])
        return int(len(df))

    def settle_from_kalshi(self, **kw) -> int:
        df = self.frame()
        open_ = df[df.settled.isna()]
        n = 0
        for ticker in open_.ticker.unique():
            try:
                m = kx.market(ticker)
            except Exception:
                continue
            if m.get("status") in ("settled", "finalized") and m.get("result") in ("yes", "no"):
                n += self.settle_one(ticker, m["result"] == "yes")
        return n

    def report(self) -> dict:
        df = self.frame()
        done = df.dropna(subset=["settled"])
        out = {"bets": int(len(df)), "settled": int(len(done)), "open": int(len(df) - len(done))}
        if len(done):
            won = done.pnl > 0
            out.update({"hit_rate": float(won.mean()), "pnl": float(done.pnl.sum()),
                        "staked": float((done.price * done.contracts).sum()),
                        "fees": float(done.fee.sum())})
            m = done.dropna(subset=["model_p"])
            if len(m):
                out["brier_model"] = brier_score(m.model_p, m.settled)
            k = done.dropna(subset=["market_p"])
            if len(k):
                out["brier_market"] = brier_score(k.market_p, k.settled)
            out["by_category"] = {c: {"n": int(len(g)), "hit_rate": float((g.pnl > 0).mean()), "pnl": float(g.pnl.sum())}
                                  for c, g in done.groupby("category")}
        return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("ticker"); a.add_argument("side"); a.add_argument("price", type=float); a.add_argument("contracts", type=float)
    a.add_argument("--p", type=float, help="our P(YES) at the time"); a.add_argument("--market", type=float)
    a.add_argument("--note"); a.add_argument("--taker", action="store_true", help="crossed the spread (taker fee)")
    sub.add_parser("settle"); sub.add_parser("report"); sub.add_parser("list")
    args = ap.parse_args(argv)
    with Ledger(weather_ledger_path()) as L:
        b = Bets(L)
        if args.cmd == "add":
            print(json.dumps(b.add(args.ticker, args.side, args.price, args.contracts, args.p, args.market, args.note,
                                   maker=not args.taker), default=str))
        elif args.cmd == "settle":
            print("settled", b.settle_from_kalshi())
        elif args.cmd == "list":
            print(b.frame().to_string())
        else:
            print(json.dumps(b.report(), indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
