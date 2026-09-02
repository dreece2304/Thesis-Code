"""Predictive distribution for the settled daily high.

Each forecast model m gives a point forecast f_m; its error e = settlement - f_m
has a fitted distribution (skew-t, or a KDE fallback) for the station, lead
and month. The predictive CDF is a mixture over models weighted by inverse
recent error variance:

    P(settlement <= s) = sum_m w_m F_m(s - f_m)

A contract "T or above" pays when settlement >= T, so p = 1 - F(T - 0.5);
"T or below" pays when settlement <= T, so p = F(T + 0.5).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np
from scipy import optimize, stats

MIN_NU = 2.5
MAX_NU = 200.0


# -- Azzalini skew-t -----------------------------------------------------------
class SkewT:
    """Skew-t of Azzalini and Capitanio (2003): location xi, scale omega, shape alpha, df nu."""

    def __init__(self, xi: float, omega: float, alpha: float, nu: float):
        if omega <= 0 or nu <= 0:
            raise ValueError("omega and nu must be positive")
        self.xi, self.omega, self.alpha, self.nu = float(xi), float(omega), float(alpha), float(nu)

    def pdf(self, x):
        z = (np.asarray(x, dtype=float) - self.xi) / self.omega
        t1 = stats.t.pdf(z, self.nu)
        arg = self.alpha * z * np.sqrt((self.nu + 1) / (self.nu + z ** 2))
        return 2.0 / self.omega * t1 * stats.t.cdf(arg, self.nu + 1)

    _GRID_HALF_WIDTH = 60.0   # in units of omega; heavy tails need room
    _GRID_N = 6001

    def _grid(self):
        g = getattr(self, "_cdf_grid", None)
        if g is None:
            xs = np.linspace(self.xi - self._GRID_HALF_WIDTH * self.omega,
                             self.xi + self._GRID_HALF_WIDTH * self.omega, self._GRID_N)
            # denser near the centre: concatenate a fine core grid
            core = np.linspace(self.xi - 8 * self.omega, self.xi + 8 * self.omega, self._GRID_N)
            xs = np.unique(np.concatenate([xs, core]))
            pdf = self.pdf(xs)
            cdf = np.concatenate([[0.0], np.cumsum(0.5 * (pdf[1:] + pdf[:-1]) * np.diff(xs))])
            total = cdf[-1] if cdf[-1] > 0 else 1.0
            g = (xs, np.clip(cdf / total, 0.0, 1.0))
            self._cdf_grid = g
        return g

    def cdf(self, x) -> np.ndarray:
        xs, cdf = self._grid()
        v = np.atleast_1d(np.asarray(x, dtype=float))
        return np.interp(v, xs, cdf, left=0.0, right=1.0)

    def moments(self) -> tuple[float, float]:
        """Mean and sd (finite for nu > 2)."""
        nu, a = self.nu, self.alpha
        delta = a / math.sqrt(1 + a * a)
        b = math.sqrt(nu / math.pi) * math.gamma((nu - 1) / 2) / math.gamma(nu / 2) if nu > 1 else float("nan")
        mean = self.xi + self.omega * b * delta
        var = self.omega ** 2 * (nu / (nu - 2) - (b * delta) ** 2) if nu > 2 else float("nan")
        return mean, math.sqrt(var) if var == var and var > 0 else float("nan")

    def loglik(self, x) -> float:
        p = self.pdf(x)
        return float(np.sum(np.log(np.maximum(p, 1e-300))))

    @classmethod
    def fit(cls, x, max_iter: int = 600) -> "SkewT":
        x = np.asarray(x, dtype=float)
        x = x[np.isfinite(x)]
        if len(x) < 10:
            raise ValueError("need at least 10 points")
        m, s = float(np.mean(x)), float(np.std(x, ddof=1))
        g = float(stats.skew(x))

        def unpack(theta):
            xi, log_om, alpha, log_nu = theta
            omega = math.exp(min(max(log_om, -6.0), 8.0))
            nu = min(MIN_NU + math.exp(min(max(log_nu, -6.0), 6.0)), MAX_NU)
            return xi, omega, float(np.clip(alpha, -50, 50)), nu

        def nll(theta):
            xi, omega, alpha, nu = unpack(theta)
            return -cls(xi, omega, alpha, nu).loglik(x)

        best = None
        for a0 in (0.0, 2.0 * np.sign(g) if g else 1.0):
            x0 = np.array([m, math.log(max(s, 1e-3)), a0, math.log(8.0)])
            r = optimize.minimize(nll, x0, method="Nelder-Mead",
                                  options={"maxiter": max_iter, "xatol": 1e-3, "fatol": 1e-4})
            if best is None or r.fun < best.fun:
                best = r
        return cls(*unpack(best.x))

    def to_params(self) -> dict:
        return {"xi": self.xi, "omega": self.omega, "alpha": self.alpha, "nu": self.nu}


class KDE:
    """Gaussian KDE fallback with the same interface."""

    def __init__(self, sample):
        self.sample = np.asarray(sample, dtype=float)
        self.k = stats.gaussian_kde(self.sample)

    def pdf(self, x):
        return self.k(np.atleast_1d(np.asarray(x, dtype=float)))

    def cdf(self, x) -> np.ndarray:
        xs = np.atleast_1d(np.asarray(x, dtype=float))
        return np.clip(np.array([self.k.integrate_box_1d(-np.inf, v) for v in xs]), 0, 1)

    def moments(self) -> tuple[float, float]:
        return float(self.sample.mean()), float(np.sqrt(self.sample.var(ddof=1) + self.k.factor ** 2 * self.sample.var()))

    def to_params(self) -> dict:
        return {"sample": [round(float(v), 3) for v in self.sample]}


@dataclass
class ErrorDist:
    """A fitted error distribution plus provenance."""
    kind: str                 # "skewt" | "kde"
    dist: SkewT | KDE
    n: int
    mean: float
    sd: float
    meta: dict = field(default_factory=dict)

    def cdf(self, x):
        return self.dist.cdf(x)

    def to_record(self) -> dict:
        return {"kind": self.kind, "n": self.n, "mean": self.mean, "sd": self.sd,
                "params": json.dumps(self.dist.to_params()), **self.meta}

    @classmethod
    def from_record(cls, rec: dict) -> "ErrorDist":
        params = json.loads(rec["params"]) if isinstance(rec["params"], str) else rec["params"]
        dist = SkewT(**params) if rec["kind"] == "skewt" else KDE(params["sample"])
        meta = {k: v for k, v in rec.items() if k not in ("kind", "n", "mean", "sd", "params")}
        return cls(rec["kind"], dist, int(rec["n"]), float(rec["mean"]), float(rec["sd"]), meta)


def fit_error_distribution(errors, min_n_skewt: int = 40) -> ErrorDist:
    """Skew-t by MLE; KDE if too few points or the fit is unstable."""
    e = np.asarray(errors, dtype=float)
    e = e[np.isfinite(e)]
    if len(e) < 5:
        raise ValueError("need at least 5 errors")
    mean, sd = float(e.mean()), float(e.std(ddof=1))
    if len(e) >= min_n_skewt:
        try:
            d = SkewT.fit(e)
            m, s = d.moments()
            stable = (np.isfinite(m) and np.isfinite(s) and abs(m - mean) < 2 * sd
                      and 0.3 * sd < s < 3 * sd and abs(d.alpha) < 20 and d.nu > MIN_NU + 1e-6)
            if stable:
                return ErrorDist("skewt", d, len(e), mean, sd, {"fit_mean": m, "fit_sd": s})
        except (ValueError, RuntimeError, FloatingPointError):
            pass
    return ErrorDist("kde", KDE(e), len(e), mean, sd)


# -- mixture and probabilities -------------------------------------------------
@dataclass
class Predictive:
    forecasts: dict[str, float]
    dists: dict[str, ErrorDist]
    weights: dict[str, float]

    def cdf(self, s: float) -> float:
        tot = 0.0
        for m, w in self.weights.items():
            tot += w * float(self.dists[m].cdf(s - self.forecasts[m])[0])
        return float(np.clip(tot, 0.0, 1.0))

    def moments(self) -> tuple[float, float]:
        means, vars_ = [], []
        for m, w in self.weights.items():
            mu, sd = self.dists[m].dist.moments()
            if not np.isfinite(mu) or not np.isfinite(sd):
                mu, sd = self.dists[m].mean, self.dists[m].sd
            means.append((w, self.forecasts[m] + mu))
            vars_.append((w, sd ** 2))
        mean = sum(w * mu for w, mu in means)
        var = sum(w * v for w, v in vars_) + sum(w * (mu - mean) ** 2 for w, mu in means)
        return float(mean), float(math.sqrt(var))

    def prob(self, threshold: int, side: str) -> float:
        if side == "above":
            return 1.0 - self.cdf(threshold - 0.5)
        if side == "below":
            return self.cdf(threshold + 0.5)
        raise ValueError(side)


def inverse_variance_weights(recent_var: dict[str, float], floor: float = 0.25) -> dict[str, float]:
    """w_m proportional to 1 / max(var_m, floor); models with no variance get the mean weight."""
    known = {m: 1.0 / max(v, floor) for m, v in recent_var.items() if v is not None and np.isfinite(v)}
    if not known:
        n = len(recent_var)
        return {m: 1.0 / n for m in recent_var}
    fill = float(np.mean(list(known.values())))
    raw = {m: known.get(m, fill) for m in recent_var}
    tot = sum(raw.values())
    return {m: v / tot for m, v in raw.items()}


def probability(forecasts: dict[str, float], dists: dict[str, ErrorDist],
                recent_var: dict[str, float] | None, threshold: int, side: str) -> tuple[float, float, dict]:
    """(p, predictive sd, components) for one contract.

    ``forecasts``: model -> point forecast of the daily high (deg F).
    ``dists``: model -> fitted error distribution for this station, lead, month.
    ``recent_var``: model -> trailing 60-day error variance (None -> equal weights).
    """
    models = [m for m in forecasts if m in dists]
    if not models:
        raise ValueError("no model has both a forecast and an error fit")
    rv = {m: (recent_var or {}).get(m) for m in models}
    w = inverse_variance_weights(rv)
    pred = Predictive({m: forecasts[m] for m in models}, {m: dists[m] for m in models}, w)
    p = pred.prob(threshold, side)
    mean, sd = pred.moments()
    comps = {m: {"forecast": forecasts[m], "weight": w[m], "bias": dists[m].mean, "sd": dists[m].sd,
                 "kind": dists[m].kind, "n": dists[m].n,
                 "p": Predictive({m: forecasts[m]}, {m: dists[m]}, {m: 1.0}).prob(threshold, side)}
             for m in models}
    return p, sd, {"mean": mean, "models": comps}
