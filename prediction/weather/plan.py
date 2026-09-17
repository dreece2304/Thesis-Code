"""Turn today's screens into a sized bet list under a daily budget.

Sizing is expected-gain based: each candidate gets a quarter-Kelly stake on
our probability against the limit price (maker fee included), the stakes are
scaled down together so the day's total never exceeds the budget, and no
single bet takes more than half of it. Candidates need a gap of at least
``min_edge`` after fees and, for weather, at least one independent source
agreeing (the caller passes that flag; the model does not grade itself).

Budget schedule (``budget_for``): $20 a day until 50 tracked bets have
settled with positive P&L and a Brier no worse than the market, then $40,
then $80 at 150. It never rises on paper results, only on tracked bets.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from shared.sim.kelly import fractional_kelly, kelly_binary_contract

from ..fees import fee_per_contract

MIN_EDGE = 0.08
KELLY_MULT = 0.25
MAX_SHARE = 0.5
SCHEDULE = [(0, 20.0), (50, 40.0), (150, 80.0)]


def budget_for(settled: int, pnl: float, brier_ours: float | None, brier_market: float | None) -> float:
    """Daily budget from the tracked record. Rises only with count, positive P&L and no worse Brier."""
    budget = SCHEDULE[0][1]
    for n, b in SCHEDULE[1:]:
        ok = settled >= n and pnl > 0 and (brier_ours is None or brier_market is None or brier_ours <= brier_market)
        if ok:
            budget = b
    return budget


@dataclass
class Candidate:
    ticker: str
    side: str            # 'yes' or 'no'
    p_side: float        # our probability that this side wins
    limit: float         # price we would pay per contract
    reason: str = ""
    agrees: bool = True  # an independent source supports our lean
    edge: float = field(init=False)

    def __post_init__(self):
        fee = fee_per_contract(self.limit, 100, maker=True)
        self.edge = self.p_side - self.limit - fee


def size(cands: list[Candidate], budget: float, min_edge: float = MIN_EDGE) -> pd.DataFrame:
    rows = []
    for c in cands:
        if c.edge < min_edge or not c.agrees or not 0 < c.limit < 1:
            continue
        f = fractional_kelly(kelly_binary_contract(c.p_side, c.limit, fee_per_contract(c.limit, 100, maker=True)), KELLY_MULT)
        rows.append({"ticker": c.ticker, "side": c.side, "limit": c.limit, "p": round(c.p_side, 3),
                     "edge": round(c.edge, 3), "kelly_frac": f, "reason": c.reason})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # allocate in proportion to Kelly fraction, cap each at MAX_SHARE of budget, fit inside budget
    raw = df.kelly_frac / df.kelly_frac.sum() * budget
    df["stake"] = raw.clip(upper=MAX_SHARE * budget)
    scale = min(1.0, budget / df.stake.sum()) if df.stake.sum() > 0 else 0.0
    df["stake"] = (df.stake * scale).round(2)
    df["contracts"] = (df.stake / df.limit).astype(int)
    df = df[df.contracts > 0].copy()
    df["stake"] = (df.contracts * df.limit).round(2)
    df["expected_gain"] = (df.contracts * (df.p * (1 - df.limit) - (1 - df.p) * df.limit)
                           - df.contracts * df.limit.map(lambda x: fee_per_contract(x, 100, maker=True))).round(2)
    return df.sort_values("edge", ascending=False).reset_index(drop=True)


def from_rain_screen(screen: pd.DataFrame, agree: dict[str, bool] | None = None) -> list[Candidate]:
    """Candidates from ``rain.screen`` output: buy the side we favour at the touch."""
    out = []
    for r in screen.itertuples():
        if getattr(r, "locked", False):
            continue
        mid = (r.yes_bid + r.yes_ask) / 2 if pd.notna(r.yes_bid) and pd.notna(r.yes_ask) else None
        if mid is not None and (mid >= 0.95 or mid <= 0.05) and abs(r.p - mid) > 0.3:
            continue  # the market already knows the outcome and our gauge feed missed it
        agree_flag = True if agree is None else agree.get(r.ticker, False)
        if pd.notna(r.yes_ask) and 0 < r.yes_ask < 1:
            out.append(Candidate(r.ticker, "yes", float(r.p), float(r.yes_ask), f"{r.city} rain p={r.p:.2f}", agree_flag))
        if pd.notna(r.yes_bid) and 0 < r.yes_bid < 1:
            out.append(Candidate(r.ticker, "no", 1 - float(r.p), round(1 - float(r.yes_bid), 2), f"{r.city} dry p={1-r.p:.2f}", agree_flag))
    return out


def main(argv=None) -> int:
    from shared.ledger import Ledger

    from . import bets as BT
    from . import rain as R
    from .live import weather_ledger_path

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=float, help="override the schedule")
    ap.add_argument("--min-edge", type=float, default=MIN_EDGE)
    ap.add_argument("--agree", help="JSON {ticker: true/false} from an independent-source check", default=None)
    a = ap.parse_args(argv)
    with Ledger(weather_ledger_path()) as L:
        rep = BT.Bets(L).report()
    budget = a.budget or budget_for(rep.get("settled", 0), rep.get("pnl", 0.0), rep.get("brier_model"), rep.get("brier_market"))
    agree = json.loads(a.agree) if a.agree else None
    screen = R.screen(R.load_fits(), now=datetime.now(timezone.utc))
    df = size(from_rain_screen(screen, agree), budget, a.min_edge)
    print(f"budget ${budget:.0f} (tracked bets settled: {rep.get('settled', 0)})")
    print(df.to_string(index=False) if len(df) else "no candidates clear the edge and agreement filters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
