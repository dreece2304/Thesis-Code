"""FRED series. Uses ``fredapi`` when a key is set, else the public CSV endpoint."""
from __future__ import annotations

import io
import os

import pandas as pd

from . import http
from .cache import cached_frame

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# Series used across projects.
SERIES = {
    "cpi": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "payrolls": "PAYEMS",
    "claims": "ICSA",
    "unrate": "UNRATE",
    "fed_funds": "DFF",
    "t10y": "DGS10",
    "t2y": "DGS2",
    "t3m": "DGS3MO",
    "vix": "VIXCLS",
}


@cached_frame("fred", ttl_seconds=12 * 3600)
def series(series_id: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """One series as a DataFrame with a ``value`` column indexed by date."""
    key = os.environ.get("FRED_API_KEY")
    if key:
        try:
            from fredapi import Fred  # optional dependency
            s = Fred(api_key=key).get_series(series_id, observation_start=start, observation_end=end)
            df = s.rename("value").to_frame()
            df.index.name = "date"
            return df
        except ImportError:
            pass
    text = http.get_text(CSV_URL, params={"id": series_id}, source="fred")
    df = pd.read_csv(io.StringIO(text), na_values=["."])
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    if start:
        df = df.loc[str(start):]
    if end:
        df = df.loc[:str(end)]
    return df
