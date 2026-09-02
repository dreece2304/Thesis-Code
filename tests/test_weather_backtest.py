from datetime import date

import numpy as np
import pandas as pd
import pytest

from prediction.weather import backtest as B
from prediction.weather import market_model as MM
from prediction.weather.evaluation import calibration, go_live_gate, paired_bootstrap
from prediction.weather.stations import LEADS, MODELS


def synthetic_archive(days=560, stations=("NYC", "CHI", "MIA"), seed=0, common_sd=2.0, own_sd=1.0):
    """Models share a common error (the weather uncertainty) plus a small own error."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-06-01", periods=days, freq="D")
    rows = []
    for st in stations:
        truth = 75 + 10 * np.sin(2 * np.pi * dates.dayofyear / 365) + rng.normal(0, 6, days)
        season = 1.0 + 0.5 * np.cos(2 * np.pi * dates.dayofyear / 365)   # winter errors larger
        common = {lead: rng.normal(0, 1, days) * (common_sd + 0.7 * lead) * season for lead in LEADS}
        for model in MODELS:
            bias = {"ecmwf_ifs025": 0.0, "gfs_seamless": 2.0, "icon_seamless": -1.0}[model]
            for lead in LEADS:
                fc = truth - bias + common[lead] + rng.normal(0, own_sd, days)
                rows.append(pd.DataFrame({"station": st, "target_date": dates, "lead": lead, "model": model,
                                          "forecast": fc, "settlement": np.round(truth)}))
    a = pd.concat(rows, ignore_index=True)
    a["error"] = a.settlement - a.forecast
    return a


def test_market_model_helpers():
    assert MM.baseline_probability(80, 81, "above") + MM.baseline_probability(80, 80, "below") == pytest.approx(1.0)
    assert MM.baseline_probability(80, 90, "above") < 0.01
    rng = np.random.default_rng(0)
    for p in (0.02, 0.5, 0.98):
        bid, ask, mid = MM.reconstructed_quotes(p, rng)
        assert 0 < bid < ask < 1 and bid <= mid <= ask


def test_evaluation_helpers():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 500)
    good = np.clip(y * 0.8 + 0.1 + rng.normal(0, 0.05, 500), 0, 1)
    bad = np.full(500, 0.5)
    b = paired_bootstrap(good, bad, y)
    assert b["diff"] > 0 and b["excludes_zero"] and b["ci_lo"] > 0
    assert paired_bootstrap(bad, bad, y)["excludes_zero"] is False
    assert paired_bootstrap([], [], [])["n"] == 0
    c = calibration(good, y)
    assert c.n.sum() == 500
    g = go_live_gate(good, bad, y, pnl_after_fees=10.0)
    assert g["passes"] and g["reason"] == "ok"
    assert go_live_gate(good, bad, y, pnl_after_fees=-1.0)["passes"] is False
    assert "need 200" in go_live_gate(good[:50], bad[:50], y[:50], 5.0)["reason"]


def test_backtest_runs_and_beats_noisy_market():
    a = synthetic_archive(days=480)
    cfg = B.BacktestConfig(warmup_months=6, max_months=2, seed=1)
    rep = B.run_backtest(a, cfg)
    s = rep.summary
    assert s["n_predictions"] > 0 and s["n_city_days"] > 0
    assert set(s["brier"]) == {"pooled", "NYC", "CHI", "MIA"}
    pooled = s["brier"]["pooled"]
    assert pooled["brier_ours"] < pooled["brier_market"]
    assert pooled["brier_ours"] < pooled["brier_baseline"]
    assert rep.predictions.p_ours.between(0, 1).all()
    assert len(rep.equity) > 0 and abs(rep.equity.iloc[-1] - (cfg.bankroll + s["pnl"])) < 1e-6
    md = rep.to_markdown()
    assert "Brier ours" in md and "gate:" in md
    if s["n_trades"]:
        t = rep.trades[rep.trades.filled & (rep.trades.contracts > 0)]
        assert (t.stake <= cfg.cap_bet * cfg.bankroll * 1.5).all()  # bankroll drifts a little
        assert t.decision_date.lt(t.target_date).all()


def test_backtest_no_lookahead():
    a = synthetic_archive(days=420)
    cfg = B.BacktestConfig(warmup_months=6, max_months=2, seed=3)
    base = B.run_backtest(a, cfg)
    first_month = base.predictions.target_date.dt.to_period("M").min()
    cutoff = (first_month + 1).to_timestamp()
    tampered = a.copy()
    late = tampered.target_date >= cutoff
    tampered.loc[late, "settlement"] += 30
    tampered.loc[late, "error"] += 30
    rep = B.run_backtest(tampered, cfg)
    p0 = base.predictions[base.predictions.target_date < cutoff].reset_index(drop=True)
    p1 = rep.predictions[rep.predictions.target_date < cutoff].reset_index(drop=True)
    pd.testing.assert_frame_equal(p0, p1)
