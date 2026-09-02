"""Performance metrics for equity curves and return series."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _arr(x) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if a.ndim != 1:
        raise ValueError("expected a 1-D series")
    return a


def cagr(equity, periods_per_year: int) -> float:
    """Compound annual growth rate from an equity curve (first to last value)."""
    e = _arr(equity)
    if len(e) < 2 or e[0] <= 0:
        return float("nan")
    years = (len(e) - 1) / periods_per_year
    if years <= 0:
        return float("nan")
    return float((e[-1] / e[0]) ** (1.0 / years) - 1.0)


def drawdown_series(equity) -> np.ndarray:
    """Drawdown from running peak as a non-negative fraction (0.2 = 20% below peak)."""
    e = _arr(equity)
    peak = np.maximum.accumulate(e)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, 1.0 - e / peak, 0.0)
    return dd


def max_drawdown(equity) -> float:
    """Largest peak-to-trough decline as a positive fraction."""
    e = _arr(equity)
    if len(e) == 0:
        return float("nan")
    return float(np.max(drawdown_series(e)))


def annualised_vol(returns, periods_per_year: int) -> float:
    r = _arr(returns)
    if len(r) < 2:
        return float("nan")
    return float(np.std(r, ddof=1) * np.sqrt(periods_per_year))


def sharpe(returns, periods_per_year: int, rf_per_period: float = 0.0) -> float:
    """Annualised Sharpe ratio of per-period simple returns."""
    r = _arr(returns) - rf_per_period
    if len(r) < 2:
        return float("nan")
    sd = np.std(r, ddof=1)
    if sd == 0:
        return float("nan")
    return float(np.mean(r) / sd * np.sqrt(periods_per_year))


def turnover(weights: pd.DataFrame) -> float:
    """Average one-way turnover per period from a weights matrix (rows = periods).

    Sum of absolute weight changes per period, halved, averaged over periods.
    Multiply by periods per year for annual turnover.
    """
    w = pd.DataFrame(weights).fillna(0.0)
    if len(w) < 2:
        return 0.0
    return float(w.diff().abs().sum(axis=1).iloc[1:].mean() / 2.0)
