"""Daily rain markets (KXRAIN): calibrated probability of measurable rain.

Kalshi's "Will it rain in <city> on <date>" pays YES when the NWS daily
climate report (CLI) shows strictly more than 0.00 inches; a trace counts as
zero. The climate day runs midnight to midnight local STANDARD time, so in
summer it starts at 01:00 local clock time (checked against CLIPHL and
CLIDCA on 2026-09-04).

Model: for each forecast model, a per-station logistic fit of
P(observed >= 0.01 in) on log(1 + 100 x model daily total), trained on
three years of lead-1 previous-run forecasts against GHCN-Daily PRCP. Raw
model totals over-forecast light rain badly (a wet ECMWF day verifies only
40 to 70% of the time depending on the station), so this calibration is the
whole point. Live probability = mean over models of the calibrated
probability for the remaining hours of the climate day, forced to 1 once
measurable rain has already been observed at the station.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from shared.data import http, kalshi as kx
from shared.data.cache import cached_frame

MODELS = ("ecmwf_ifs025", "gfs_seamless", "icon_seamless")
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
NCEI_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
WET_IN = 0.01


@dataclass(frozen=True)
class RainStation:
    key: str        # Kalshi market suffix (e.g. "SATX")
    city: str       # as it appears in the market title
    cli: str
    asos: str
    ghcn: str
    lat: float
    lon: float
    tz: str


RAIN_STATIONS: dict[str, RainStation] = {s.key: s for s in [
    RainStation("NYC", "New York City", "CLINYC", "KNYC", "USW00094728", 40.779, -73.969, "America/New_York"),
    RainStation("NEWARK", "Newark", "CLIEWR", "KEWR", "USW00014734", 40.6925, -74.1687, "America/New_York"),
    RainStation("PHIL", "Philadelphia", "CLIPHL", "KPHL", "USW00013739", 39.872, -75.241, "America/New_York"),
    RainStation("TTN", "Trenton", "CLITTN", "KTTN", "USW00014792", 40.277, -74.816, "America/New_York"),
    RainStation("DC", "Washington DC", "CLIDCA", "KDCA", "USW00013743", 38.852, -77.037, "America/New_York"),
    RainStation("BOS", "Boston", "CLIBOS", "KBOS", "USW00014739", 42.361, -71.010, "America/New_York"),
    RainStation("ATL", "Atlanta", "CLIATL", "KATL", "USW00013874", 33.640, -84.427, "America/New_York"),
    RainStation("MIA", "Miami", "CLIMIA", "KMIA", "USW00012839", 25.795, -80.290, "America/New_York"),
    RainStation("CHI", "Chicago", "CLIORD", "KORD", "USW00094846", 41.978, -87.906, "America/Chicago"),
    RainStation("MIN", "Minneapolis", "CLIMSP", "KMSP", "USW00014922", 44.883, -93.229, "America/Chicago"),
    RainStation("DAL", "Dallas", "CLIDFW", "KDFW", "USW00003927", 32.897, -97.038, "America/Chicago"),
    RainStation("AUS", "Austin", "CLIAUS", "KATT", "USW00013958", 30.321, -97.760, "America/Chicago"),
    RainStation("SATX", "San Antonio", "CLISAT", "KSAT", "USW00012921", 29.534, -98.469, "America/Chicago"),
    RainStation("HOU", "Houston", "CLIHOU", "KHOU", "USW00012918", 29.645, -95.279, "America/Chicago"),
    RainStation("NOLA", "New Orleans", "CLIMSY", "KMSY", "USW00012916", 29.993, -90.258, "America/Chicago"),
    RainStation("OKC", "Oklahoma City", "CLIOKC", "KOKC", "USW00013967", 35.389, -97.600, "America/Chicago"),
    RainStation("DEN", "Denver", "CLIDEN", "KDEN", "USW00003017", 39.847, -104.656, "America/Denver"),
    RainStation("PHX", "Phoenix", "CLIPHX", "KPHX", "USW00023183", 33.428, -112.004, "America/Phoenix"),
    RainStation("LV", "Las Vegas", "CLILAS", "KLAS", "USW00023169", 36.072, -115.163, "America/Los_Angeles"),
    RainStation("LAX", "Los Angeles", "CLILAX", "KLAX", "USW00023174", 33.938, -118.389, "America/Los_Angeles"),
    RainStation("SFO", "San Francisco", "CLISFO", "KSFO", "USW00023234", 37.619, -122.375, "America/Los_Angeles"),
    RainStation("SEA", "Seattle", "CLISEA", "KSEA", "USW00024233", 47.449, -122.309, "America/Los_Angeles"),
]}
BY_CITY = {s.city: s for s in RAIN_STATIONS.values()}


def rain_dir() -> Path:
    return Path(os.environ.get("DATA_CACHE_DIR", "data_cache")) / "weather"


def climate_day_start(now: datetime, tz: str) -> datetime:
    """Start of the current NWS climate day: midnight local standard time."""
    local = now.astimezone(ZoneInfo(tz))
    dst = local.dst() or timedelta(0)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) + dst
    if start > local:  # between 00:00 and 01:00 daylight time we are still in yesterday's climate day
        start -= timedelta(days=1)
    return start


# -- calibration archive -------------------------------------------------------
def _x(total) -> np.ndarray:
    return np.log1p(np.maximum(np.asarray(total, dtype=float), 0.0) * 100.0)


def fit_logistic(total, wet) -> tuple[float, float]:
    x, y = _x(total), np.asarray(wet, dtype=float)

    def nll(b):
        p = 1 / (1 + np.exp(-(b[0] + b[1] * x)))
        return -np.sum(y * np.log(p + 1e-9) + (1 - y) * np.log(1 - p + 1e-9))

    r = minimize(nll, [-2.5, 1.0], method="Nelder-Mead")
    return float(r.x[0]), float(r.x[1])


def logistic_prob(params: tuple[float, float], total: float) -> float:
    b0, b1 = params
    return float(1 / (1 + np.exp(-(b0 + b1 * _x(total)))))


@cached_frame("rain_calibration", ttl_seconds=None)
def calibration_frame(station_key: str, start: date, end: date, lead: int = 1) -> pd.DataFrame:
    """(date, model, forecast total, observed total) for one station."""
    st = RAIN_STATIONS[station_key]
    obs = http.get_json(NCEI_URL, params={"dataset": "daily-summaries", "stations": st.ghcn, "startDate": str(start),
                                          "endDate": str(end), "dataTypes": "PRCP", "format": "json",
                                          "units": "standard", "includeAttributes": "false"}, source="ghcn")
    o = pd.Series({x["DATE"]: float(x["PRCP"]) for x in obs if x.get("PRCP") not in (None, "")})
    frames = []
    for model in MODELS:
        col = f"precipitation_previous_day{lead}"
        js = http.get_json(PREVIOUS_RUNS_URL, params={"latitude": st.lat, "longitude": st.lon, "start_date": str(start),
                                                      "end_date": str(end), "hourly": col, "models": model,
                                                      "precipitation_unit": "inch", "timezone": st.tz}, source="open_meteo")
        h = js["hourly"]
        df = pd.DataFrame({"t": h["time"], "p": h[col]})
        df["d"] = df["t"].str[:10]
        daily = df.groupby("d")["p"].sum(min_count=20)
        j = pd.DataFrame({"forecast": daily, "observed": o}).dropna()
        j["model"] = model
        j["station"] = station_key
        frames.append(j.reset_index().rename(columns={"index": "date"}))
    return pd.concat(frames, ignore_index=True)


def fit_all(stations=None, years: int = 3, end: date | None = None) -> pd.DataFrame:
    """Per station and model logistic parameters plus a pooled fallback per model."""
    end = end or (date.today() - timedelta(days=2))
    start = end - timedelta(days=365 * years)
    keys = stations or list(RAIN_STATIONS)
    frames = [calibration_frame(k, start, end) for k in keys]
    J = pd.concat(frames, ignore_index=True)
    J["wet"] = (J["observed"] >= WET_IN).astype(int)
    rows = []
    for (s, m), g in J.groupby(["station", "model"]):
        b0, b1 = fit_logistic(g["forecast"], g["wet"])
        rows.append({"station": s, "model": m, "b0": b0, "b1": b1, "n": len(g), "obs_wet": g.wet.mean(),
                     "model_wet": (g.forecast >= WET_IN).mean()})
    for m, g in J.groupby("model"):
        b0, b1 = fit_logistic(g["forecast"], g["wet"])
        rows.append({"station": "POOLED", "model": m, "b0": b0, "b1": b1, "n": len(g), "obs_wet": g.wet.mean(),
                     "model_wet": (g.forecast >= WET_IN).mean()})
    fits = pd.DataFrame(rows)
    rain_dir().mkdir(parents=True, exist_ok=True)
    fits.to_parquet(rain_dir() / "rain_fits.parquet", index=False)
    return fits


def load_fits() -> pd.DataFrame:
    return pd.read_parquet(rain_dir() / "rain_fits.parquet")


def params_for(fits: pd.DataFrame, station_key: str, model: str) -> tuple[float, float]:
    r = fits[(fits.station == station_key) & (fits.model == model)]
    if r.empty:
        r = fits[(fits.station == "POOLED") & (fits.model == model)]
    if r.empty:
        raise KeyError(f"no calibration for {model}")
    return float(r.b0.iloc[0]), float(r.b1.iloc[0])


# -- live inputs ---------------------------------------------------------------
def observed_so_far(st: RainStation, now: datetime) -> float:
    """Inches recorded at the ASOS since the climate day started (max per clock hour)."""
    start = climate_day_start(now, st.tz)
    js = http.get_json(f"https://api.weather.gov/stations/{st.asos}/observations",
                       params={"start": start.isoformat(), "limit": 100},
                       headers={"Accept": "application/geo+json"}, source="nws")
    byhour: dict[str, float] = {}
    for f in js.get("features", []):
        p = f["properties"]
        v = (p.get("precipitationLastHour") or {}).get("value")
        if v:
            byhour[p["timestamp"][:13]] = max(byhour.get(p["timestamp"][:13], 0.0), float(v))
    return round(sum(byhour.values()) / 25.4, 3)


def remaining_totals(st: RainStation, now: datetime, models=MODELS) -> dict[str, float]:
    """Each model's precipitation total from the current hour to the end of the climate day."""
    local = now.astimezone(ZoneInfo(st.tz))
    end = climate_day_start(now, st.tz) + timedelta(days=1)
    out = {}
    for model in models:
        js = http.get_json("https://api.open-meteo.com/v1/forecast",
                           params={"latitude": st.lat, "longitude": st.lon, "hourly": "precipitation", "models": model,
                                   "forecast_days": 3, "timezone": st.tz, "precipitation_unit": "inch"},
                           source="open_meteo")
        h = js["hourly"]
        tot = 0.0
        for t, v in zip(h["time"], h["precipitation"]):
            ts = datetime.fromisoformat(t).replace(tzinfo=ZoneInfo(st.tz))
            if local.replace(minute=0, second=0, microsecond=0) <= ts < end:
                tot += float(v or 0.0)
        out[model] = round(tot, 3)
    return out


