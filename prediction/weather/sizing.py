"""Quarter-Kelly sizing with per-bet and total caps and correlation grouping."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared.sim.kelly import fractional_kelly, kelly_binary_contract

from ..fees import fee_per_contract

KELLY_MULT = 0.25
CAP_PER_BET = 0.05
CAP_TOTAL = 0.15
CORR_THRESHOLD = 0.5
CORR_WINDOW_DAYS = 30
PAPER_BANKROLL = 2000.0


@dataclass
class Size:
    fraction: float      # of bankroll, after caps
    stake: float         # dollars at risk (price + fee) x contracts
    contracts: int
    kelly_full: float
    capped_by: str | None


def size_bet(p: float, price: float, bankroll: float, existing_bet_stake: float = 0.0,
             existing_total_stake: float = 0.0, multiplier: float = KELLY_MULT,
             cap_bet: float = CAP_PER_BET, cap_total: float = CAP_TOTAL, maker: bool = True) -> Size:
    """Contracts to buy at ``price`` given our probability ``p``.

    Caps are on total cost (price plus fee) as a fraction of bankroll:
    ``cap_bet`` for one bet key (city-day or correlated group) and ``cap_total``
    across all open bets; existing stakes are subtracted first.
    """
    fee = fee_per_contract(price, contracts=100, maker=maker)
    f_full = kelly_binary_contract(p, price, fee)
    f = fractional_kelly(f_full, multiplier)
    capped = None
    room_bet = max(0.0, cap_bet - existing_bet_stake / bankroll)
    room_total = max(0.0, cap_total - existing_total_stake / bankroll)
    if f > room_bet:
        f, capped = room_bet, "per_bet"
    if f > room_total:
        f, capped = room_total, "total"
    cost = price + fee
    contracts = int(np.floor(f * bankroll / cost)) if cost > 0 else 0
    stake = contracts * cost
    return Size(stake / bankroll if bankroll else 0.0, stake, contracts, f_full, capped)


def correlation_groups(errors_wide: pd.DataFrame, asof=None, window_days: int = CORR_WINDOW_DAYS,
                       threshold: float = CORR_THRESHOLD, min_days: int = 10) -> list[set[str]]:
    """Union-find groups of stations whose ensemble-mean errors correlate above ``threshold``.

    ``errors_wide`` is indexed by date with one column per station.
    """
    df = errors_wide.copy()
    df.index = pd.to_datetime(df.index)
    if asof is not None:
        asof = pd.Timestamp(asof)
        df = df[(df.index < asof) & (df.index >= asof - pd.Timedelta(days=window_days))]
    cols = list(df.columns)
    parent = {c: c for c in cols}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    if len(df.dropna(how="all")) >= min_days:
        corr = df.corr(min_periods=min_days)
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                c = corr.loc[a, b]
                if pd.notna(c) and c > threshold:
                    parent[find(a)] = find(b)
    groups: dict[str, set[str]] = {}
    for c in cols:
        groups.setdefault(find(c), set()).add(c)
    return sorted(groups.values(), key=lambda s: sorted(s))


def bet_key(station: str, target_date, groups: list[set[str]] | None = None) -> str:
    """City-day key; correlated cities on the same day share a key."""
    name = station
    for g in groups or []:
        if station in g and len(g) > 1:
            name = "+".join(sorted(g))
            break
    return f"{name}:{pd.Timestamp(target_date).date()}"
