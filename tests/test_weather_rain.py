from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from prediction.weather import archive as A
from prediction.weather import rain as R
from shared.data import http, kalshi as kx


def test_climate_day_starts_at_standard_midnight():
    # 2026-09-04 03:00 UTC = 23:00 EDT Sep 3 -> climate day Sep 3 started 01:00 EDT Sep 3
    s = R.climate_day_start(datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc), "America/New_York")
    assert (s.year, s.month, s.day, s.hour) == (2026, 9, 3, 1)
    # 04:30 UTC = 00:30 EDT Sep 4 -> still the Sep 3 climate day
    s = R.climate_day_start(datetime(2026, 9, 4, 4, 30, tzinfo=timezone.utc), "America/New_York")
    assert (s.day, s.hour) == (3, 1)
    # 05:30 UTC = 01:30 EDT -> Sep 4 climate day
    s = R.climate_day_start(datetime(2026, 9, 4, 5, 30, tzinfo=timezone.utc), "America/New_York")
    assert (s.day, s.hour) == (4, 1)
    # Phoenix has no DST: climate day starts at 00:00
    s = R.climate_day_start(datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc), "America/Phoenix")
    assert s.hour == 0


def test_archive_climate_day_shift():
    idx = pd.date_range("2026-09-04 00:00", periods=3, freq="h")  # local clock, EDT
    days = A.climate_day(idx, "America/New_York")
    assert days[0] == date(2026, 9, 3) and days[1] == date(2026, 9, 4)
    assert list(A.climate_day(idx, None)) == [date(2026, 9, 4)] * 3
    winter = pd.date_range("2026-01-04 00:00", periods=2, freq="h")
    assert list(A.climate_day(winter, "America/New_York")) == [date(2026, 1, 4)] * 2


def test_logistic_fit_recovers_calibration():
    rng = np.random.default_rng(0)
    total = np.where(rng.uniform(size=3000) < 0.5, 0.0, rng.exponential(0.2, 3000))
    p_true = 1 / (1 + np.exp(-(-2.5 + 1.2 * R._x(total))))
    wet = (rng.uniform(size=3000) < p_true).astype(int)
    b0, b1 = R.fit_logistic(total, wet)
    assert b0 == pytest.approx(-2.5, abs=0.3) and b1 == pytest.approx(1.2, abs=0.2)
    assert R.logistic_prob((b0, b1), 0.0) < 0.15
    assert R.logistic_prob((b0, b1), 0.5) > R.logistic_prob((b0, b1), 0.05) > R.logistic_prob((b0, b1), 0.0)


def _fits():
    rows = [{"station": "BOS", "model": m, "b0": -2.5, "b1": 1.0, "n": 100, "obs_wet": 0.3, "model_wet": 0.4} for m in R.MODELS]
    rows += [{"station": "POOLED", "model": m, "b0": -2.0, "b1": 1.0, "n": 1000, "obs_wet": 0.3, "model_wet": 0.4} for m in R.MODELS]
    return pd.DataFrame(rows)


def test_probability_locks_when_rain_observed_and_uses_pooled_fallback():
    fits = _fits()
    st = R.RAIN_STATIONS["BOS"]
    now = datetime(2026, 9, 5, 8, tzinfo=timezone.utc)
    p, info = R.probability(st, fits, now, totals={m: 0.0 for m in R.MODELS}, so_far=0.05)
    assert p == 1.0 and info["locked"]
    p, info = R.probability(st, fits, now, totals={m: 0.2 for m in R.MODELS}, so_far=0.0)
    assert 0.5 < p < 0.9 and not info["locked"] and set(info["per_model"]) == set(R.MODELS)
    assert R.params_for(fits, "DEN", "gfs_seamless") == (-2.0, 1.0)
    with pytest.raises(KeyError):
        R.params_for(fits, "DEN", "not_a_model")


def test_screen_with_stubs(monkeypatch):
    now = datetime(2026, 9, 5, 8, tzinfo=timezone.utc)
    mk = pd.DataFrame({"ticker": ["KXRAIN-26SEP05-BOS", "KXRAIN-26SEP05-DEN", "KXRAIN-26SEP04-BOS"],
                       "title": ["Will it rain in Boston on Sep 5, 2026?", "Will it rain in Denver on Sep 5, 2026?",
                                 "Will it rain in Boston on Sep 4, 2026?"],
                       "yes_bid": [0.22, 0.19, 0.5], "yes_ask": [0.23, 0.20, 0.6]})
    monkeypatch.setattr(kx, "markets", lambda status="open", series_ticker=None, **kw: mk.copy())
    monkeypatch.setattr(R, "observed_so_far", lambda st, now: 0.02 if st.key == "DEN" else 0.0)
    monkeypatch.setattr(R, "remaining_totals", lambda st, now, models=R.MODELS: {m: 0.3 for m in models})
    df = R.screen(_fits(), now=now, target=date(2026, 9, 5))
    assert df.city.tolist() == ["Boston", "Denver"]
    den = df[df.city == "Denver"].iloc[0]
    assert den.p == 1.0 and den.locked and den.edge_yes == pytest.approx(0.80)
    bos = df[df.city == "Boston"].iloc[0]
    assert 0.5 < bos.p < 1 and bos.edge_yes == pytest.approx(bos.p - 0.23, abs=1e-6)


def test_log_and_resolve(monkeypatch):
    from shared.ledger import Ledger
    now = datetime(2026, 9, 5, 8, tzinfo=timezone.utc)
    df = pd.DataFrame({"ticker": ["KXRAIN-26SEP05-BOS"], "city": ["Boston"], "target_date": [date(2026, 9, 5)],
                       "p": [0.3], "observed_in": [0.0], "locked": [False], "totals": ['{"gfs_seamless": 0.1}'],
                       "yes_bid": [0.22], "yes_ask": [0.23], "edge_yes": [0.07], "edge_no": [-0.08]})
    with Ledger(":memory:") as L:
        assert R.log_screen(L, df, now) == 1
        row = L.predictions(project=R.PROJECT).iloc[0]
        assert row.model_prob == 0.3 and row.market_prob == pytest.approx(0.225)
        monkeypatch.setattr(kx, "markets", lambda status="open", series_ticker=None, **kw:
                            pd.DataFrame({"ticker": ["KXRAIN-26SEP05-BOS"], "result": ["yes"]}))
        assert R.resolve_settled(L) == 1
        assert L.predictions(resolved=True).outcome.iloc[0] == 1
