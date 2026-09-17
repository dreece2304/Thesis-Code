import pandas as pd
import pytest

from prediction.weather import plan as P


def test_budget_schedule():
    assert P.budget_for(0, 0.0, None, None) == 20
    assert P.budget_for(60, 5.0, 0.10, 0.12) == 40
    assert P.budget_for(60, -5.0, 0.10, 0.12) == 20       # losing record never raises it
    assert P.budget_for(60, 5.0, 0.15, 0.12) == 20        # worse than market never raises it
    assert P.budget_for(200, 50.0, 0.10, 0.10) == 80


def test_size_respects_budget_and_share():
    cands = [P.Candidate("A", "yes", 0.60, 0.30, agrees=True),      # big edge
             P.Candidate("B", "no", 0.85, 0.70, agrees=True),       # smaller edge
             P.Candidate("C", "yes", 0.35, 0.30, agrees=True),      # edge under threshold
             P.Candidate("D", "yes", 0.90, 0.30, agrees=False)]     # no independent agreement
    df = P.size(cands, budget=20.0)
    assert set(df.ticker) == {"A", "B"}
    assert df.stake.sum() <= 20.0 + 1e-9
    assert (df.stake <= 10.0 + 1e-9).all()
    assert df.iloc[0].ticker == "A" and (df.expected_gain > 0).all()
    assert P.size([cands[2]], 20.0).empty


def test_from_rain_screen():
    s = pd.DataFrame({"ticker": ["KXRAIN-1", "KXRAIN-2"], "city": ["A", "B"], "p": [0.9, 0.05],
                      "yes_bid": [0.70, 0.30], "yes_ask": [0.73, 0.33], "locked": [False, False]})
    c = P.from_rain_screen(s, agree={"KXRAIN-1": True, "KXRAIN-2": True})
    df = P.size(c, 20.0)
    assert df.ticker.tolist() == ["KXRAIN-2", "KXRAIN-1"] or set(df.ticker) == {"KXRAIN-1", "KXRAIN-2"}
    assert df[df.ticker == "KXRAIN-2"].side.iloc[0] == "no" and df[df.ticker == "KXRAIN-1"].side.iloc[0] == "yes"
