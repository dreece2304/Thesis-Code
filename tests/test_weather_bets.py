from datetime import datetime

import pytest

from prediction.weather import bets as B
from shared.data import kalshi as kx
from shared.ledger import Ledger


def test_add_settle_report(monkeypatch):
    with Ledger(":memory:") as L:
        b = B.Bets(L)
        r = b.add("KXRAIN-26SEP11-DC", "yes", 0.72, 5, model_p=0.9, market_p=0.7, note="rain")
        assert r["category"] == "rain" and r["fee"] == pytest.approx(0.02)   # 5 x 0.07x.72x.28 x 0.25 = 1.8c -> 2c
        b.add("KXHIGHNY-26SEP11-T82", "no", 0.75, 4, model_p=0.2)
        b.add("KXRIEMANN-35-28JAN01", "no", 0.82, 10)
        with pytest.raises(ValueError):
            b.add("X", "maybe", 0.5, 1)
        assert b.report()["open"] == 3
        monkeypatch.setattr(kx, "market", lambda t: {"status": "settled", "result": "yes"} if "DC" in t
                            else ({"status": "settled", "result": "no"} if "NY" in t else {"status": "active"}))
        assert b.settle_from_kalshi() == 2
        rep = b.report()
        assert rep["settled"] == 2 and rep["open"] == 1 and rep["hit_rate"] == 1.0
        assert rep["pnl"] == pytest.approx(5 * 0.28 - 0.02 + 4 * 0.25 - 0.02, abs=0.011)
        assert rep["brier_model"] == pytest.approx(((0.9 - 1) ** 2 + (0.2 - 0) ** 2) / 2)
        assert set(rep["by_category"]) == {"rain", "temperature"}
