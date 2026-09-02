import math

import numpy as np
import pytest
from scipy import stats

from prediction.weather import model as M


def test_skewt_recovers_location_scale_and_sign_of_skew():
    rng = np.random.default_rng(0)
    x = 1.5 + 2.0 * stats.skewnorm.rvs(4, size=1500, random_state=rng)   # skewed right
    d = M.SkewT.fit(x)
    mean, sd = d.moments()
    assert mean == pytest.approx(x.mean(), abs=0.15)
    assert sd == pytest.approx(x.std(ddof=1), abs=0.15)
    assert d.alpha > 0
    assert d.cdf(1e9)[0] == pytest.approx(1.0, abs=1e-3)
    assert d.cdf(np.median(x))[0] == pytest.approx(0.5, abs=0.03)
    assert float(np.trapezoid(d.pdf(np.linspace(-30, 30, 4001)), np.linspace(-30, 30, 4001))) == pytest.approx(1.0, abs=1e-3)


def test_fit_error_distribution_and_kde_fallback():
    rng = np.random.default_rng(1)
    e = rng.normal(-1.0, 3.0, 500)
    d = M.fit_error_distribution(e)
    assert d.kind == "skewt" and d.mean == pytest.approx(-1.0, abs=0.4) and d.sd == pytest.approx(3.0, abs=0.4)
    rec = d.to_record()
    back = M.ErrorDist.from_record(rec)
    assert back.kind == "skewt" and back.cdf(0.0)[0] == pytest.approx(d.cdf(0.0)[0], abs=1e-6)
    small = M.fit_error_distribution(e[:20])
    assert small.kind == "kde"
    back = M.ErrorDist.from_record(small.to_record())
    assert back.kind == "kde" and 0 < back.cdf(0.0)[0] < 1
    with pytest.raises(ValueError):
        M.fit_error_distribution([1.0, 2.0])


def _dists():
    rng = np.random.default_rng(2)
    return {"ecmwf_ifs025": M.fit_error_distribution(rng.normal(0.0, 2.0, 300)),
            "gfs_seamless": M.fit_error_distribution(rng.normal(1.0, 3.0, 300))}


def test_probability_partition_and_monotone():
    dists = _dists()
    fc = {"ecmwf_ifs025": 80.0, "gfs_seamless": 81.0}
    p_above, sd, comp = M.probability(fc, dists, {"ecmwf_ifs025": 4.0, "gfs_seamples": None}, 82, "above")
    p_below, _, _ = M.probability(fc, dists, None, 81, "below")
    assert p_above + p_below == pytest.approx(1.0, abs=1e-6)     # >=82 and <=81 partition the integers
    ps = [M.probability(fc, dists, None, t, "above")[0] for t in range(70, 95)]
    assert all(a >= b - 1e-9 for a, b in zip(ps, ps[1:]))
    assert ps[0] > 0.99 and ps[-1] < 0.01
    assert sd > 1.5 and set(comp["models"]) == set(fc)
    assert comp["models"]["ecmwf_ifs025"]["weight"] + comp["models"]["gfs_seamless"]["weight"] == pytest.approx(1.0)


def test_inverse_variance_weights():
    w = M.inverse_variance_weights({"a": 1.0, "b": 4.0})
    assert w["a"] == pytest.approx(0.8) and w["b"] == pytest.approx(0.2)
    w = M.inverse_variance_weights({"a": None, "b": None})
    assert w == {"a": 0.5, "b": 0.5}
    w = M.inverse_variance_weights({"a": 1.0, "b": None, "c": 1.0})
    assert w["b"] == pytest.approx(1 / 3)
    with pytest.raises(ValueError):
        M.probability({"x": 80.0}, {}, None, 80, "above")
