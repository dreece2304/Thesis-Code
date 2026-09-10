"""Scheduled paper-trading job. Refuses to run unless PAPER=1.

Steps: resolve settled markets, discover open KXHIGH* markets for the active
stations, score every contract (logged to the weather ledger with the market
mid), apply entry rules by lead, size at quarter Kelly with caps and
correlation groups, post paper limit orders against an order-book snapshot.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from shared.data import open_meteo
from shared.ledger import Ledger

from ..fees import fee_per_contract
from . import archive as arch
from . import errors as err
from . import kalshi as KW
from . import market_model as mm
from .model import probability
from .sizing import PAPER_BANKROLL, bet_key, correlation_groups, size_bet
from .stations import ACTIVE, MODELS, Station

PROJECT = "weather"
# Kalshi opens each day's KXHIGH markets at 14:00 UTC the day before, so the
# spec's 3-day entry is not available: enter at lead 1 (evening run), add at
# lead 0 (morning-of run). Override with WEATHER_ENTRY_LEAD / WEATHER_ADD_LEAD.
ENTRY_LEAD = int(os.environ.get("WEATHER_ENTRY_LEAD", "1"))
ADD_LEAD = int(os.environ.get("WEATHER_ADD_LEAD", "0"))
ENTRY_EDGE, ADD_EDGE = 0.05, 0.03
MAX_LEAD = 5
# After this local hour the day's high is largely set and the market knows it;
# a lead-0 model score without observations is stale, so no orders.
LEAD0_CUTOFF_HOUR = int(os.environ.get("WEATHER_LEAD0_CUTOFF_HOUR", "11"))
# Cities that may receive paper orders. All active cities are still scored and
# logged. Chicago is excluded until its backtest Brier gap turns positive.
TRADE_STATIONS = set(os.environ.get("WEATHER_TRADE_STATIONS", "NYC,MIA").split(","))


def weather_ledger_path() -> Path:
    """Tracked in git (ledger/weather.duckdb) so the daily routine keeps history across sessions."""
    return Path(os.environ.get("WEATHER_LEDGER_PATH", "ledger/weather.duckdb"))


def require_paper(env=None) -> None:
    env = os.environ if env is None else env
    if env.get("PAPER") != "1":
        raise RuntimeError("refusing to run: set PAPER=1 (this job only ever paper trades)")


def model_forecasts(station: Station, target: date, models=MODELS, **kw) -> dict[str, float]:
    """Deterministic daily-high forecast per model for one local date."""
    out = {}
    for model in models:
        df = open_meteo.forecast(station.lat, station.lon, hourly=None, daily=("temperature_2m_max",),
                                 forecast_days=7, timezone=station.tz, models=model, **kw)
        s = df["temperature_2m_max"]
        s.index = pd.to_datetime(s.index).date
        if target in s.index and pd.notna(s.loc[target]):
            out[model] = float(s.loc[target])
    return out


def refresh_data(stations=ACTIVE) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bring the archive up to yesterday and refit error distributions."""
    a = arch.update_archive(stations) if arch.archive_path().exists() else arch.build_archive(stations)
    fits = err.fit_errors(a)
    err.save_fits(fits)
    return a, fits


def score(stations, archive: pd.DataFrame, fits: pd.DataFrame, now: datetime, snapshots: bool = True,
          **kw) -> pd.DataFrame:
    markets = KW.discover(stations, **kw)
    if markets.empty:
        return pd.DataFrame()
    rows = []
    nws_cache: dict[str, pd.DataFrame] = {}
    fc_cache: dict[tuple[str, date], dict] = {}
    for st in stations:
        mk = markets[(markets.station == st.key) & markets.station_ok & (markets.side != "between")]
        if mk.empty:
            continue
        today = pd.Timestamp(now).tz_convert(st.tz).date()
        try:
            nws_cache[st.key] = mm.nws_point_forecast(st)
        except Exception:
            nws_cache[st.key] = pd.DataFrame(columns=["date", "high"])
        for m in mk.itertuples():
            lead = (m.target_date - today).days
            if lead < 0 or lead > MAX_LEAD:
                continue
            if lead == 0 and pd.Timestamp(now).tz_convert(st.tz).hour >= LEAD0_CUTOFF_HOUR:
                continue
            fit_lead = max(lead, 1)   # lead-0 decisions use the lead-1 error fit (conservative)
            key = (st.key, m.target_date)
            if key not in fc_cache:
                fc_cache[key] = model_forecasts(st, m.target_date, **kw)
            fc = fc_cache[key]
            dists = err.lookup(fits, st.key, fit_lead, m.target_date.month)
            if not fc or not dists:
                continue
            rv = err.recent_variance(archive, st.key, fit_lead, asof=pd.Timestamp(m.target_date))
            p, sd, comp = probability(fc, dists, rv, int(m.threshold), m.side)
            nws = nws_cache[st.key]
            nws_high = nws.loc[nws["date"] == m.target_date, "high"]
            p_base = mm.baseline_probability(float(nws_high.iloc[0]), int(m.threshold), m.side) if len(nws_high) else np.nan
            snap = KW.snapshot_orderbook(m.ticker, persist=snapshots, now=now) if snapshots else \
                {"id": None, "yes_bid": m.yes_bid, "yes_ask": m.yes_ask}
            bid, ask = snap.get("yes_bid"), snap.get("yes_ask")
            mid = (bid + ask) / 2 if bid is not None and ask is not None else np.nan
            rows.append({"ticker": m.ticker, "station": st.key, "target_date": m.target_date, "lead": lead,
                         "threshold": int(m.threshold), "side": m.side, "p": p, "sd": sd, "p_baseline": p_base,
                         "yes_bid": bid, "yes_ask": ask, "mid": mid, "snapshot_id": snap.get("id"),
                         "components": json.dumps(comp), "rules": m.rules_primary})
    return pd.DataFrame(rows)


