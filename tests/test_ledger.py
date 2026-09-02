from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from shared.ledger import Ledger, brier_score
from shared.ledger import ledger as ledger_mod


def test_log_and_resolve_roundtrip(tmp_path):
    with Ledger(tmp_path / "l.duckdb") as L:
        pid = L.log_prediction("prediction", "KXHIGHNY-1", 0.7, market_prob=0.6, stake=5.0,
                               timestamp=datetime(2026, 1, 1), notes="test")
        df = L.predictions()
        assert len(df) == 1
        row = df.iloc[0]
        assert row.id == pid and row.project == "prediction"
        assert row.model_prob == 0.7 and row.market_prob == 0.6 and row.stake == 5.0
        assert pd.isna(row.outcome)
        L.resolve(pid, True)
        row = L.predictions(resolved=True).iloc[0]
        assert row.outcome == 1 and row.resolved_at is not None
        assert L.predictions(resolved=False).empty


def test_persistence_across_connections(tmp_path):
    p = tmp_path / "persist.duckdb"
    with Ledger(p) as L:
        L.log_prediction("investing", "SPY", 0.5)
    with Ledger(p) as L:
        assert len(L.predictions()) == 1


def test_validation():
    with Ledger(":memory:") as L:
        with pytest.raises(ValueError):
            L.log_prediction("x", "y", 1.2)
        with pytest.raises(ValueError):
            L.log_prediction("x", "y", 0.5, market_prob=-0.1)
        with pytest.raises(ValueError):
            L.log_prediction("x", "y", float("nan"))
        with pytest.raises(ValueError):
            L.log_prediction("", "y", 0.5)
        with pytest.raises(ValueError):
            L.log_prediction("x", "y", 0.5, stake=-1)
        with pytest.raises(KeyError):
            L.resolve("nope", 1)


def test_resolve_market_bulk():
    with Ledger(":memory:") as L:
        L.log_prediction("prediction", "M1", 0.4)
        L.log_prediction("prediction", "M1", 0.6)
        L.log_prediction("prediction", "M2", 0.6)
        assert L.resolve_market("M1", 0) == 2
        df = L.predictions(resolved=True)
        assert set(df.market_or_asset) == {"M1"} and (df.outcome == 0).all()


def test_brier_score_basic():
    assert brier_score([1.0, 0.0], [1, 0]) == 0.0
    assert brier_score([0.0, 1.0], [1, 0]) == 1.0
    assert brier_score([0.5, 0.5], [1, 0]) == pytest.approx(0.25)
    assert np.isnan(brier_score([], []))
    with pytest.raises(ValueError):
        brier_score([0.5], [1, 0])


def test_brier_by_project_and_skill():
    with Ledger(":memory:") as L:
        # model perfect, market coin-flip
        for i in range(10):
            y = i % 2
            L.log_prediction("prediction", f"m{i}", model_prob=float(y), market_prob=0.5, outcome=y)
        # no market prob for investing
        L.log_prediction("investing", "SPY", 0.8, outcome=1)
        L.log_prediction("investing", "SPY", 0.8)  # unresolved, ignored
        df = L.brier_by_project().set_index("project")
        assert df.loc["prediction", "n"] == 10
        assert df.loc["prediction", "brier_model"] == 0.0
        assert df.loc["prediction", "brier_market"] == pytest.approx(0.25)
        assert df.loc["prediction", "skill"] == pytest.approx(1.0)
        assert df.loc["investing", "n"] == 1
        assert df.loc["investing", "brier_model"] == pytest.approx(0.04)
        assert np.isnan(df.loc["investing", "brier_market"])


def test_calibration_curve_bins():
    with Ledger(":memory:") as L:
        # 0.1 bucket: 20 predictions, 2 positive -> calibrated
        for i in range(20):
            L.log_prediction("prediction", f"a{i}", 0.12, outcome=int(i < 2))
        # 0.9 bucket: 10 predictions, 9 positive
        for i in range(10):
            L.log_prediction("prediction", f"b{i}", 0.91, outcome=int(i < 9))
        # exactly 1.0 must land in the top bin
        L.log_prediction("prediction", "c", 1.0, outcome=1)
        c = L.calibration_curve(bins=10)
        assert list(c.n) == [20, 11]
        assert c.iloc[0].frac_positive == pytest.approx(0.1)
        assert c.iloc[0].bin_lo == pytest.approx(0.1) and c.iloc[0].bin_hi == pytest.approx(0.2)
        assert c.iloc[1].bin_lo == pytest.approx(0.9) and c.iloc[1].bin_hi == pytest.approx(1.0)
        assert L.calibration_curve(project="investing").empty


def test_reliability_plot_writes_png(tmp_path):
    with Ledger(":memory:") as L:
        for i in range(30):
            L.log_prediction("prediction", f"m{i}", (i % 10) / 10 + 0.05, market_prob=0.5,
                             outcome=int(i % 3 == 0))
        out = tmp_path / "plots" / "rel.png"
        fig = L.reliability_plot(project="prediction", path=out)
        assert out.exists() and out.stat().st_size > 1000
        import matplotlib.pyplot as plt
        plt.close(fig)


def test_default_ledger_uses_env(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_mod, "_default", None)
    pid = ledger_mod.log_prediction("forecasting", "regime", 0.33)
    assert ledger_mod.default_ledger().path.endswith("ledger.duckdb")
    ledger_mod.resolve(pid, 0)
    assert ledger_mod.brier_by_project().iloc[0].n == 1
    ledger_mod.default_ledger().close()
    monkeypatch.setattr(ledger_mod, "_default", None)
