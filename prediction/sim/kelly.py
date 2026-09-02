"""Kelly bankroll simulator for binary prediction-market contracts.

Implemented from the brief's spec (the original ``kelly_bankroll_simulator.jsx``
was not available when this was written; reconcile presets and RNG against it
when the file is provided; ``shared.sim.rng.mulberry32`` is there for that).

Mechanics per bet (vectorised across paths):
  * fraction f = multiplier x full-Kelly for (p_true, price, fee per contract)
  * stake = f x bankroll, converted to contracts at cost = price + fee
  * win with probability p_true: bankroll += contracts x (1 - cost)
  * lose: bankroll -= contracts x cost
  * a path is ruined once bankroll < ruin_threshold x starting bankroll,
    after which it stops betting.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from shared.sim.kelly import fractional_kelly, kelly_binary_contract
from shared.sim.rng import SeededRNG

from ..fees import fee_per_contract


@dataclass(frozen=True)
class MarketPreset:
    name: str
    price: float       # market price of the side we buy
    p_true: float      # our true (calibrated) probability for that side
    maker: bool = False
    description: str = ""

    @property
    def edge(self) -> float:
        return self.p_true - self.price


PRESETS: dict[str, MarketPreset] = {
    "coin_flip": MarketPreset("coin_flip", 0.50, 0.50, description="no edge; fees only"),
    "weather_daily": MarketPreset("weather_daily", 0.55, 0.62,
                                  description="city temperature bucket, thin book, taker"),
    "weather_maker": MarketPreset("weather_maker", 0.55, 0.62, maker=True,
                                  description="same market, resting orders"),
    "econ_release": MarketPreset("econ_release", 0.40, 0.46,
                                 description="CPI or payrolls bucket"),
    "fed_meeting": MarketPreset("fed_meeting", 0.85, 0.90,
                                description="single-meeting rate decision"),
    "longshot_no": MarketPreset("longshot_no", 0.92, 0.96,
                                description="selling 'will X happen' longshots (buying NO)"),
    "overconfident": MarketPreset("overconfident", 0.55, 0.52,
                                  description="believed edge 0.62 but true prob 0.52; negative edge"),
}


@dataclass
class BankrollResult:
    final: np.ndarray                 # final bankroll per path
    paths: np.ndarray | None          # (n_paths, n_bets + 1) if kept
    ruined: np.ndarray                # bool per path
    fraction: float                   # fraction of bankroll per bet
    start: float
    meta: dict = field(default_factory=dict)

    @property
    def ruin_prob(self) -> float:
        return float(self.ruined.mean())

    @property
    def median_final(self) -> float:
        return float(np.median(self.final))

    @property
    def p5(self) -> float:
        return float(np.percentile(self.final, 5))

    @property
    def p95(self) -> float:
        return float(np.percentile(self.final, 95))

    @property
    def mean_log_growth(self) -> float:
        """Mean log(final / start) per bet over surviving and ruined paths."""
        n = self.meta.get("n_bets", 1)
        with np.errstate(divide="ignore"):
            g = np.log(np.maximum(self.final, 1e-12) / self.start) / n
        return float(np.mean(g))

    def summary(self) -> dict:
        return {
            "fraction": self.fraction, "ruin_prob": self.ruin_prob,
            "median_final": self.median_final, "p5": self.p5, "p95": self.p95,
            "mean_log_growth": self.mean_log_growth, **self.meta,
        }


def simulate_bankroll(
    p_true: float,
    price: float,
    kelly_multiplier: float = 0.25,
    n_bets: int = 500,
    n_paths: int = 2000,
    bankroll: float = 1000.0,
    maker: bool = False,
    p_believed: float | None = None,
    fee_free: bool = False,
    max_fraction: float | None = None,
    ruin_threshold: float = 0.10,
    keep_paths: bool = False,
    rng: SeededRNG | None = None,
) -> BankrollResult:
    """Monte Carlo of repeated bets at one price.

    ``p_believed`` sizes the bet (defaults to ``p_true``); outcomes are drawn
    from ``p_true``. Set them apart to simulate miscalibration.
    """
    if n_bets < 1 or n_paths < 1:
        raise ValueError("n_bets and n_paths must be >= 1")
    if not 0.0 < price < 1.0:
        raise ValueError("price must be in (0, 1)")
    if not 0.0 <= p_true <= 1.0:
        raise ValueError("p_true must be in [0, 1]")
    rng = rng or SeededRNG(0)
    p_size = p_true if p_believed is None else p_believed
    fee = 0.0 if fee_free else fee_per_contract(price, contracts=100, maker=maker)
    f_full = kelly_binary_contract(p_size, price, fee)
    f = fractional_kelly(f_full, kelly_multiplier, cap=max_fraction)
    cost = price + fee

    b = np.full(n_paths, float(bankroll))
    alive = np.ones(n_paths, dtype=bool)
    floor = ruin_threshold * bankroll
    paths = np.empty((n_paths, n_bets + 1)) if keep_paths else None
    if keep_paths:
        paths[:, 0] = b

    wins = rng.uniform(size=(n_bets, n_paths)) < p_true
    for i in range(n_bets):
        stake = np.where(alive, f * b, 0.0)
        contracts = stake / cost
        pnl = np.where(wins[i], contracts * (1.0 - cost), -contracts * cost)
        b = b + pnl
        alive &= b >= floor
        if keep_paths:
            paths[:, i + 1] = b

    return BankrollResult(
        final=b, paths=paths, ruined=~alive, fraction=f, start=bankroll,
        meta={"p_true": p_true, "p_believed": p_size, "price": price, "fee_per_contract": fee,
              "kelly_full": f_full, "kelly_multiplier": kelly_multiplier, "n_bets": n_bets,
              "n_paths": n_paths, "maker": maker},
    )


def simulate_preset(name: str, **kw) -> BankrollResult:
    p = PRESETS[name]
    kw.setdefault("maker", p.maker)
    return simulate_bankroll(p.p_true, p.price, **kw)


def sweep_multipliers(p_true: float, price: float, multipliers=(0.1, 0.25, 0.5, 1.0, 1.5, 2.0),
                      seed: int = 0, **kw) -> list[dict]:
    """Summaries across Kelly multipliers, same random draws for each."""
    out = []
    for m in multipliers:
        r = simulate_bankroll(p_true, price, kelly_multiplier=m, rng=SeededRNG(seed), **kw)
        out.append(r.summary())
    return out
