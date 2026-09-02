import math

import numpy as np
import pandas as pd
import pytest

from shared.sim import (
    SeededRNG, annualised_vol, cagr, drawdown_series, expected_log_growth, fractional_kelly,
    kelly_binary_contract, kelly_fraction, max_drawdown, mulberry32, sharpe, turnover,
)

# Reference values generated with the JS implementation (node v22):
#   function mulberry32(a){return function(){var t=a+=0x6D2B79F5;t=Math.imul(t^t>>>15,t|1);
#   t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296}}
MULBERRY_REF = {
    0: (0.266429208685, 0.000329745701, 0.223272027448),
    1: (0.627073940588, 0.002735721180, 0.527447039960),
    42: (0.601103751920, 0.448290558998, 0.852465793490),
    123456789: (0.257790743839, 0.970772111556, 0.785328014288),
}


@pytest.mark.parametrize("seed,expected", MULBERRY_REF.items())
def test_mulberry32_matches_js(seed, expected):
    g = mulberry32(seed)
    got = [next(g) for _ in range(3)]
    assert got == pytest.approx(expected, abs=1e-12)


def test_mulberry32_range_and_mean():
    g = mulberry32(7)
    xs = np.array([next(g) for _ in range(20000)])
    assert xs.min() >= 0 and xs.max() < 1
    assert abs(xs.mean() - 0.5) < 0.01


def test_seeded_rng_reproducible_and_spawn():
    a, b = SeededRNG(123), SeededRNG(123)
    assert np.array_equal(a.normal(size=5), b.normal(size=5))
    kids = SeededRNG(1).spawn(2)
    assert not np.array_equal(kids[0].uniform(size=5), kids[1].uniform(size=5))
    kids2 = SeededRNG(1).spawn(2)
    assert np.array_equal(kids[0].uniform(size=5), kids2[0].uniform(size=5)) is False  # already consumed
    assert np.array_equal(SeededRNG(1).spawn(2)[1].uniform(size=5), kids2[1].uniform(size=5))
    x = np.arange(10)
    bb = SeededRNG(0).block_bootstrap(x, block=3, length=7)
    assert len(bb) == 7 and set(bb) <= set(x)
    p = SeededRNG(0).bernoulli(0.3, size=10000).mean()
    assert abs(p - 0.3) < 0.02


def test_kelly_fraction_textbook():
    # p=0.6 at even odds -> 20%
    assert kelly_fraction(0.6, 1.0) == pytest.approx(0.2)
    assert kelly_fraction(0.5, 1.0) == 0.0
    assert kelly_fraction(0.4, 1.0) == 0.0
    assert kelly_fraction(1.0, 1.0) == 1.0
    assert kelly_fraction(0.6, 0.0) == 0.0
    with pytest.raises(ValueError):
        kelly_fraction(1.1, 1.0)


def test_kelly_binary_contract_with_fee():
    # price 0.5, no fee: b = 1, p = 0.6 -> 0.2
    assert kelly_binary_contract(0.6, 0.5) == pytest.approx(0.2)
    # a fee reduces the fraction
    assert kelly_binary_contract(0.6, 0.5, fee=0.02) < 0.2
    # fee big enough to kill the edge -> 0
    assert kelly_binary_contract(0.52, 0.5, fee=0.02) == 0.0
    assert kelly_binary_contract(0.9, 0.99, fee=0.02) == 0.0  # cost >= 1
    with pytest.raises(ValueError):
        kelly_binary_contract(0.6, 0.5, fee=-0.01)


def test_fractional_and_growth():
    assert fractional_kelly(0.4) == pytest.approx(0.1)
    assert fractional_kelly(0.4, 0.5, cap=0.15) == pytest.approx(0.15)
    f_star = kelly_fraction(0.6, 1.0)
    g_star = expected_log_growth(0.6, 1.0, f_star)
    assert g_star > expected_log_growth(0.6, 1.0, f_star / 2)
    assert g_star > expected_log_growth(0.6, 1.0, f_star * 2)
    assert expected_log_growth(0.6, 1.0, 0.0) == 0.0
    assert expected_log_growth(0.6, 1.0, 1.0) == -math.inf


def test_metrics():
    eq = [100, 110, 99, 120, 90, 130]
    assert max_drawdown(eq) == pytest.approx(0.25)  # 120 -> 90
    assert drawdown_series(eq)[0] == 0 and drawdown_series(eq)[-1] == 0
    assert cagr([100, 121], periods_per_year=1 / 2) == pytest.approx(0.1)  # two years, 21%
    assert cagr([100] * 13, 12) == 0.0
    r = np.array([0.01, -0.01, 0.02, 0.0])
    assert sharpe(r, 12) == pytest.approx(np.mean(r) / np.std(r, ddof=1) * np.sqrt(12))
    assert annualised_vol(r, 252) == pytest.approx(np.std(r, ddof=1) * np.sqrt(252))
    w = pd.DataFrame({"a": [1.0, 0.0, 1.0], "b": [0.0, 1.0, 0.0]})
    assert turnover(w) == pytest.approx(1.0)  # full switch each period = 100% one-way
    assert turnover(w.iloc[:1]) == 0.0