def decide(scored: pd.DataFrame, book: KW.PaperBook, ledger: Ledger, archive: pd.DataFrame,
           bankroll: float, now: datetime) -> list[dict]:
    """Log predictions, then place at most one paper order per city-day and lead."""
    placed = []
    if scored.empty:
        return placed
    for r in scored.itertuples():
        ledger.log_prediction(PROJECT, r.ticker, r.p, market_prob=None if pd.isna(r.mid) else float(r.mid),
                              timestamp=now, notes=json.dumps({"station": r.station, "lead": r.lead,
                                                               "threshold": r.threshold, "side": r.side,
                                                               "sd": round(r.sd, 3), "p_baseline": None if pd.isna(r.p_baseline) else round(r.p_baseline, 4),
                                                               "yes_ask": r.yes_ask, "snapshot_id": r.snapshot_id}))
    groups = correlation_groups(arch.ensemble_mean_errors(archive, ENTRY_LEAD), asof=pd.Timestamp(now).tz_convert("UTC").tz_localize(None))
    exposure = book.open_exposure().set_index("bet_key")["cost"].to_dict() if len(book.open_exposure()) else {}
    total = sum(exposure.values())
    for (station, target), g in scored.groupby(["station", "target_date"]):
        if station not in TRADE_STATIONS:
            continue
        lead = int(g.lead.iloc[0])
        if lead not in (ENTRY_LEAD, ADD_LEAD):
            continue
        key = bet_key(station, target, groups)
        # an add without an earlier entry (missed evening run) is treated as an entry
        is_entry = lead == ENTRY_LEAD or exposure.get(key, 0.0) <= 0
        required = ENTRY_EDGE if is_entry else ADD_EDGE
        best = None
        for r in g.itertuples():
            for buy, p_side, ask in (("yes", r.p, r.yes_ask), ("no", 1 - r.p, None if r.yes_bid is None else round(1 - r.yes_bid, 4))):
                if ask is None or not 0 < ask < 1:
                    continue
                edge = p_side - ask - fee_per_contract(ask, 100, maker=True)
                if best is None or edge > best["edge"]:
                    best = {"row": r, "buy": buy, "p_side": p_side, "edge": edge}
        if best is None or best["edge"] <= required:
            continue
        r = best["row"]
        limit = round(best["p_side"] - required, 2)
        if not 0 < limit < 1:
            continue
        size = size_bet(best["p_side"], limit, bankroll, existing_bet_stake=exposure.get(key, 0.0),
                        existing_total_stake=total)
        if size.contracts <= 0:
            continue
        quotes = {"yes_bid": r.yes_bid, "yes_ask": r.yes_ask}
        order = book.place(r.ticker, best["buy"], limit, size.contracts, quotes, fair=best["p_side"],
                           station=station, target_date=target, snapshot_id=r.snapshot_id, bet_key=key,
                           notes=json.dumps({"lead": lead, "edge": round(best["edge"], 4), "capped_by": size.capped_by}),
                           now=now)
        placed.append(order)
        if order["status"] == "filled":
            exposure[key] = exposure.get(key, 0.0) + size.stake
            total += size.stake
    return placed


def run(stations=ACTIVE, now: datetime | None = None, bankroll: float = PAPER_BANKROLL,
        refresh: bool = False, snapshots: bool = True, **kw) -> dict:
    require_paper()
    now = now or datetime.now(timezone.utc)
    if refresh or not arch.archive_path().exists() or not err.fits_path().exists():
        archive, fits = refresh_data(stations)
    else:
        archive, fits = arch.load_archive(), err.load_fits()
    with Ledger(weather_ledger_path()) as ledger:
        book = KW.PaperBook(ledger)
        resolved = KW.resolve_settled(ledger, book, stations, **kw)
        book.cancel_resting()
        scored = score(stations, archive, fits, now, snapshots=snapshots, **kw)
        placed = decide(scored, book, ledger, archive, bankroll, now)
        return {"resolved": resolved, "scored": int(len(scored)), "orders": placed,
                "pnl": book.pnl_summary(), "ledger": str(weather_ledger_path())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh-data", action="store_true", help="update archive and refit before scoring")
    ap.add_argument("--no-snapshots", action="store_true")
    a = ap.parse_args(argv)
    out = run(refresh=a.refresh_data, snapshots=not a.no_snapshots)
    print(json.dumps(out, default=str, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
