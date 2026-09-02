"""Kelly criterion sizing with fees.

Conventions: ``p`` is the probability of winning, ``b`` is net odds (profit per
unit staked on a win). A binary contract that pays 1 if the event happens,
bought at ``price`` with a per-contract ``fee``, has ``b = (1 - cost) / cost``
where ``cost = price + fee``.
"""
from __future__ import annotations

import math


def kelly_fraction(p: float, b: float) -> float:
    """Full-Kelly fraction of bankroll for win probability ``p`` at net odds ``b``.

    Clamped to [0, 1]. Returns 0 when there is no edge.
    """
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"p must be in [0, 1], got {p}")
    if b <= 0:
        return 0.0
    f = (p * (b + 1.0) - 1.0) / b
    return min(1.0, max(0.0, f))


def kelly_binary_contract(p: float, price: float, fee: float = 0.0) -> float:
    """Kelly fraction for a 0/1 contract bought at ``price`` plus ``fee``.

    ``price`` and ``fee`` are in the same units as the payout (dollars per
    contract that pays 1). The fee is paid whether or not the contract wins.
    """
    if fee < 0:
        raise ValueError("fee must be >= 0")
    cost = price + fee
    if cost <= 0.0 or cost >= 1.0:
        return 0.0
    b = (1.0 - cost) / cost
    return kelly_fraction(p, b)


def fractional_kelly(f_full: float, multiplier: float = 0.25, cap: float | None = None) -> float:
    """Scale a full-Kelly fraction (quarter Kelly by default), optionally capped."""
    if multiplier < 0:
        raise ValueError("multiplier must be >= 0")
    f = f_full * multiplier
    if cap is not None:
        f = min(f, cap)
    return f


def expected_log_growth(p: float, b: float, f: float) -> float:
    """Expected log growth per bet when staking fraction ``f`` at odds ``b``."""
    if f >= 1.0:
        return -math.inf
    if f <= 0.0:
        return 0.0
    return p * math.log1p(f * b) + (1.0 - p) * math.log1p(-f)
