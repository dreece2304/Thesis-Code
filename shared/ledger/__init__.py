"""Calibration ledger: every probability any project produces is logged here.

Backed by DuckDB. See ``Ledger`` for the API. Module-level helpers operate on
a default ledger at ``$LEDGER_PATH`` (default ``data_cache/ledger.duckdb``).
"""
from .ledger import (
    Ledger,
    brier_by_project,
    brier_score,
    calibration_curve,
    default_ledger,
    log_prediction,
    reliability_plot,
    resolve,
)

__all__ = [
    "Ledger",
    "brier_by_project",
    "brier_score",
    "calibration_curve",
    "default_ledger",
    "log_prediction",
    "reliability_plot",
    "resolve",
]
