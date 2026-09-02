"""National Weather Service API: station observations and metadata."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from . import http
from .cache import cached_frame

BASE = "https://api.weather.gov"

# Kalshi resolves its city temperature markets on these ASOS stations.
KALSHI_STATIONS = {
    "NYC": "KNYC",   # Central Park
    "CHI": "KMDW",   # Midway
    "MIA": "KMIA",
    "AUS": "KAUS",
    "DEN": "KDEN",
    "LAX": "KLAX",
    "PHL": "KPHL",
}

_FIELDS = {
    "temperature": "temperature_c",
    "dewpoint": "dewpoint_c",
    "windSpeed": "wind_kmh",
    "precipitationLastHour": "precip_mm_1h",
    "maxTemperatureLast24Hours": "tmax24_c",
    "minTemperatureLast24Hours": "tmin24_c",
}


def _obs_rows(features: list[dict]) -> pd.DataFrame:
    rows = []
    for f in features:
        p = f.get("properties", {})
        row = {"time": p.get("timestamp"), "station": p.get("station", "").rsplit("/", 1)[-1]}
        for src, dst in _FIELDS.items():
            v = p.get(src) or {}
            row[dst] = v.get("value")
        rows.append(row)
    df = pd.DataFrame(rows, columns=["time", "station", *_FIELDS.values()])
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.sort_values("time").set_index("time")
        df["temperature_f"] = df["temperature_c"] * 9 / 5 + 32
    return df


@cached_frame("nws_observations", ttl_seconds=900)
def station_observations(station: str, start: str | datetime | None = None,
                         end: str | datetime | None = None, limit: int = 500) -> pd.DataFrame:
    """Observations for an ASOS/AWOS station id (e.g. ``KNYC``)."""
    params: dict = {"limit": limit}
    if start is not None:
        params["start"] = pd.Timestamp(start).tz_localize("UTC").isoformat() if pd.Timestamp(start).tzinfo is None else pd.Timestamp(start).isoformat()
    if end is not None:
        params["end"] = pd.Timestamp(end).tz_localize("UTC").isoformat() if pd.Timestamp(end).tzinfo is None else pd.Timestamp(end).isoformat()
    js = http.get_json(f"{BASE}/stations/{station}/observations", params=params,
                       headers={"Accept": "application/geo+json"}, source="nws")
    return _obs_rows(js.get("features", []))


def latest_observation(station: str) -> dict:
    js = http.get_json(f"{BASE}/stations/{station}/observations/latest",
                       headers={"Accept": "application/geo+json"}, source="nws")
    df = _obs_rows([js])
    return df.reset_index().iloc[0].to_dict() if not df.empty else {}


def point(lat: float, lon: float) -> dict:
    """Grid metadata for a coordinate (forecast office, grid id, stations URL)."""
    js = http.get_json(f"{BASE}/points/{lat:.4f},{lon:.4f}", source="nws")
    return js.get("properties", {})
