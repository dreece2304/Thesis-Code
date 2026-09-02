from datetime import date

import numpy as np
import pandas as pd
import pytest

from prediction.weather import archive as A
from prediction.weather import errors as E
from prediction.weather.stations import STATIONS
from shared.data import ghcn, open_meteo


def _hourly(start="2025-01-01", days=3):
    t = pd.date_range(start, periods=24 * days, freq="h")
    df = pd.DataFrame(index=t)
    df["temperature_2m"] = 60 + 10 * (t.hour == 15)
    for k in range(1, 6):
        df[f"temperature_2m_previous_day{k}"] = 60 + 10 * (t.hour == 15) + k
    return df


def test_daily_max_by_lead():
    d = A.daily_max_by_lead(_hourly())
    assert set(d.lead) == {0, 1, 2, 3, 4, 5} and len(d) == 18
    assert d[(d.lead == 3)].forecast.tolist() == [73.0] * 3
    short = _hourly(days=1).iloc[:10]
    assert A.daily_max_by_lead(short).empty   # fewer than 20 hours


def _stub_archive_sources(monkeypatch, days=800, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    truth = 70 + 15 * np.sin(2 * np.pi * (dates.dayofyear / 365)) + rng.normal(0, 5, days)

    def prev_runs(lat, lon, start, end, variable, model, previous_days, timezone, **kw):
        t = pd.date_range(dates[0], periods=24 * days, freq="h")
        df = pd.DataFrame(index=t)
        bias = {"ecmwf_ifs025": 0.0, "gfs_seamless": 1.5, "icon_seamless": -1.0}[model]
        daily = np.repeat(truth, 24)
        df[variable] = daily - 5 + 5 * (t.hour == 15) - bias + np.repeat(rng.normal(0, 1.0, days), 24)
        for k in range(1, previous_days + 1):
            df[f"{variable}_previous_day{k}"] = daily - 5 + 5 * (t.hour == 15) - bias + np.repeat(rng.normal(0, 1.5 + 0.5 * k, days), 24)
        mask = (df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end) + pd.Timedelta(days=1))
        return df[mask]

    def daily(station_id, start, end, datatypes=("TMAX",), **kw):
        s = pd.Series(np.round(truth), index=dates.rename("DATE"), name="TMAX")
        return s.loc[str(start):str(end)].to_frame()

    monkeypatch.setattr(open_meteo, "previous_runs", prev_runs)
    monkeypatch.setattr(ghcn, "daily", daily)
    return dates


def test_build_archive_and_error_fits(monkeypatch):
    _stub_archive_sources(monkeypatch)
    a = A.build_archive([STATIONS["NYC"]], years=2, end=date(2026, 2, 1), save=True)
    assert list(a.columns) == A.COLUMNS
    assert set(a.model) == set(("ecmwf_ifs025", "gfs_seamless", "icon_seamless"))
    assert set(a.lead) == {0, 1, 2, 3, 4, 5}
    assert a.error.notna().mean() > 0.95
    assert A.load_archive().shape == a.shape
    g = a[a.lead == 1].groupby("model").error.mean()
    assert g["gfs_seamless"] == pytest.approx(1.5, abs=0.4) and g["icon_seamless"] == pytest.approx(-1.0, abs=0.4)
    fits = E.fit_errors(a, leads=(1, 3), months=(6, 7))
    assert set(fits.lead) == {1, 3} and set(fits.month) == {6, 7}
    assert (fits.n >= 5).all()
    d = E.lookup(fits, "NYC", 3, 7)
    assert set(d) == set(a.model) and d["gfs_seamless"].mean == pytest.approx(1.5, abs=0.8)
    s = E.summary(fits)
    assert {"station", "lead", "model", "bias", "sd", "kde_share"} <= set(s.columns)
    # no lookahead: fits before a date ignore later errors
    early = E.fit_errors(a, before=pd.Timestamp("2024-08-01"), leads=(1,), months=(7,))
    assert early.n.max() <= 31 + 2 * 31  # at most July 2024 pooled with neighbours
    E.save_fits(fits)
    assert len(E.load_fits()) == len(fits)


def test_recent_variance_respects_asof(monkeypatch):
    _stub_archive_sources(monkeypatch)
    a = A.build_archive([STATIONS["NYC"]], years=2, end=date(2026, 2, 1), save=False)
    rv = E.recent_variance(a, "NYC", 3, asof=pd.Timestamp("2025-06-01"))
    assert set(rv) == set(a.model) and all(v > 0 for v in rv.values())
    perturbed = a.copy()
    perturbed.loc[perturbed.target_date >= "2025-06-01", "error"] += 100
    assert E.recent_variance(perturbed, "NYC", 3, asof=pd.Timestamp("2025-06-01")) == rv
    assert E.recent_variance(a, "NYC", 3, asof=pd.Timestamp("2024-02-05")).get("gfs_seamless") is None
    wide = A.ensemble_mean_errors(a, 3)
    assert list(wide.columns) == ["NYC"] and wide.index.is_monotonic_increasing


def test_crosscheck_settlements():
    a = pd.DataFrame({"station": ["NYC"] * 4, "target_date": pd.to_datetime(["2024-02-04"] * 2 + ["2024-02-05"] * 2),
                      "lead": [1, 2, 1, 2], "model": ["gfs_seamless"] * 4, "forecast": [70.0] * 4,
                      "settlement": [72.0, 72.0, 68.0, 68.0], "error": [2.0, 2.0, -2.0, -2.0]})
    k = pd.DataFrame({"station": ["NYC", "NYC"], "target_date": [date(2024, 2, 4), date(2024, 2, 5)],
                      "kalshi_value": [72.0, 0.0]})
    cc = A.crosscheck_settlements(a, k)
    assert len(cc) == 2 and cc["diff"].iloc[0] == 0 and cc["diff"].iloc[1] == 68.0
