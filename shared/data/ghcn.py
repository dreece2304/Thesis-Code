"""GHCN-Daily station history via the NCEI access API (no key needed).

Used for multi-year forecast-vs-observed bias correction.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import http
from .cache import cached_frame

URL = "https://www.ncei.noaa.gov/access/services/data/v1"

# GHCN ids for the Kalshi station set (ASOS first-order stations).
GHCN_IDS = {
    "KNYC": "USW00094728",
    "KMDW": "USW00014819",
    "KMIA": "USW00012839",
    "KAUS": "USW00013904",
    "KDEN": "USW00003017",
    "KLAX": "USW00023174",
    "KPHL": "USW00013739",
}


@cached_frame("ghcn_daily", ttl_seconds=24 * 3600)
def daily(station_id: str, start: str | date, end: str | date,
          datatypes=("TMAX", "TMIN", "PRCP"), units: str = "standard") -> pd.DataFrame:
    """Daily summaries. ``units='standard'`` gives F and inches."""
    params = {
        "dataset": "daily-summaries", "stations": station_id,
        "startDate": str(start), "endDate": str(end),
        "dataTypes": ",".join(datatypes), "format": "json", "units": units,
        "includeAttributes": "false",
    }
    js = http.get_json(URL, params=params, source="ghcn")
    df = pd.DataFrame(js)
    if df.empty:
        return pd.DataFrame(columns=["DATE", "STATION", *datatypes]).set_index("DATE")
    df["DATE"] = pd.to_datetime(df["DATE"])
    for c in datatypes:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.set_index("DATE").sort_index()
