"""Open-Meteo: forecast, ensemble members, and historical archive. No key needed."""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import http
from .cache import cached_frame

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"

# Ensemble model ids accepted by the ensemble endpoint.
ENSEMBLE_MODELS = ("gfs_seamless", "ecmwf_ifs025", "icon_seamless")


def _frame(block: dict, time_key: str = "time") -> pd.DataFrame:
    df = pd.DataFrame(block)
    if time_key in df:
        df[time_key] = pd.to_datetime(df[time_key])
        df = df.set_index(time_key)
    return df


@cached_frame("open_meteo_forecast", ttl_seconds=1800)
def forecast(lat: float, lon: float, hourly=("temperature_2m",), daily=None,
             forecast_days: int = 7, temperature_unit: str = "fahrenheit",
             timezone: str = "UTC", models: str | None = None) -> pd.DataFrame:
    """Deterministic forecast. Returns hourly (or daily if only daily requested)."""
    params = {
        "latitude": lat, "longitude": lon, "forecast_days": forecast_days,
        "temperature_unit": temperature_unit, "precipitation_unit": "inch",
        "timezone": timezone,
    }
    if hourly:
        params["hourly"] = ",".join(hourly)
    if daily:
        params["daily"] = ",".join(daily)
    if models:
        params["models"] = models
    js = http.get_json(FORECAST_URL, params=params, source="open_meteo")
    if hourly:
        return _frame(js["hourly"])
    return _frame(js["daily"])


def _parse_ensemble(js: dict, model: str) -> pd.DataFrame:
    hourly = js["hourly"]
    t = pd.to_datetime(hourly["time"])
    rows = []
    for key, vals in hourly.items():
        if key == "time":
            continue
        # keys look like temperature_2m, temperature_2m_member01, ...
        if "_member" in key:
            var, member = key.rsplit("_member", 1)
            member = int(member)
        else:
            var, member = key, 0  # control run
        rows.append(pd.DataFrame({"time": t, "model": model, "variable": var,
                                  "member": member, "value": vals}))
    if not rows:
        return pd.DataFrame(columns=["time", "model", "variable", "member", "value"])
    return pd.concat(rows, ignore_index=True)


@cached_frame("open_meteo_ensemble", ttl_seconds=1800)
def ensemble(lat: float, lon: float, variables=("temperature_2m",),
             models=ENSEMBLE_MODELS, forecast_days: int = 7,
             temperature_unit: str = "fahrenheit", timezone: str = "UTC") -> pd.DataFrame:
    """All ensemble members for each model, long format.

    Columns: time, model, variable, member (0 = control), value.
    """
    frames = []
    for model in models:
        params = {
            "latitude": lat, "longitude": lon, "hourly": ",".join(variables),
            "models": model, "forecast_days": forecast_days,
            "temperature_unit": temperature_unit, "precipitation_unit": "inch",
            "timezone": timezone,
        }
        js = http.get_json(ENSEMBLE_URL, params=params, source="open_meteo")
        frames.append(_parse_ensemble(js, model))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


@cached_frame("open_meteo_archive", ttl_seconds=None)
def archive(lat: float, lon: float, start: str | date, end: str | date,
            daily=("temperature_2m_max", "temperature_2m_min", "precipitation_sum"),
            temperature_unit: str = "fahrenheit", timezone: str = "UTC") -> pd.DataFrame:
    """Reanalysis-based daily history (ERA5 land). Cached forever."""
    params = {
        "latitude": lat, "longitude": lon, "start_date": str(start), "end_date": str(end),
        "daily": ",".join(daily), "temperature_unit": temperature_unit,
        "precipitation_unit": "inch", "timezone": timezone,
    }
    js = http.get_json(ARCHIVE_URL, params=params, source="open_meteo")
    return _frame(js["daily"])


@cached_frame("open_meteo_previous_runs", ttl_seconds=None)
def previous_runs(lat: float, lon: float, start: str | date, end: str | date,
                  variable: str = "temperature_2m", model: str = "gfs_seamless",
                  previous_days: int = 5, temperature_unit: str = "fahrenheit",
                  timezone: str = "UTC") -> pd.DataFrame:
    """Archived hourly forecasts issued 1..N days earlier, for error modelling.

    The previous-runs endpoint only serves hourly variables. Columns are
    ``<variable>`` (the most recent run) and ``<variable>_previous_dayK``; take
    a daily max per local date to get the lead-K forecast of the daily high.
    """
    hourly = [variable] + [f"{variable}_previous_day{k}" for k in range(1, previous_days + 1)]
    params = {
        "latitude": lat, "longitude": lon, "start_date": str(start), "end_date": str(end),
        "hourly": ",".join(hourly), "models": model, "temperature_unit": temperature_unit,
        "precipitation_unit": "inch", "timezone": timezone,
    }
    js = http.get_json(PREVIOUS_RUNS_URL, params=params, source="open_meteo")
    return _frame(js["hourly"])
