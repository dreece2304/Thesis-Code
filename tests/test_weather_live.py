import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from prediction.weather import archive as A
from prediction.weather import errors as E
from prediction.weather import kalshi as KW
from prediction.weather import live, report
from prediction.weather import market_model as MM
from prediction.weather.stations import STATIONS
from shared.data import kalshi as kx
from shared.data import open_meteo
from shared.ledger import Ledger
from tests.test_weather_backtest import synthetic_archive


def test_requires_paper_flag(monkeypatch):
    monkeypatch.delenv("PAPER", raising=False)
    with pytest.raises(RuntimeError):
        live.require_paper()
    with pytest.raises(RuntimeError):
        live.run()          # must fail before touching data or network
    monkeypatch.setenv("PAPER", "0")
    with pytest.raises(RuntimeError):
        live.require_paper()
    monkeypatch.setenv("PAPER", "1")
    live.require_paper()


def _stub_live(monkeypatch, tmp_path):
    a = synthetic_archive(days=500, stations=("NYC", "CHI", "MIA"))
    A.archive_dir().mkdir(parents=True, exist_ok=True)
    a.to_parquet(A.archive_path(), index=False)
    fits = E.fit_errors(a, leads=(1, 3), months=(9,))
    E.save_fits(fits)
    now = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)

    def markets(status="open", series_ticker=None, **kw):
        if status != "open":
            return pd.DataFrame()
        st = {s.series: s for s in STATIONS.values()}[series_ticker]
        rows = []
        for t in (85, 88):
            rows.append({"ticker": f"{series_ticker}-26SEP03-T{t - 1}", "title": f"Will the maximum temperature be >{t - 1}° on Sep 3, 2026?",
                         "strike_type": "greater", "floor_strike": t - 1, "cap_strike": None,
                         "rules_primary": f"... recorded at X ({st.cli}) ...", "yes_bid": 0.30, "yes_ask": 0.33, "last_price": 0.31})
        rows.append({"ticker": f"{series_ticker}-26SEP03-B86.5", "title": "Will the maximum temperature be 86-87° on Sep 3, 2026?",
                     "strike_type": "between", "floor_strike": 85.5, "cap_strike": 87.5,
                     "rules_primary": f"... ({st.cli}) ...", "yes_bid": 0.2, "yes_ask": 0.25, "last_price": 0.2})
        return pd.DataFrame(rows)

    def forecast(lat, lon, hourly=None, daily=None, forecast_days=7, timezone="UTC", models=None, **kw):
        idx = pd.date_range("2026-09-02", periods=7, freq="D")
        base = {"ecmwf_ifs025": 88.0, "gfs_seamless": 90.0, "icon_seamless": 87.0}[models]
        return pd.DataFrame({"temperature_2m_max": base}, index=idx)

    monkeypatch.setattr(kx, "markets", markets)
    monkeypatch.setattr(kx, "orderbook", lambda ticker, depth=10: {"yes": [(0.30, 100.0)], "no": [(0.67, 50.0)]})
    monkeypatch.setattr(open_meteo, "forecast", forecast)
    monkeypatch.setattr(MM, "nws_point_forecast", lambda st: pd.DataFrame({"date": [date(2026, 9, 3)], "high": [88], "name": ["Thu"]}))
    monkeypatch.setenv("WEATHER_LEDGER_PATH", str(tmp_path / "weather.duckdb"))
    return now


def test_live_run_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER", "1")
    now = _stub_live(monkeypatch, tmp_path)
    out = live.run(now=now, snapshots=True)
    assert out["scored"] == 6                      # 2 threshold contracts x 3 cities; range bucket skipped
    with Ledger(live.weather_ledger_path()) as L:
        df = L.predictions(project="weather")
        assert len(df) == 6 and df.model_prob.between(0, 1).all() and df.market_prob.notna().all()
        notes = json.loads(df.notes.iloc[0])
        assert notes["lead"] == 1 and notes["side"] == "above" and notes["snapshot_id"]
        book = KW.PaperBook(L)
        orders = book.orders()
        assert len(out["orders"]) == len(orders) >= 1
        assert (orders.limit_price.between(0.01, 0.99)).all()
        assert (orders.contracts * orders.limit_price <= 0.05 * 2000 + 1).all()
        st = report.weekly_status(L, book, now=datetime(2026, 9, 6))
        assert st.project == "prediction" and "predictions this week" in st.done[0] and st.blocked
    snaps = list(KW.snapshot_dir().glob("*.jsonl"))
    assert snaps and sum(1 for _ in snaps[0].open()) == 6
    # next morning (lead 0): scores again with the lead-1 fit; adds only on top of the entry
    out2 = live.run(now=now.replace(day=3), snapshots=False)
    assert out2["scored"] == 6


def test_live_score_skips_far_leads(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER", "1")
    now = _stub_live(monkeypatch, tmp_path).replace(day=1, month=8)   # Aug 1: markets 35 days out
    out = live.run(now=now, snapshots=False)
    assert out["scored"] == 0 and out["orders"] == []
