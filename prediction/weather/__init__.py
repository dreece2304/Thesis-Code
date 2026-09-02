"""Kalshi daily-high temperature model. Spec: docs/KALSHI_WEATHER_SPEC.md.

Paper trading only. ``live.run`` refuses to start unless ``PAPER=1``.
"""
from .stations import ACTIVE, MODELS, STATIONS, Station

__all__ = ["ACTIVE", "MODELS", "STATIONS", "Station"]