def probability(st: RainStation, fits: pd.DataFrame, now: datetime, totals: dict[str, float] | None = None,
                so_far: float | None = None) -> tuple[float, dict]:
    so_far = observed_so_far(st, now) if so_far is None else so_far
    if so_far >= WET_IN:
        return 1.0, {"observed_in": so_far, "locked": True}
    totals = totals if totals is not None else remaining_totals(st, now)
    ps = {m: logistic_prob(params_for(fits, st.key, m), t) for m, t in totals.items()}
    return float(np.mean(list(ps.values()))), {"observed_in": so_far, "locked": False, "totals": totals, "per_model": ps}


# -- markets -------------------------------------------------------------------
_RE_CITY = re.compile(r"rain in (.+?) on ")


def open_markets(target: date | None = None, **kw) -> pd.DataFrame:
    mk = kx.markets(status="open", series_ticker="KXRAIN", **kw)
    if mk.empty:
        return mk
    mk = mk.copy()
    mk["city"] = mk["title"].str.extract(_RE_CITY)[0]
    mk["target_date"] = mk["ticker"].map(lambda t: datetime.strptime(t.split("-")[1], "%y%b%d").date())
    if target is not None:
        mk = mk[mk.target_date == target]
    return mk


def screen(fits: pd.DataFrame, now: datetime | None = None, target: date | None = None, **kw) -> pd.DataFrame:
    """Calibrated probability vs market for every open KXRAIN market on ``target``."""
    now = now or datetime.now(timezone.utc)
    mk = open_markets(target, **kw)
    rows = []
    for m in mk.itertuples():
        st = BY_CITY.get(m.city)
        if st is None:
            continue
        p, info = probability(st, fits, now)
        bid, ask = m.yes_bid, m.yes_ask
        rows.append({"ticker": m.ticker, "city": m.city, "target_date": m.target_date, "p": round(p, 3),
                     "observed_in": info["observed_in"], "locked": info["locked"],
                     "totals": json.dumps(info.get("totals", {})),
                     "yes_bid": bid, "yes_ask": ask,
                     "edge_yes": None if pd.isna(ask) else round(p - ask, 3),
                     "edge_no": None if pd.isna(bid) else round((1 - p) - (1 - bid), 3)})
    return pd.DataFrame(rows)


