"""Monthly trend-following backtest with per-asset vol targeting.

Rules (milestone 2 of the brief):
  * hold an asset when its price is above its N-month simple moving average
  * each held asset gets weight (vol_target / n_assets) / realised_vol, capped
  * remaining capital sits in cash (a cash proxy such as BIL, or 0%)
  * weights decided at month-end t apply to returns over month t+1 (no lookahead)

Also produces 60/40 and single-asset benchmarks, a lookback x vol-target
sensitivity grid, and a tax-drag estimate from realised short- and long-term
gains under average-cost accounting.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import product

import numpy as np
import pandas as pd

from shared.sim.metrics import cagr, max_drawdown, sharpe, turnover


@dataclass
class Config:
    lookback: int = 10            # months in the moving average
    vol_target: float = 0.10      # annual portfolio vol budget
    vol_window: int = 12          # months of returns for realised vol
    max_weight: float = 0.60      # per-asset cap
    cash: str | None = "BIL"      # column used as cash return; None = 0%
    periods_per_year: int = 12
    st_tax: float = 0.37          # short-term capital gains rate
    lt_tax: float = 0.20          # long-term capital gains rate
    lt_months: int = 12           # holding period for long-term treatment


@dataclass
class BacktestResult:
    weights: pd.DataFrame         # target weights at each month-end (incl. cash column)
    returns: pd.Series            # portfolio returns for the following month
    equity: pd.Series
    metrics: dict = field(default_factory=dict)
    config: Config | None = None

    def summary(self) -> dict:
        return {**self.metrics, **(asdict(self.config) if self.config else {})}


# -- signals -------------------------------------------------------------------
def trend_signal(prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """True where price is above its trailing ``lookback``-month mean (inclusive)."""
    sma = prices.rolling(lookback, min_periods=lookback).mean()
    return (prices > sma) & sma.notna()


def realised_vol(prices: pd.DataFrame, window: int, periods_per_year: int = 12) -> pd.DataFrame:
    return prices.pct_change().rolling(window, min_periods=window).std() * np.sqrt(periods_per_year)


def target_weights(prices: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Weights per month-end using only data through that month-end."""
    risk_cols = [c for c in prices.columns if c != cfg.cash]
    px = prices[risk_cols]
    sig = trend_signal(px, cfg.lookback)
    vol = realised_vol(px, cfg.vol_window, cfg.periods_per_year)
    n = len(risk_cols)
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = (cfg.vol_target / n) / vol
    w = raw.where(sig, 0.0).clip(lower=0.0, upper=cfg.max_weight).fillna(0.0)
    total = w.sum(axis=1)
    scale = np.where(total > 1.0, 1.0 / total, 1.0)
    w = w.mul(scale, axis=0)
    w["CASH"] = 1.0 - w.sum(axis=1)
    return w


