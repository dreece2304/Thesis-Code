import numpy as np
import pytest

from prediction.sim.kelly import PRESETS, simulate_bankroll, simulate_preset, sweep_multipliers
from shared.sim.rng import SeededRNG


def test_no_edge_bleeds_fees_and_does_not_grow():
    r = simulate_preset("coin_flip", n_bets=300, n_paths=500, rng=SeededRNG(1))
    # Kelly says do not bet when p == price after fees.
    assert r.fraction == 0.0
    assert np.all(r.final == r.start) and r.ruin_prob == 0.0


def test_positive_edge_quarter_kelly_grows_without_ruin():
    r = simulate_preset("weather_daily", kelly_multiplier=0.25, n_bets=500, n_paths=1000,
                        rng=SeededRNG(2))
    assert r.fraction > 0
    assert r.median_final > r.start
    assert r.ruin_prob < 0.01
    assert r.mean_log_growth > 0


def test_overbetting_increases_ruin_and_lowers_growth():
    p, price = PRESETS["weather_daily"].p_true, PRESETS["weather_daily"].price
    rows = {s["kelly_multiplier"]: s for s in
            sweep_multipliers(p, price, multipliers=(0.25, 1.0, 2.0, 3.0), n_bets=500, n_paths=1000)}
    assert rows[0.25]["ruin_prob"] <= rows[1.0]["ruin_prob"] <= rows[2.0]["ruin_prob"] <= rows[3.0]["ruin_prob"]
    assert rows[3.0]["ruin_prob"] > 0.5
    # Full Kelly maximises log growth: both under- and over-betting are worse.
    assert rows[1.0]["mean_log_growth"] > rows[2.0]["mean_log_growth"]
    assert rows[1.0]["mean_log_growth"] > rows[0.25]["mean_log_growth"]
    # Twice Kelly has roughly zero growth in theory; here it is at best marginal.
    assert rows[2.0]["mean_log_growth"] < rows[0.25]["mean_log_growth"]


def test_miscalibration_ruins_the_confident_bettor():
    # Believes 0.62, truth 0.52 at price 0.55: full Kelly sized on the belief.
    r = simulate_bankroll(p_true=0.52, price=0.55, p_believed=0.62, kelly_multiplier=1.0,
                          n_bets=500, n_paths=500, rng=SeededRNG(3))
    assert r.fraction > 0
    assert r.median_final < r.start
    assert r.ruin_prob > 0.5


def test_fees_matter_for_thin_edges():
    with_fees = simulate_bankroll(0.57, 0.55, kelly_multiplier=1.0, n_bets=200, n_paths=200)
    no_fees = simulate_bankroll(0.57, 0.55, kelly_multiplier=1.0, n_bets=200, n_paths=200, fee_free=True)
    assert with_fees.fraction < no_fees.fraction
    assert with_fees.meta["fee_per_contract"] > 0 and no_fees.meta["fee_per_contract"] == 0


def test_paths_shape_and_ruin_stops_betting():
    r = simulate_bankroll(0.6, 0.5, kelly_multiplier=4.0, n_bets=50, n_paths=20, keep_paths=True,
                          ruin_threshold=0.5, rng=SeededRNG(4))
    assert r.paths.shape == (20, 51)
    ruined = np.where(r.ruined)[0]
    assert len(ruined) > 0
    for i in ruined:
        path = r.paths[i]
        first = np.argmax(path < 0.5 * r.start)
        assert np.all(path[first:] == path[first])  # frozen after ruin
    assert r.summary()["n_bets"] == 50


def test_input_validation():
    with pytest.raises(ValueError):
        simulate_bankroll(0.6, 1.0)
    with pytest.raises(ValueError):
        simulate_bankroll(1.2, 0.5)
    with pytest.raises(ValueError):
        simulate_bankroll(0.6, 0.5, n_bets=0)
