"""Milestone 1 data pipelines: FRED macro, VIX term structure, realised vol."""
from __future__ import annotations

import numpy as np
import pandas as pd

from shared.data import fred, prices

MACRO_SERIES = {
    "cpi": "CPIAUCSL", "core_cpi": "CPILFESL", "payrolls": "PAYEMS", "claims": "ICSA",
    "unrate": "UNRATE", "fed_funds": "DFF", "t3m": "DGS3MO", "t2y": "DGS2", "t10y": "DGS10",
}
VIX_SERIES = {"vix": "VIXCLS", "vix3m": "VXVCLS"}


def macro_panel(start: str = "1990-01-01", end: str | None = None, **kw) -> pd.DataFrame:
    """Monthly panel (month-end, last observation) of the macro series plus derived columns."""
    cols = {}
    for name, sid in MACRO_SERIES.items():
        s = fred.series(sid, start=start, end=end, **kw)["value"]
        cols[name] = s.resample("ME").last()
    df = pd.DataFrame(cols)
    df["cpi_yoy"] = df["cpi"].pct_change(12)
    df["core_cpi_yoy"] = df["core_cpi"].pct_change(12)
    df["payrolls_chg"] = df["payrolls"].diff()
    df["curve_10y_2y"] = df["t10y"] - df["t2y"]
    df["curve_10y_3m"] = df["t10y"] - df["t3m"]
    return df


def vix_term_structure(start: str = "2007-01-01", end: str | None = None, **kw) -> pd.DataFrame:
    """Daily VIX, 3-month VIX and their ratio (>1 means backwardation, stress)."""
    v = fred.series(VIX_SERIES["vix"], start=start, end=end, **kw)["value"].rename("vix")
    v3 = fred.series(VIX_SERIES["vix3m"], start=start, end=end, **kw)["value"].rename("vix3m")
    df = pd.concat([v, v3], axis=1).dropna(how="all")
    df["ratio"] = df["vix"] / df["vix3m"]
    return df


def realised_vol(daily_prices: pd.Series, window: int = 21, periods_per_year: int = 252) -> pd.Series:
    """Annualised rolling realised vol from daily prices (log returns)."""
    r = np.log(daily_prices).diff()
    return (r.rolling(window).std() * np.sqrt(periods_per_year)).rename("realised_vol")


def spy_realised_vol(window: int = 21, start: str = "1993-01-01", **kw) -> pd.Series:
    px = prices.daily_prices("SPY", start=start, **kw)["SPY"]
    return realised_vol(px, window)


def monthly_returns(px: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return px.resample("ME").last().pct_change().dropna(how="all")


def regime_features(start: str = "2007-01-01", **kw) -> pd.DataFrame:
    """Monthly features for the regime model: SPY return, realised vol, VIX ratio."""
    px = prices.daily_prices("SPY", start=start, **kw)["SPY"]
    ts = vix_term_structure(start=start, **kw)
    df = pd.DataFrame({
        "ret": monthly_returns(px),
        "rvol": realised_vol(px).resample("ME").last(),
        "vix": ts["vix"].resample("ME").last(),
        "vix_ratio": ts["ratio"].resample("ME").mean(),
    })
    df["next_rvol"] = df["rvol"].shift(-1)  # target for validation only
    return df.dropna(subset=["ret", "rvol"])
