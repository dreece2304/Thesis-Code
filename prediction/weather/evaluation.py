"""Brier comparison, paired bootstrap, calibration, and the go-live gate."""
from __future__ import annotations

import numpy as np
import pandas as pd

from shared.ledger import brier_score

GATE_MIN_N = 200
GATE_CI = 0.90


def paired_bootstrap(p_ours, p_market, outcomes, n_boot: int = 2000, ci: float = GATE_CI,
                     seed: int = 0) -> dict:
    """Bootstrap interval for (Brier market - Brier ours); positive means we are better."""
    a, b, y = (np.asarray(v, dtype=float) for v in (p_ours, p_market, outcomes))
    n = len(y)
    if n == 0:
        return {"n": 0, "brier_ours": np.nan, "brier_market": np.nan, "diff": np.nan,
                "ci_lo": np.nan, "ci_hi": np.nan, "excludes_zero": False}
    d = (b - y) ** 2 - (a - y) ** 2
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boots = d[idx].mean(axis=1)
    lo, hi = np.percentile(boots, [(1 - ci) / 2 * 100, (1 + ci) / 2 * 100])
    return {"n": n, "brier_ours": brier_score(a, y), "brier_market": brier_score(b, y),
            "diff": float(d.mean()), "ci_lo": float(lo), "ci_hi": float(hi),
            "excludes_zero": bool(lo > 0)}


def calibration(p, outcomes, bins: int = 10) -> pd.DataFrame:
    p, y = np.asarray(p, dtype=float), np.asarray(outcomes, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    df = pd.DataFrame({"bin": idx, "p": p, "y": y})
    out = df.groupby("bin").agg(mean_prob=("p", "mean"), frac_positive=("y", "mean"), n=("y", "size")).reset_index()
    out["bin_lo"] = edges[out["bin"]]
    out["bin_hi"] = edges[out["bin"] + 1]
    return out[["bin_lo", "bin_hi", "mean_prob", "frac_positive", "n"]]


def go_live_gate(p_ours, p_market, outcomes, pnl_after_fees: float, min_n: int = GATE_MIN_N,
                 seed: int = 0) -> dict:
    """Spec gate: >= min_n resolved, Brier better with 90% CI excluding zero, P&L > 0.

    Report only. No code path reads this to trade live.
    """
    b = paired_bootstrap(p_ours, p_market, outcomes, seed=seed)
    passes = b["n"] >= min_n and b["excludes_zero"] and pnl_after_fees > 0
    reasons = []
    if b["n"] < min_n:
        reasons.append(f"need {min_n} resolved, have {b['n']}")
    if not b["excludes_zero"]:
        reasons.append("Brier gap CI includes zero")
    if pnl_after_fees <= 0:
        reasons.append("paper P&L not positive")
    return {**b, "pnl_after_fees": float(pnl_after_fees), "passes": bool(passes),
            "reason": "; ".join(reasons) or "ok"}
