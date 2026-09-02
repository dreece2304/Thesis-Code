import time

import pandas as pd
import pytest

from shared.data import cache, fred, ghcn, http, kalshi, nws, open_meteo, prices
from shared.data.ratelimit import RateLimiter


def test_cache_roundtrip_and_ttl(monkeypatch):
    calls = []

    @cache.cached_frame("t", ttl_seconds=100)
    def f(a, b=1):
        calls.append((a, b))
        return pd.DataFrame({"x": [a, b]})

    assert f(1, b=2).x.tolist() == [1, 2]
    assert f(1, b=2).x.tolist() == [1, 2]
    assert len(calls) == 1
    f(1, b=2, refresh=True)
    assert len(calls) == 2
    f(3)
    assert len(calls) == 3
    # expire
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 101)
    f(1, b=2)
    assert len(calls) == 4
    assert cache.clear("t") >= 2


def test_cache_skips_empty_frames():
    n = [0]

    @cache.cached_frame("e", ttl_seconds=None)
    def f():
        n[0] += 1
        return pd.DataFrame()

    f(); f()
    assert n[0] == 2


def test_rate_limiter_spacing():
    t = [0.0]
    slept = []
    rl = RateLimiter(1.0, clock=lambda: t[0], sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    assert rl.wait() == 0.0
    t[0] += 0.25
    assert rl.wait() == pytest.approx(0.75)
    t[0] += 5
    assert rl.wait() == 0.0
    with pytest.raises(ValueError):
        RateLimiter(-1)


def _stub(monkeypatch, payloads):
    """payloads: list of dicts returned in order, or a callable(url, params)."""
    seen = []

    def fake(url, params=None, headers=None, timeout=30, source=None):
        seen.append((url, params))
        if callable(payloads):
            return payloads(url, params)
        return payloads.pop(0)

    monkeypatch.setattr(http, "get_json", fake)
    return seen


def test_open_meteo_forecast_and_ensemble(monkeypatch):
    seen = _stub(monkeypatch, lambda url, p: {
        "hourly": {"time": ["2026-01-01T00:00", "2026-01-01T01:00"],
                   "temperature_2m": [30.0, 31.0],
                   "temperature_2m_member01": [29.0, 32.0]}
    })
    df = open_meteo.forecast(40.78, -73.97, forecast_days=1)
    assert list(df.columns) == ["temperature_2m", "temperature_2m_member01"]
    assert df.index[0] == pd.Timestamp("2026-01-01")
    assert seen[0][1]["temperature_unit"] == "fahrenheit"

    ens = open_meteo.ensemble(40.78, -73.97, models=("gfs_seamless", "icon_seamless"))
    assert set(ens.model) == {"gfs_seamless", "icon_seamless"}
    assert set(ens.member) == {0, 1}
    assert len(ens) == 2 * 2 * 2
    assert ens.query("model=='gfs_seamless' and member==1").value.tolist() == [29.0, 32.0]


def test_open_meteo_archive_cached_forever(monkeypatch):
    seen = _stub(monkeypatch, [{"daily": {"time": ["2023-01-01"], "temperature_2m_max": [40.0],
                                           "temperature_2m_min": [30.0], "precipitation_sum": [0.1]}}])
    a = open_meteo.archive(1, 2, "2023-01-01", "2023-01-01")
    b = open_meteo.archive(1, 2, "2023-01-01", "2023-01-01")
    assert len(seen) == 1 and a.equals(b)


def test_nws_observations_parse(monkeypatch):
    _stub(monkeypatch, [{"features": [
        {"properties": {"timestamp": "2026-01-01T12:00:00+00:00", "station": "https://api.weather.gov/stations/KNYC",
                        "temperature": {"value": 10.0}, "precipitationLastHour": {"value": None}}},
        {"properties": {"timestamp": "2026-01-01T11:00:00+00:00", "station": "https://api.weather.gov/stations/KNYC",
                        "temperature": {"value": 0.0}}},
    ]}])
    df = nws.station_observations("KNYC", start="2026-01-01", end="2026-01-02")
    assert list(df.station) == ["KNYC", "KNYC"]
    assert df.index.is_monotonic_increasing
    assert df.temperature_f.tolist() == [32.0, 50.0]
    assert nws.KALSHI_STATIONS["NYC"] == "KNYC"


def test_ghcn_parse(monkeypatch):
    _stub(monkeypatch, [[{"DATE": "2023-01-02", "STATION": "USW00094728", "TMAX": "45", "TMIN": "33", "PRCP": "0.00"},
                         {"DATE": "2023-01-01", "STATION": "USW00094728", "TMAX": "50", "TMIN": "", "PRCP": "0.10"}]])
    df = ghcn.daily("USW00094728", "2023-01-01", "2023-01-02")
    assert df.index[0] == pd.Timestamp("2023-01-01")
    assert df.TMAX.tolist() == [50.0, 45.0]
    assert pd.isna(df.TMIN.iloc[0])


def test_kalshi_markets_paginate_and_convert_cents(monkeypatch):
    pages = [
        {"markets": [{"ticker": "A", "yes_bid": 40, "yes_ask": 45, "status": "open",
                      "close_time": "2026-02-01T00:00:00Z", "rules_primary": "Resolves YES if ..."}],
         "cursor": "next"},
        {"markets": [{"ticker": "B", "yes_bid": 90, "yes_ask": 95, "status": "open"}], "cursor": ""},
    ]
    seen = _stub(monkeypatch, pages)
    df = kalshi.markets()
    assert df.ticker.tolist() == ["A", "B"]
    assert df.yes_ask.tolist() == [0.45, 0.95]
    assert seen[1][1]["cursor"] == "next"
    assert df.close_time.iloc[0].tzinfo is not None
    assert "rules_primary" in df.columns


def test_kalshi_orderbook(monkeypatch):
    _stub(monkeypatch, [{"orderbook": {"yes": [[45, 100], [44, 50]], "no": None}}])
    ob = kalshi.orderbook("A")
    assert ob["yes"] == [(0.45, 100), (0.44, 50)] and ob["no"] == []


def test_fred_csv_fallback(monkeypatch):
    monkeypatch.setattr(http, "get_text", lambda url, params=None, **k:
                        "DATE,CPIAUCSL\n2020-01-01,258.7\n2020-02-01,.\n2020-03-01,258.1\n")
    df = fred.series("CPIAUCSL", start="2020-02-01")
    assert list(df.index) == [pd.Timestamp("2020-02-01"), pd.Timestamp("2020-03-01")]
    assert pd.isna(df.value.iloc[0]) and df.value.iloc[1] == 258.1
    assert fred.SERIES["cpi"] == "CPIAUCSL"


def test_splice_with_proxy():
    idx = pd.date_range("2020-01-31", periods=6, freq="ME")
    proxy = pd.Series([100, 110, 121, 121, 133.1, 146.41], index=idx)
    primary = pd.Series([50.0, 55.0, 60.5], index=idx[3:])
    s = prices.splice_with_proxy(primary, proxy)
    assert len(s) == 6
    assert s.iloc[3] == 50.0 and s.iloc[2] == pytest.approx(50.0)  # proxy flat into inception
    assert s.iloc[1] / s.iloc[0] == pytest.approx(1.1)
    assert prices.to_monthly(pd.DataFrame({"a": [1, 2, 3]}, index=pd.date_range("2020-01-01", periods=3))).iloc[0, 0] == 3
    with pytest.raises(ValueError):
        prices.splice_with_proxy(primary, proxy.iloc[:2])
