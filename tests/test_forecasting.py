import numpy as np
import pandas as pd
import pytest

from forecasting import baseline, data
from shared.data import fred, prices
from shared.ledger import Ledger


def _fake_series(sid, start=None, end=None, **kw):
    idx = pd.date_range("2020-01-01", periods=730, freq="D")
    base = {"VIXCLS": 20.0, "VXVCLS": 22.0}.get(sid, 100.0)
    vals = base + np.arange(len(idx)) * 0.01
    return pd.DataFrame({"value": vals}, index=idx.rename("date"))


def test_macro_panel_and_vix(monkeypatch):
    monkeypatch.setattr(fred, "series", _fake_series)
    m = data.macro_panel(start="2020-01-01")
    assert set(data.MACRO_SERIES) <= set(m.columns)
    assert m.index.freqstr in ("ME", "M") or m.index[1].is_month_end
    assert "cpi_yoy" in m and "curve_10y_2y" in m
    assert m["curve_10y_2y"].abs().max() < 1e-9  # identical fake series
    ts = data.vix_term_structure(start="2020-01-01")
    assert ts.ratio.iloc[0] == pytest.approx(20 / 22)


def test_realised_vol_and_regime_features(monkeypatch):
    idx = pd.date_range("2020-01-01", periods=500, freq="B")
    rng = np.random.default_rng(0)
    px = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))), index=idx)
    rv = data.realised_vol(px, 21)
    assert rv.dropna().mean() == pytest.approx(0.01 * np.sqrt(252), rel=0.15)
    monkeypatch.setattr(prices, "daily_prices", lambda t, start=None, **kw: px.to_frame("SPY"))
    monkeypatch.setattr(fred, "series", _fake_series)
    f = data.regime_features(start="2020-01-01")
    assert {"ret", "rvol", "vix", "vix_ratio", "next_rvol"} <= set(f.columns)
    assert f.next_rvol.iloc[:-1].tolist() == f.rvol.iloc[1:].tolist()


def test_market_implied():
    assert baseline.market_implied(0.40, 0.50) == pytest.approx(0.45)
    assert baseline.market_implied(None, None, 0.3) == 0.3
    assert baseline.market_implied(float("nan"), 0.5, float("nan")) is None
    assert baseline.market_implied(0.6, 0.5) is None  # crossed book


def test_combine_and_tune():
    pm, pk = np.array([0.9, 0.2]), np.array([0.5, 0.5])
    assert baseline.combine(pm, pk, 0.0) == pytest.approx(pm)
    assert baseline.combine(pm, pk, 1.0) == pytest.approx(pk)
    mid = baseline.combine(pm, pk, 0.5)
    assert 0.5 < mid[0] < 0.9 and 0.2 < mid[1] < 0.5
    with pytest.raises(ValueError):
        baseline.combine(pm, pk, 1.5)
    # model is pure noise, market is calibrated: tuning should go to the market
    rng = np.random.default_rng(1)
    p_true = rng.uniform(0.05, 0.95, 2000)
    y = (rng.uniform(size=2000) < p_true).astype(int)
    noise = rng.uniform(0.05, 0.95, 2000)
    s, table = baseline.tune_shrinkage(noise, p_true, y)
    assert s >= 0.9 and table.brier.iloc[-1] < table.brier.iloc[0]
    # model perfect, market noisy: tuning should go to the model
    s2, _ = baseline.tune_shrinkage(y * 0.98 + 0.01, noise, y)
    assert s2 <= 0.1


def test_beats_market_gate():
    with Ledger(":memory:") as L:
        r = baseline.beats_market(L, "prediction")
        assert r["passes"] is False and r["n"] == 0
        rng = np.random.default_rng(2)
        for i in range(250):
            y = int(rng.uniform() < 0.6)
            L.log_prediction("prediction", f"m{i}", model_prob=0.9 if y else 0.1,
                             market_prob=0.5, outcome=y)
        r = baseline.beats_market(L, "prediction", min_n=200)
        assert r["passes"] is True and r["brier_model"] < r["brier_market"]
        assert baseline.beats_market(L, "prediction", min_n=300)["passes"] is False
