import numpy as np
import pandas as pd
import pytest

from investing import backtest as bt
from investing.overlay import MIN_REGIME_ACCURACY, RegimeGateError, regime_scale
from shared.sim.rng import SeededRNG


def _prices(n=120, seed=0):
    rng = SeededRNG(seed)
    idx = pd.date_range("2000-01-31", periods=n, freq="ME")
    up = 100 * np.cumprod(1 + rng.normal(0.01, 0.03, n))        # trending up, 10% vol
    up_hi = 100 * np.cumprod(1 + rng.normal(0.01, 0.06, n))     # trending up, 20% vol
    down = 100 * np.cumprod(1 - 0.01 + rng.normal(0, 0.02, n))  # trending down
    cash = 100 * np.cumprod(np.full(n, 1 + 0.002))              # 2.4% a year
    return pd.DataFrame({"SPY": up, "QQQ": up_hi, "TLT": down, "BIL": cash}, index=idx)


def test_trend_signal_and_weights():
    px = _prices()
    cfg = bt.Config(lookback=10, vol_window=12, vol_target=0.10, max_weight=1.0)
    sig = bt.trend_signal(px[["SPY", "TLT"]], 10)
    assert not sig.iloc[:9].any().any()                    # warmup
    assert sig["SPY"].iloc[20:].mean() > 0.8
    assert sig["TLT"].iloc[20:].mean() < 0.2
    w = bt.target_weights(px, cfg)
    assert set(w.columns) == {"SPY", "QQQ", "TLT", "CASH"}
    assert (w.sum(axis=1) - 1).abs().max() < 1e-9
    assert (w >= -1e-12).all().all()
    late = w.iloc[24:]
    assert late["TLT"].mean() < 0.05
    # per-asset vol targeting: the 2x vol asset gets about half the weight when both held
    both = late[(late.SPY > 0) & (late.QQQ > 0)]
    ratio = (both.QQQ / both.SPY).median()
    assert 0.3 < ratio < 0.8


def test_no_lookahead():
    px = _prices()
    cfg = bt.Config()
    full = bt.target_weights(px, cfg)
    trunc = bt.target_weights(px.iloc[:80], cfg)
    pd.testing.assert_frame_equal(full.iloc[:80], trunc)
    # perturbing future prices changes nothing before the perturbation
    px2 = px.copy()
    px2.iloc[90:] *= 0.5
    pd.testing.assert_frame_equal(bt.target_weights(px2, cfg).iloc[:90], full.iloc[:90])


def test_returns_use_lagged_weights():
    idx = pd.date_range("2020-01-31", periods=3, freq="ME")
    w = pd.DataFrame({"A": [1.0, 0.0, 0.0], "CASH": [0.0, 1.0, 1.0]}, index=idx)
    ar = pd.DataFrame({"A": [np.nan, 0.10, -0.50], "CASH": [np.nan, 0.0, 0.0]}, index=idx)
    r = bt.portfolio_returns(w, ar)
    assert r.tolist() == pytest.approx([0.10, 0.0])  # month 2 was all cash


def test_run_backtest_metrics_and_benchmarks():
    px = _prices(n=180)
    res = bt.run_backtest(px, bt.Config())
    m = res.metrics
    assert m["months"] > 150
    assert m["cagr"] > 0 and 0 <= m["max_drawdown"] < 0.5
    assert m["turnover_annual"] >= 0 and 0 <= m["time_in_cash"] <= 1
    assert 0 <= m["tax_drag_annual"] < 0.1
    assert res.equity.iloc[-1] == pytest.approx((1 + res.returns).prod())
    comp = bt.compare(px, bt.Config())
    assert set(comp.index) == {"strategy", "60/40", "SPY"}
    assert comp.loc["SPY", "months"] == comp.loc["strategy", "months"]
    ks = bt.kill_signals(comp)
    assert set(ks) >= {"underperforms_60_40_risk_adjusted", "implied_cost_bps", "costs_above_50bps"}
    with pytest.raises(ValueError):
        bt.fixed_mix(px, {"SPY": 0.5})


def test_tax_drag_short_vs_long():
    idx = pd.date_range("2020-01-31", periods=30, freq="ME")
    ar = pd.DataFrame({"A": [np.nan] + [0.05] * 29, "CASH": 0.0}, index=idx)
    cfg = bt.Config(st_tax=0.4, lt_tax=0.2, lt_months=12)
    # buy at t0, sell everything at t3: short-term
    w = pd.DataFrame({"A": [1.0, 1.0, 1.0, 0.0] + [0.0] * 26, "CASH": [0.0, 0.0, 0.0, 1.0] + [1.0] * 26}, index=idx)
    st = bt.tax_drag(w, ar, cfg)
    assert st["st_gains"] > 0 and st["lt_gains"] == 0
    assert st["taxes_paid"] == pytest.approx(0.4 * st["st_gains"])
    # hold 20 months then sell: long-term
    w2 = pd.DataFrame({"A": [1.0] * 20 + [0.0] * 10, "CASH": [0.0] * 20 + [1.0] * 10}, index=idx)
    lt = bt.tax_drag(w2, ar, cfg)
    assert lt["lt_gains"] > 0 and lt["st_gains"] == 0 and lt["st_share"] == 0
    assert lt["taxes_paid"] == pytest.approx(0.2 * lt["lt_gains"])


def test_sensitivity_grid_shape():
    px = _prices(n=100)
    s = bt.sensitivity(px, lookbacks=(3, 6), vol_targets=(0.05, 0.2))
    assert len(s) == 4 and {"cagr", "sharpe", "turnover_annual"} <= set(s.columns)


def test_regime_gate():
    assert regime_scale(None, None) == 1.0
    assert regime_scale(2, 0.7) == 0.5
    assert regime_scale(0, MIN_REGIME_ACCURACY) == 1.0
    with pytest.raises(RegimeGateError):
        regime_scale(1, 0.59)
    with pytest.raises(RegimeGateError):
        regime_scale(1, None)
    with pytest.raises(RegimeGateError):
        regime_scale(7, 0.9)