# -- simulation ----------------------------------------------------------------
def _asset_returns(prices: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    r = prices.pct_change()
    r["CASH"] = r[cfg.cash] if cfg.cash and cfg.cash in r else 0.0
    return r


def portfolio_returns(weights: pd.DataFrame, asset_returns: pd.DataFrame) -> pd.Series:
    """Returns realised in month t+1 from weights chosen at t."""
    cols = [c for c in weights.columns if c in asset_returns.columns]
    lagged = weights[cols].shift(1)
    r = (lagged * asset_returns[cols]).sum(axis=1, min_count=1)
    return r[lagged.notna().all(axis=1)]


def tax_drag(weights: pd.DataFrame, asset_returns: pd.DataFrame, cfg: Config,
             start_equity: float = 1.0) -> dict:
    """Estimate annual tax drag from realised gains (average-cost lots).

    Sells realise gains on the sold fraction at the short- or long-term rate
    depending on how long the position has been continuously open. Losses
    carry forward against later gains. Returns taxes as a fraction of average
    equity per year plus the split of short vs long-term gains.
    """
    cols = [c for c in weights.columns if c in asset_returns.columns and c != "CASH"]
    idx = weights.index
    hold = {c: 0.0 for c in cols}       # dollars held
    basis = {c: 0.0 for c in cols}
    opened = {c: None for c in cols}    # position index when opened
    cash = start_equity
    loss_carry = 0.0
    st_gain = lt_gain = tax = 0.0
    equity_path = []
    for i, t in enumerate(idx):
        if i > 0:
            r = asset_returns.loc[t]
            for c in cols:
                hold[c] *= 1 + (0.0 if pd.isna(r[c]) else r[c])
            cash *= 1 + (0.0 if pd.isna(r.get("CASH", 0.0)) else r.get("CASH", 0.0))
        equity = cash + sum(hold.values())
        equity_path.append(equity)
        w = weights.loc[t]
        if w.isna().any():
            continue
        for c in cols:
            target = w[c] * equity
            trade = target - hold[c]
            if trade < -1e-12 and hold[c] > 0:
                frac = min(1.0, -trade / hold[c])
                gain = frac * (hold[c] - basis[c])
                months = i - (opened[c] if opened[c] is not None else i)
                long_term = months >= cfg.lt_months
                if gain >= 0:
                    taxable = max(0.0, gain - loss_carry)
                    loss_carry = max(0.0, loss_carry - gain)
                    if long_term:
                        lt_gain += gain
                    else:
                        st_gain += gain
                    tax += taxable * (cfg.lt_tax if long_term else cfg.st_tax)
                else:
                    loss_carry += -gain
                basis[c] *= 1 - frac
                hold[c] += trade
                cash -= trade
                if hold[c] <= 1e-12:
                    hold[c] = basis[c] = 0.0
                    opened[c] = None
            elif trade > 1e-12:
                if hold[c] <= 1e-12:
                    opened[c] = i
                basis[c] += trade
                hold[c] += trade
                cash -= trade
    years = max((len(idx) - 1) / cfg.periods_per_year, 1e-9)
    avg_equity = float(np.mean(equity_path)) if equity_path else start_equity
    return {
        "tax_drag_annual": tax / years / avg_equity,
        "st_gains": st_gain, "lt_gains": lt_gain, "taxes_paid": tax,
        "st_share": st_gain / (st_gain + lt_gain) if (st_gain + lt_gain) > 0 else float("nan"),
    }


def evaluate(returns: pd.Series, weights: pd.DataFrame | None, cfg: Config) -> dict:
    eq = (1 + returns).cumprod()
    m = {
        "cagr": cagr(np.r_[1.0, eq.to_numpy()], cfg.periods_per_year),
        "max_drawdown": max_drawdown(np.r_[1.0, eq.to_numpy()]),
        "sharpe": sharpe(returns.to_numpy(), cfg.periods_per_year),
        "vol": float(returns.std(ddof=1) * np.sqrt(cfg.periods_per_year)),
        "months": int(len(returns)),
        "start": str(returns.index[0].date()) if len(returns) else None,
        "end": str(returns.index[-1].date()) if len(returns) else None,
    }
    if weights is not None:
        w = weights.loc[returns.index[0]:returns.index[-1]]
        m["turnover_annual"] = turnover(w.drop(columns=["CASH"], errors="ignore")) * cfg.periods_per_year
        m["time_in_cash"] = float(w["CASH"].mean()) if "CASH" in w else float("nan")
    return m


def run_backtest(prices: pd.DataFrame, cfg: Config | None = None) -> BacktestResult:
    """Full pipeline on a month-end price frame (columns = tickers)."""
    cfg = cfg or Config()
    prices = prices.sort_index()
    w = target_weights(prices, cfg)
    ar = _asset_returns(prices, cfg)
    warm = max(cfg.lookback, cfg.vol_window)
    w.iloc[:warm] = np.nan          # not investable before the lookbacks fill
    ret = portfolio_returns(w, ar)
    eq = (1 + ret).cumprod()
    metrics = evaluate(ret, w, cfg)
    metrics.update(tax_drag(w.dropna(), ar, cfg))
    return BacktestResult(weights=w, returns=ret, equity=eq, metrics=metrics, config=cfg)


def fixed_mix(prices: pd.DataFrame, weights: dict[str, float], cfg: Config | None = None,
              start=None) -> BacktestResult:
    """Monthly-rebalanced constant-weight benchmark (e.g. 60/40)."""
    cfg = cfg or Config()
    prices = prices.sort_index()
    if abs(sum(weights.values()) - 1) > 1e-9:
        raise ValueError("weights must sum to 1")
    w = pd.DataFrame({k: v for k, v in weights.items()}, index=prices.index)
    w["CASH"] = 0.0
    ar = _asset_returns(prices, cfg)
    ret = portfolio_returns(w, ar).dropna()
    if start is not None:
        ret = ret.loc[start:]
    eq = (1 + ret).cumprod()
    return BacktestResult(weights=w, returns=ret, equity=eq, metrics=evaluate(ret, w, cfg), config=cfg)


def compare(prices: pd.DataFrame, cfg: Config | None = None, equity: str = "SPY",
            bond: str = "TLT") -> pd.DataFrame:
    """Strategy vs 60/40 vs equity-only over the strategy's investable window."""
    cfg = cfg or Config()
    strat = run_backtest(prices, cfg)
    start = strat.returns.index[0]
    rows = {"strategy": strat.metrics}
    if equity in prices and bond in prices:
        rows["60/40"] = fixed_mix(prices, {equity: 0.6, bond: 0.4}, cfg, start=start).metrics
    if equity in prices:
        rows[equity] = fixed_mix(prices, {equity: 1.0}, cfg, start=start).metrics
    return pd.DataFrame(rows).T


def sensitivity(prices: pd.DataFrame, lookbacks=range(3, 13),
                vol_targets=(0.05, 0.075, 0.10, 0.125, 0.15, 0.20),
                base: Config | None = None) -> pd.DataFrame:
    base = base or Config()
    rows = []
    for lb, vt in product(lookbacks, vol_targets):
        cfg = Config(**{**asdict(base), "lookback": lb, "vol_target": vt})
        m = run_backtest(prices, cfg).metrics
        rows.append({"lookback": lb, "vol_target": vt, **{k: m[k] for k in
                     ("cagr", "max_drawdown", "sharpe", "turnover_annual", "tax_drag_annual")}})
    return pd.DataFrame(rows)


def kill_signals(comparison: pd.DataFrame, cost_bps_per_turn: float = 10.0) -> dict:
    """Brief's kill signals: worse risk-adjusted than 60/40; costs above 50 bps a year."""
    out = {}
    if "60/40" in comparison.index:
        out["underperforms_60_40_risk_adjusted"] = bool(
            comparison.loc["strategy", "sharpe"] < comparison.loc["60/40", "sharpe"])
    cost = comparison.loc["strategy", "turnover_annual"] * 2 * cost_bps_per_turn  # round trip
    out["implied_cost_bps"] = float(cost)
    out["costs_above_50bps"] = bool(cost > 50)
    return out
