"""Station registry: Kalshi series, settlement station ids, coordinates, rounding."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    key: str
    name: str
    series: str          # Kalshi series ticker (KXHIGH*)
    cli: str             # NWS CLI product id named in the market rules
    nws: str             # ASOS station id
    ghcn: str            # GHCN-Daily id for the same site
    lat: float
    lon: float
    tz: str
    tier: int            # 1 = live set, 2 = add after gate, 3 = later


# Rules text confirmed live on 2026-09-02: "recorded at <city> (<CLI id>)".
STATIONS: dict[str, Station] = {
    "NYC": Station("NYC", "New York Central Park", "KXHIGHNY", "CLINYC", "KNYC", "USW00094728",
                   40.779, -73.969, "America/New_York", 1),
    "CHI": Station("CHI", "Chicago Midway", "KXHIGHCHI", "CLIMDW", "KMDW", "USW00014819",
                   41.786, -87.752, "America/Chicago", 1),
    "MIA": Station("MIA", "Miami International", "KXHIGHMIA", "CLIMIA", "KMIA", "USW00012839",
                   25.795, -80.290, "America/New_York", 1),
    "LAX": Station("LAX", "Los Angeles International", "KXHIGHLAX", "CLILAX", "KLAX", "USW00023174",
                   33.938, -118.389, "America/Los_Angeles", 2),
    "AUS": Station("AUS", "Austin Camp Mabry", "KXHIGHAUS", "CLIAUS", "KATT", "USW00013958",
                   30.321, -97.760, "America/Chicago", 2),
    "DEN": Station("DEN", "Denver International", "KXHIGHDEN", "CLIDEN", "KDEN", "USW00003017",
                   39.847, -104.656, "America/Denver", 3),
    "PHL": Station("PHL", "Philadelphia International", "KXHIGHPHIL", "CLIPHL", "KPHL", "USW00013739",
                   39.872, -75.241, "America/New_York", 3),
}

ACTIVE = [s for s in STATIONS.values() if s.tier == 1]
BY_SERIES = {s.series: s for s in STATIONS.values()}

# Open-Meteo model ids (deterministic runs) used for the error archive and live scoring.
MODELS = ("ecmwf_ifs025", "gfs_seamless", "icon_seamless")
LEADS = (1, 2, 3, 4, 5)


def settle(value: float) -> int:
    """Settlement is the integer degrees F reported in the CLI (half rounds up)."""
    return int(math.floor(value + 0.5))


def cut(threshold: int, side: str) -> tuple[float, float]:
    """Continuous interval on the settled integer that makes a contract YES.

    ``above``: settlement >= threshold -> (threshold - 0.5, inf)
    ``below``: settlement <= threshold -> (-inf, threshold + 0.5)
    """
    if side == "above":
        return threshold - 0.5, math.inf
    if side == "below":
        return -math.inf, threshold + 0.5
    raise ValueError(f"side must be 'above' or 'below', got {side!r}")
