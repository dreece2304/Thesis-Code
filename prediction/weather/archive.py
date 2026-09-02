"""Three-year archive of forecasts vs settlements.

Tidy table: (station, target_date, lead, model, forecast, settlement, error)
with ``error = settlement - forecast`` (so settlement = forecast + error).
Forecasts are the daily max (local date) of Open-Meteo previous-run hourly
temperature at lead 1..5 days. Settlement is GHCN-Daily TMAX for the station,
cross-checkable against Kalshi's settled ``expiration_value``.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from shared.data import ghcn, open_meteo

from .stations import ACTIVE, LEADS, MODELS, Station

COLUMNS = ["station", "target_date", "lead", "model", "forecast", "settlement", "error"]


def archive_dir() -> Path:
    return Path(os.environ.get("DATA_CACHE_DIR", "data_cache")) / "weather"


def archive_path() -> Path:
    return archive_dir() / "archive.parquet"


def daily_max_by_lead(hourly: pd.DataFrame, variable: str = "temperature_2m",
                      leads=LEADS) -> pd.DataFrame:
    """Long frame (target_date, lead, forecast) from a previous-runs hourly frame."""
    df = hourly.copy()
    df["target_date"] = pd.to_datetime(df.index).date
    rows = []
    for lead in (0, *leads):
        col = variable if lead == 0 else f"{variable}_previous_day{lead}"
        if col not in df:
            continue
        m = df.groupby("target_date")[col].agg(["max", "count"])
        m = m[m["count"] >= 20]  # need most of the day
        rows.append(pd.DataFrame({"target_date": m.index, "lead": lead, "forecast": m["max"].to_numpy()}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["target_date", "lead", "forecast"])


def pull_forecasts(station: Station, start: date, end: date, models=MODELS, leads=LEADS,
                   **kw) -> pd.DataFrame:
    frames = []
    for model in models:
        h = open_meteo.previous_runs(station.lat, station.lon, start, end, variable="temperature_2m",
                                     model=model, previous_days=max(leads), timezone=station.tz, **kw)
        d = daily_max_by_lead(h, leads=leads)
        d["model"] = model
        frames.append(d)
    out = pd.concat(frames, ignore_index=True)
    out["station"] = station.key
    return out


def pull_settlements(station: Station, start: date, end: date, **kw) -> pd.Series:
    obs = ghcn.daily(station.ghcn, start, end, datatypes=("TMAX",), **kw)
    s = obs["TMAX"].dropna()
    s.index = pd.to_datetime(s.index).date
    return s.rename("settlement")


def build_archive(stations=ACTIVE, years: int = 3, end: date | None = None,
                  models=MODELS, leads=LEADS, save: bool = True, **kw) -> pd.DataFrame:
    end = end or (date.today() - timedelta(days=2))
    start = end - timedelta(days=365 * years)
    parts = []
    for st in stations:
        f = pull_forecasts(st, start, end, models=models, leads=leads, **kw)
        s = pull_settlements(st, start, end, **kw)
        f["settlement"] = f["target_date"].map(s)
        parts.append(f)
    df = pd.concat(parts, ignore_index=True)
    df["error"] = df["settlement"] - df["forecast"]
    df["target_date"] = pd.to_datetime(df["target_date"])
    df = df[COLUMNS].sort_values(["station", "target_date", "lead", "model"]).reset_index(drop=True)
    if save:
        archive_dir().mkdir(parents=True, exist_ok=True)
        df.to_parquet(archive_path(), index=False)
    return df


def load_archive(path: str | Path | None = None) -> pd.DataFrame:
    p = Path(path) if path else archive_path()
    if not p.exists():
        raise FileNotFoundError(f"no archive at {p}; run build_archive() first")
    df = pd.read_parquet(p)
    df["target_date"] = pd.to_datetime(df["target_date"])
    return df


def update_archive(stations=ACTIVE, days: int = 14, **kw) -> pd.DataFrame:
    """Append the last ``days`` of forecasts and settlements to the saved archive."""
    old = load_archive() if archive_path().exists() else pd.DataFrame(columns=COLUMNS)
    end = date.today() - timedelta(days=1)
    new = build_archive(stations, years=0, end=end, save=False, **{**kw})
    if new.empty and days:
        start = end - timedelta(days=days)
        parts = []
        for st in stations:
            f = pull_forecasts(st, start, end, **kw)
            s = pull_settlements(st, start, end, **kw)
            f["settlement"] = f["target_date"].map(s)
            parts.append(f)
        new = pd.concat(parts, ignore_index=True)
        new["error"] = new["settlement"] - new["forecast"]
        new["target_date"] = pd.to_datetime(new["target_date"])
        new = new[COLUMNS]
    df = pd.concat([old, new], ignore_index=True)
    df = df.drop_duplicates(["station", "target_date", "lead", "model"], keep="last")
    df = df.sort_values(["station", "target_date", "lead", "model"]).reset_index(drop=True)
    archive_dir().mkdir(parents=True, exist_ok=True)
    df.to_parquet(archive_path(), index=False)
    return df


def crosscheck_settlements(archive: pd.DataFrame, kalshi_settlements: pd.DataFrame) -> pd.DataFrame:
    """Compare GHCN settlement with Kalshi's settled value per (station, date).

    ``kalshi_settlements`` has columns station, target_date, kalshi_value.
    Returns rows where both exist, with the difference; non-zero rows need a look.
    """
    g = archive[["station", "target_date", "settlement"]].drop_duplicates()
    k = kalshi_settlements.copy()
    k["target_date"] = pd.to_datetime(k["target_date"])
    m = g.merge(k, on=["station", "target_date"], how="inner")
    m["diff"] = m["settlement"] - m["kalshi_value"]
    return m


def ensemble_mean_errors(archive: pd.DataFrame, lead: int) -> pd.DataFrame:
    """Wide frame: date x station of the mean-over-models error at one lead."""
    a = archive[archive["lead"] == lead]
    return a.groupby(["target_date", "station"])["error"].mean().unstack("station")
