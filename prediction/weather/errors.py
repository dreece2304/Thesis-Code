"""Fit error distributions per station, lead, month and model; recent variances; diagnostics."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from .model import ErrorDist, fit_error_distribution

KEY = ["station", "lead", "model", "month", "wet"]
WET_IN = 0.05
MIN_N_WET = 40


def fits_path() -> Path:
    return Path(os.environ.get("DATA_CACHE_DIR", "data_cache")) / "weather" / "fits.parquet"


def _month_pool(archive: pd.DataFrame, month: int, width: int) -> pd.DataFrame:
    months = {((month - 1 + k) % 12) + 1 for k in range(-width, width + 1)}
    return archive[archive["target_date"].dt.month.isin(months)]


def fit_errors(archive: pd.DataFrame, before: pd.Timestamp | None = None, min_n: int = 60,
               max_pool: int = 2, leads=None, months=None) -> pd.DataFrame:
    """One fit per (station, lead, model, month) using data strictly before ``before``.

    If a calendar month has fewer than ``min_n`` errors it is pooled with its
    neighbours (up to ``max_pool`` months each side); ``pool`` records how far.
    """
    a = archive.dropna(subset=["error"])
    a = a[a["lead"] > 0]
    if before is not None:
        a = a[a["target_date"] < pd.Timestamp(before)]
    if leads is not None:
        a = a[a["lead"].isin(list(leads))]
    rows = []
    for (st, lead, model), g in a.groupby(["station", "lead", "model"]):
        for month in (months or range(1, 13)):
            pool = 0
            sub = _month_pool(g, month, 0)
            while len(sub) < min_n and pool < max_pool:
                pool += 1
                sub = _month_pool(g, month, pool)
            if len(sub) < 5:
                continue
            d = fit_error_distribution(sub["error"].to_numpy())
            rec = d.to_record()
            rec.update({"station": st, "lead": int(lead), "model": model, "month": month, "wet": -1, "pool": pool,
                        "skew": float(pd.Series(sub["error"]).skew())})
            rows.append(rec)
            # wet-day split: the model's own forecast precipitation for the target day.
            # Fitted on a wider month pool (all year if needed) because wet days are scarce.
            if "precip" in sub and sub["precip"].notna().any():
                for wet in (0, 1):
                    w = sub[(sub["precip"] >= WET_IN) == bool(wet)]
                    wpool = pool
                    while len(w) < MIN_N_WET and wpool < 5:
                        wpool += 1
                        w = _month_pool(g, month, wpool)
                        w = w[(w["precip"] >= WET_IN) == bool(wet)]
                    if len(w) < MIN_N_WET:
                        continue
                    dw = fit_error_distribution(w["error"].to_numpy())
                    recw = dw.to_record()
                    recw.update({"station": st, "lead": int(lead), "model": model, "month": month, "wet": wet,
                                 "pool": wpool, "skew": float(pd.Series(w["error"]).skew())})
                    rows.append(recw)
    return pd.DataFrame(rows)


def save_fits(fits: pd.DataFrame, path: str | Path | None = None) -> Path:
    p = Path(path) if path else fits_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fits.to_parquet(p, index=False)
    return p


def load_fits(path: str | Path | None = None) -> pd.DataFrame:
    p = Path(path) if path else fits_path()
    return pd.read_parquet(p)


def lookup(fits: pd.DataFrame, station: str, lead: int, month: int,
           wet: dict[str, bool] | None = None) -> dict[str, ErrorDist]:
    """model -> ErrorDist for one station, lead and month.

    ``wet`` maps model -> whether that model forecasts a wet day; when given
    and a wet/dry split exists for the model, the split distribution is used.
    """
    sub = fits[(fits.station == station) & (fits.lead == lead) & (fits.month == month)]
    if "wet" not in sub:
        sub = sub.assign(wet=-1)
    out = {}
    for model, g in sub.groupby("model"):
        want = -1 if wet is None or model not in wet else int(bool(wet[model]))
        r = g[g.wet == want]
        if r.empty:
            r = g[g.wet == -1]
        if r.empty:
            continue
        out[model] = ErrorDist.from_record(r.iloc[0].to_dict())
    return out


def recent_variance(archive: pd.DataFrame, station: str, lead: int, asof: pd.Timestamp,
                    window_days: int = 60, min_n: int = 10) -> dict[str, float | None]:
    """model -> variance of errors with target_date in [asof - window, asof)."""
    asof = pd.Timestamp(asof)
    a = archive[(archive.station == station) & (archive.lead == lead)
                & (archive.target_date < asof) & (archive.target_date >= asof - pd.Timedelta(days=window_days))]
    out = {}
    for model, g in a.dropna(subset=["error"]).groupby("model"):
        out[model] = float(g["error"].var(ddof=1)) if len(g) >= min_n else None
    return out


def recent_bias(archive: pd.DataFrame, station: str, lead: int, asof: pd.Timestamp,
                window_days: int = 60, min_n: int = 10) -> dict[str, float]:
    """model -> mean error (settlement - forecast) over the trailing window before asof."""
    asof = pd.Timestamp(asof)
    a = archive[(archive.station == station) & (archive.lead == lead)
                & (archive.target_date < asof) & (archive.target_date >= asof - pd.Timedelta(days=window_days))]
    out = {}
    for model, g in a.dropna(subset=["error"]).groupby("model"):
        if len(g) >= min_n:
            out[model] = float(g["error"].mean())
    return out


def summary(fits: pd.DataFrame) -> pd.DataFrame:
    """Mean bias and sd by station, lead and model (averaged over months)."""
    return fits.groupby(["station", "lead", "model"]).agg(
        n=("n", "sum"), bias=("mean", "mean"), sd=("sd", "mean"), skew=("skew", "mean"),
        kde_share=("kind", lambda s: float((s == "kde").mean()))).reset_index()


def diagnostics(archive: pd.DataFrame, out_dir: str | Path) -> list[Path]:
    """Error sd vs lead per station and model; monthly bias per station. Saves PNGs."""
    import matplotlib
    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    a = archive.dropna(subset=["error"])
    a = a[a["lead"] > 0]
    fig, axes = plt.subplots(1, a.station.nunique(), figsize=(4 * a.station.nunique(), 3.5), squeeze=False)
    for ax, (st, g) in zip(axes[0], a.groupby("station")):
        for model, gm in g.groupby("model"):
            s = gm.groupby("lead")["error"].agg(["std", "mean"])
            ax.plot(s.index, s["std"], "o-", label=f"{model} sd")
            ax.plot(s.index, s["mean"], "x--", alpha=0.6, label=f"{model} bias")
        ax.axhline(0, color="k", lw=0.5)
        ax.set_title(st)
        ax.set_xlabel("lead (days)")
        ax.set_ylabel("deg F")
        ax.legend(fontsize=6)
    fig.tight_layout()
    p = out_dir / "error_vs_lead.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    paths.append(p)

    fig, ax = plt.subplots(figsize=(7, 3.5))
    for st, g in a[a["lead"] == 1].groupby("station"):
        s = g.groupby(g["target_date"].dt.month)["error"].mean()
        ax.plot(s.index, s.values, "o-", label=st)
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("month")
    ax.set_ylabel("mean error at lead 1 (deg F)")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "seasonal_bias.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    paths.append(p)
    return paths