# -- ledger and CLI ------------------------------------------------------------
PROJECT = "weather_rain"


def log_screen(ledger, df: pd.DataFrame, now: datetime | None = None) -> int:
    """Log every screened market to the calibration ledger (model vs market mid)."""
    now = now or datetime.now(timezone.utc)
    n = 0
    for r in df.itertuples():
        mid = None
        if pd.notna(r.yes_bid) and pd.notna(r.yes_ask) and 0 < r.yes_bid <= r.yes_ask < 1:
            mid = float((r.yes_bid + r.yes_ask) / 2)
        ledger.log_prediction(PROJECT, r.ticker, float(r.p), market_prob=mid, timestamp=now,
                              notes=json.dumps({"city": r.city, "observed_in": r.observed_in,
                                                "locked": bool(r.locked), "totals": json.loads(r.totals)}))
        n += 1
    return n


def resolve_settled(ledger, **kw) -> int:
    pending = ledger.predictions(project=PROJECT, resolved=False)
    if pending.empty:
        return 0
    settled = kx.markets(status="settled", series_ticker="KXRAIN", max_pages=5, **kw)
    n = 0
    for m in settled.itertuples():
        if m.ticker in set(pending.market_or_asset) and m.result in ("yes", "no"):
            n += ledger.resolve_market(m.ticker, m.result == "yes")
    return n


def main(argv=None) -> int:
    import argparse

    from shared.ledger import Ledger

    from .live import weather_ledger_path

    ap = argparse.ArgumentParser(description="Calibrated rain screen for today's KXRAIN markets")
    ap.add_argument("--fit", action="store_true", help="refit the calibration from three years of archives")
    ap.add_argument("--no-log", action="store_true")
    a = ap.parse_args(argv)
    fits = fit_all() if a.fit or not (rain_dir() / "rain_fits.parquet").exists() else load_fits()
    now = datetime.now(timezone.utc)
    df = screen(fits, now=now)
    with Ledger(weather_ledger_path()) as L:
        resolved = resolve_settled(L)
        logged = 0 if a.no_log else log_screen(L, df, now)
    print(df.sort_values("edge_yes", ascending=False).to_string(index=False))
    print(f"resolved {resolved}, logged {logged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
