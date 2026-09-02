"""Regime overlay for sizing. Gate from project 3: OOS accuracy >= 60% or not used."""
from __future__ import annotations

MIN_REGIME_ACCURACY = 0.60
DEFAULT_SCALES = {0: 1.0, 1: 0.75, 2: 0.5}  # calm, transitional, stressed


class RegimeGateError(ValueError):
    """Raised when a regime signal below the accuracy gate is used for sizing."""


def regime_scale(regime: int | None, oos_accuracy: float | None,
                 scales: dict[int, float] | None = None) -> float:
    """Exposure multiplier for a regime state.

    Returns 1.0 (no overlay) when ``regime`` is None. Raises if the signal's
    out-of-sample accuracy is unknown or below ``MIN_REGIME_ACCURACY``.
    """
    if regime is None:
        return 1.0
    if oos_accuracy is None or not 0 <= oos_accuracy <= 1:
        raise RegimeGateError("regime accuracy unknown; overlay not allowed")
    if oos_accuracy < MIN_REGIME_ACCURACY:
        raise RegimeGateError(
            f"regime OOS accuracy {oos_accuracy:.2f} < {MIN_REGIME_ACCURACY:.2f}; overlay not allowed")
    scales = scales or DEFAULT_SCALES
    if regime not in scales:
        raise RegimeGateError(f"unknown regime {regime!r}")
    return float(scales[regime])
