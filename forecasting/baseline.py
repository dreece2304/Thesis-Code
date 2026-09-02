"""Milestone 2: market-implied baseline, log-odds combination, and the Brier gate.

Every model must beat the market-implied probability on Brier over enough
resolved predictions or it is not used. ``beats_market`` is the gate.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from shared.ledger import Ledger, brier_score

EPS = 1e-4


def market_implied(yes_bid: float | None, yes_ask: float | None, last: float | None = None) -> float | None:
    """Mid of the yes book, else last trade. Prices in dollars."""
    b = None if yes_bid is None or (isinstance(yes_bid, float) and math.isnan(yes_bid)) else yes_bid
    a = None if yes_ask is None or (isinstance(yes_ask, float) and math.isnan(yes_ask)) else yes_ask
    if b is not None and a is not None and 0 < b <= a < 1:
        return (b + a) / 2
    if last is not None and not (isinstance(last, float) and math.isnan(last)) and 0 < last < 1:
        return float(last)
    return None


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def inv_logit(x):
    return 1 / (1 + np.exp(-np.asarray(x, dtype=float)))


def combine(p_model, p_market, shrink: float = 0.5):
    """Log-odds average. ``shrink`` is the weight on the market (1 = market only)."""
    if not 0 <= shrink <= 1:
        raise ValueError("shrink must be in [0, 1]")
    return inv_logit((1 - shrink) * logit(p_model) + shrink * logit(p_market))


def tune_shrinkage(p_model, p_market, outcomes, grid=None) -> tuple[float, pd.DataFrame]:
    """Pick the shrink that minimises Brier on resolved predictions."""
    grid = np.linspace(0, 1, 21) if grid is None else np.asarray(grid)
    p_model, p_market, y = map(lambda a: np.asarray(a, dtype=float), (p_model, p_market, outcomes))
    rows = [{"shrink": float(s), "brier": brier_score(combine(p_model, p_market, s), y)} for s in grid]
    table = pd.DataFrame(rows)
    return float(table.loc[table.brier.idxmin(), "shrink"]), table


def beats_market(ledger: Ledger, project: str, min_n: int = 200) -> dict:
    """Gate: model Brier below market Brier on >= min_n resolved rows with both."""
    df = ledger.predictions(project=project, resolved=True).dropna(subset=["market_prob"])
    n = int(len(df))
    if n == 0:
        return {"project": project, "n": 0, "brier_model": float("nan"),
                "brier_market": float("nan"), "passes": False, "reason": "no resolved rows"}
    bm = brier_score(df.model_prob, df.outcome)
    bk = brier_score(df.market_prob, df.outcome)
    passes = n >= min_n and bm < bk
    reason = "ok" if passes else (f"need {min_n} rows, have {n}" if n < min_n else "model not better than market")
    return {"project": project, "n": n, "brier_model": bm, "brier_market": bk,
            "passes": bool(passes), "reason": reason}
