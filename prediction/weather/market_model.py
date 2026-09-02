"""Commoditised baseline: NWS point forecast high with a fixed 3 deg F normal.

Measures how much of any edge is our model versus crowd sloppiness. In the
backtest, where archived NWS point forecasts are not available, the mean of
the deterministic model forecasts stands in for the NWS number.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats

from shared.data import http

from .stations import Station, cut

NWS = "https://api.weather.gov"
BASELINE_SD = 3.0


def nws_point_forecast(station: Station) -> pd.DataFrame:
    """Daytime period highs from the NWS gridpoint forecast: columns date, high, name."""
    pt = http.get_json(f"{NWS}/points/{station.lat:.4f},{station.lon:.4f}", source="nws")["properties"]
    fc = http.get_json(pt["forecast"], source="nws")["properties"]["periods"]
    rows = [{"date": datetime.fromisoformat(p["startTime"]).date(), "high": p["temperature"], "name": p["name"]}
            for p in fc if p.get("isDaytime")]
    return pd.DataFrame(rows)


def baseline_probability(forecast_high: float, threshold: int, side: str, sd: float = BASELINE_SD) -> float:
    lo, hi = cut(threshold, side)
    upper = 1.0 if hi == np.inf else stats.norm.cdf((hi - forecast_high) / sd)
    lower = 0.0 if lo == -np.inf else stats.norm.cdf((lo - forecast_high) / sd)
    return float(np.clip(upper - lower, 0.0, 1.0))


def reconstructed_quotes(p: float, rng: np.random.Generator, noise_sd_logit: float = 0.25,
                         half_spread: float = 0.01, tick: float = 0.01) -> tuple[float, float, float]:
    """Noisy market (bid, ask, mid) around a baseline probability.

    Noise is applied in logit space so quotes stay inside (0, 1); the spread is
    two ticks by default. Calibrate ``noise_sd_logit`` from live order books.
    """
    p = float(np.clip(p, 0.02, 0.98))
    z = np.log(p / (1 - p)) + rng.normal(0, noise_sd_logit)
    mid = 1 / (1 + np.exp(-z))
    bid = max(tick, np.floor((mid - half_spread) / tick) * tick)
    ask = min(1 - tick, np.ceil((mid + half_spread) / tick) * tick)
    return float(bid), float(ask), float(mid)
