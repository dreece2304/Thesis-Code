"""DuckDB-backed prediction ledger with Brier scoring and calibration plots."""
from __future__ import annotations

import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import duckdb
import numpy as np
import pandas as pd

DEFAULT_PATH = "data_cache/ledger.duckdb"

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id              VARCHAR PRIMARY KEY,
    project         VARCHAR NOT NULL,
    market_or_asset VARCHAR NOT NULL,
    timestamp       TIMESTAMP NOT NULL,
    model_prob      DOUBLE NOT NULL,
    market_prob     DOUBLE,
    stake           DOUBLE NOT NULL DEFAULT 0.0,
    outcome         INTEGER,
    resolved_at     TIMESTAMP,
    notes           VARCHAR
);
"""

COLUMNS = [
    "id", "project", "market_or_asset", "timestamp", "model_prob",
    "market_prob", "stake", "outcome", "resolved_at", "notes",
]


def utcnow() -> datetime:
    """Naive UTC now (DuckDB TIMESTAMP is timezone-naive)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive(ts: datetime | None) -> datetime:
    if ts is None:
        return utcnow()
    if isinstance(ts, str):
        ts = pd.Timestamp(ts).to_pydatetime()
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def _check_prob(p, name: str, allow_none: bool = False) -> float | None:
    if p is None:
        if allow_none:
            return None
        raise ValueError(f"{name} must not be None")
    p = float(p)
    if math.isnan(p) or not 0.0 <= p <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {p}")
    return p


def brier_score(probs: Iterable[float], outcomes: Iterable[int]) -> float:
    """Mean squared error between probabilities and 0/1 outcomes."""
    p = np.asarray(list(probs), dtype=float)
    y = np.asarray(list(outcomes), dtype=float)
    if p.size == 0:
        return float("nan")
    if p.shape != y.shape:
        raise ValueError("probs and outcomes must have the same length")
    return float(np.mean((p - y) ** 2))


