"""Kalshi fee model.

Taker fee per contract = 0.07 x price x (1 - price). Maker fee = 25% of that.
Fees are charged on the whole order and rounded up to the next cent.
Prices are in dollars (0.01 to 0.99).
"""
from __future__ import annotations

import math

TAKER_RATE = 0.07
MAKER_SHARE = 0.25


def _ceil_cents(x: float) -> float:
    # round() guards against 0.0175 * 100 = 1.7499999 style float noise
    return math.ceil(round(x * 100.0, 6)) / 100.0


def _check_price(price: float) -> float:
    price = float(price)
    if not 0.0 < price < 1.0:
        raise ValueError(f"price must be strictly between 0 and 1, got {price}")
    return price


def raw_taker_fee(price: float) -> float:
    """Unrounded taker fee for one contract."""
    price = _check_price(price)
    return TAKER_RATE * price * (1.0 - price)


def kalshi_fee(price: float, contracts: float = 1, maker: bool = False) -> float:
    """Total fee in dollars for ``contracts`` at ``price``, rounded up to the cent."""
    if contracts <= 0:
        raise ValueError("contracts must be > 0")
    raw = raw_taker_fee(price) * contracts
    if maker:
        raw *= MAKER_SHARE
    return _ceil_cents(raw)


def fee_per_contract(price: float, contracts: float = 1, maker: bool = False) -> float:
    """Effective per-contract fee after rounding (use this in Kelly sizing)."""
    return kalshi_fee(price, contracts, maker) / contracts


def expected_fee_rate(price: float, maker: bool = False) -> float:
    """Fee as a fraction of the contract price, unrounded (for quick screens)."""
    f = raw_taker_fee(price) * (MAKER_SHARE if maker else 1.0)
    return f / price