class Ledger:
    """Prediction ledger. Use as a context manager or call ``close()``."""

    def __init__(self, path: str | os.PathLike | None = None):
        path = str(path or os.environ.get("LEDGER_PATH", DEFAULT_PATH))
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.con = duckdb.connect(path)
        self.con.execute(SCHEMA)

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- writes --------------------------------------------------------------
    def log_prediction(
        self,
        project: str,
        market_or_asset: str,
        model_prob: float,
        market_prob: float | None = None,
        stake: float = 0.0,
        timestamp: datetime | None = None,
        notes: str | None = None,
        outcome: int | None = None,
        resolved_at: datetime | None = None,
        id: str | None = None,
    ) -> str:
        """Insert one prediction and return its id.

        ``model_prob`` is the probability the model assigns to the event.
        ``market_prob`` is the market-implied probability at the same time,
        if known. ``outcome`` may be given immediately for backfills.
        """
        if not project or not market_or_asset:
            raise ValueError("project and market_or_asset are required")
        model_prob = _check_prob(model_prob, "model_prob")
        market_prob = _check_prob(market_prob, "market_prob", allow_none=True)
        stake = float(stake)
        if stake < 0:
            raise ValueError("stake must be >= 0")
        if outcome is not None:
            outcome = int(bool(outcome))
            resolved_at = _as_naive(resolved_at)
        elif resolved_at is not None:
            raise ValueError("resolved_at given without outcome")
        pid = id or uuid.uuid4().hex
        self.con.execute(
            "INSERT INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [pid, project, market_or_asset, _as_naive(timestamp), model_prob,
             market_prob, stake, outcome, resolved_at, notes],
        )
        return pid

    def resolve(self, id: str, outcome: int | bool, resolved_at: datetime | None = None) -> None:
        """Record the realised outcome (0/1) for a prediction id."""
        outcome = int(bool(outcome))
        cur = self.con.execute(
            "UPDATE predictions SET outcome = ?, resolved_at = ? WHERE id = ?",
            [outcome, _as_naive(resolved_at), id],
        )
        n = cur.fetchall()
        # DuckDB returns the affected row count as the single result row.
        if n and n[0][0] == 0:
            raise KeyError(f"no prediction with id {id!r}")

    def resolve_market(self, market_or_asset: str, outcome: int | bool,
                       resolved_at: datetime | None = None) -> int:
        """Resolve every unresolved prediction on a market. Returns count."""
        outcome = int(bool(outcome))
        cur = self.con.execute(
            "UPDATE predictions SET outcome = ?, resolved_at = ? "
            "WHERE market_or_asset = ? AND outcome IS NULL",
            [outcome, _as_naive(resolved_at), market_or_asset],
        )
        rows = cur.fetchall()
        return int(rows[0][0]) if rows else 0

    # -- reads ---------------------------------------------------------------
    def predictions(self, project: str | None = None,
                    resolved: bool | None = None) -> pd.DataFrame:
        sql = "SELECT * FROM predictions"
        clauses, params = [], []
        if project is not None:
            clauses.append("project = ?")
            params.append(project)
        if resolved is True:
            clauses.append("outcome IS NOT NULL")
        elif resolved is False:
            clauses.append("outcome IS NULL")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY timestamp"
        return self.con.execute(sql, params).df()

    def brier_by_project(self) -> pd.DataFrame:
        """Brier score of the model and of the market, per project.

        ``brier_market`` uses only rows where ``market_prob`` is present, so
        ``n_market`` may be smaller than ``n``. ``skill`` is
        ``1 - brier_model_on_market_rows / brier_market``: positive means the
        model beats the market on the rows where both exist.
        """
        df = self.predictions(resolved=True)
        rows = []
        for project, g in df.groupby("project", sort=True):
            m = g.dropna(subset=["market_prob"])
            b_model = brier_score(g.model_prob, g.outcome)
            b_market = brier_score(m.market_prob, m.outcome) if len(m) else float("nan")
            b_model_on_m = brier_score(m.model_prob, m.outcome) if len(m) else float("nan")
            skill = (1 - b_model_on_m / b_market) if len(m) and b_market > 0 else float("nan")
            rows.append({
                "project": project, "n": int(len(g)), "brier_model": b_model,
                "n_market": int(len(m)), "brier_market": b_market, "skill": skill,
            })
        return pd.DataFrame(rows, columns=[
            "project", "n", "brier_model", "n_market", "brier_market", "skill"])

    def calibration_curve(self, project: str | None = None, bins: int = 10,
                          column: str = "model_prob") -> pd.DataFrame:
        """Bin resolved predictions by forecast probability.

        Returns one row per non-empty bin with ``bin_lo``, ``bin_hi``,
        ``mean_prob``, ``frac_positive`` and ``n``.
        """
        if bins < 1:
            raise ValueError("bins must be >= 1")
        df = self.predictions(project=project, resolved=True).dropna(subset=[column])
        edges = np.linspace(0.0, 1.0, bins + 1)
        if df.empty:
            return pd.DataFrame(columns=["bin_lo", "bin_hi", "mean_prob", "frac_positive", "n"])
        idx = np.clip(np.digitize(df[column].to_numpy(), edges[1:-1], right=False), 0, bins - 1)
        df = df.assign(_bin=idx)
        out = df.groupby("_bin").agg(
            mean_prob=(column, "mean"), frac_positive=("outcome", "mean"), n=("outcome", "size")
        ).reset_index()
        out["bin_lo"] = edges[out["_bin"]]
        out["bin_hi"] = edges[out["_bin"] + 1]
        return out[["bin_lo", "bin_hi", "mean_prob", "frac_positive", "n"]]

    def reliability_plot(self, project: str | None = None, bins: int = 10,
                         path: str | os.PathLike | None = None):
        """Reliability diagram (model, and market where available).

        Returns the matplotlib Figure. Saves to ``path`` if given.
        """
        import matplotlib
        if path is not None or not os.environ.get("DISPLAY"):
            matplotlib.use("Agg", force=False)
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(5, 5))
        ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
        for col, label in (("model_prob", "model"), ("market_prob", "market")):
            c = self.calibration_curve(project, bins, column=col)
            if not c.empty:
                ax.plot(c.mean_prob, c.frac_positive, "o-", label=label)
                for _, r in c.iterrows():
                    ax.annotate(str(int(r.n)), (r.mean_prob, r.frac_positive),
                                textcoords="offset points", xytext=(4, 4), fontsize=7)
        ax.set_xlabel("forecast probability")
        ax.set_ylabel("observed frequency")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_title(f"reliability: {project or 'all projects'}")
        ax.legend(loc="upper left")
        fig.tight_layout()
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(path, dpi=120)
        return fig


# -- module-level convenience on a default ledger ------------------------------
_default: Ledger | None = None


def default_ledger() -> Ledger:
    global _default
    if _default is None:
        _default = Ledger()
    return _default


def log_prediction(*args, **kwargs) -> str:
    return default_ledger().log_prediction(*args, **kwargs)


def resolve(*args, **kwargs) -> None:
    return default_ledger().resolve(*args, **kwargs)


def brier_by_project() -> pd.DataFrame:
    return default_ledger().brier_by_project()


def calibration_curve(*args, **kwargs) -> pd.DataFrame:
    return default_ledger().calibration_curve(*args, **kwargs)


def reliability_plot(*args, **kwargs):
    return default_ledger().reliability_plot(*args, **kwargs)
