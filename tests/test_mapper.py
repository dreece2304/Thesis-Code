from datetime import datetime, timezone

import pandas as pd
import pytest

from prediction.mapper import category_summary, classify, enrich, rank_thin_modelable


def test_classify_rules_and_field():
    assert classify("KXHIGHNY-26SEP05-B75", "Will the high temp in NYC be 75-76?") == "weather"
    assert classify("KXCPI-26SEP", "CPI for August above 0.3%") == "econ"
    assert classify("KXFEDDECISION-26SEP", "Fed rate cut in September?") == "fed"
    assert classify("X", "Will the Seahawks win the game?") == "sports"
    assert classify("X", "Bitcoin above 100k") == "crypto"
    assert classify("X", "something odd") == "other"
    assert classify("X", "anything", category_field="Climate and Weather") == "weather"
    assert classify("X", "anything", category_field="Economics") == "econ"
    assert classify("X", "Bitcoin", category_field="") == "crypto"


def _frame():
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return pd.DataFrame({
        "ticker": ["KXHIGHNY-1", "KXCPI-1", "SPORT-1", "KXHIGHNY-2", "POL-1"],
        "title": ["NYC high temp 75-76", "CPI above 0.3", "Team wins the game", "NYC high 80+", "Senate bill passes"],
        "subtitle": [None] * 5,
        "category": [None] * 5,
        "yes_bid": [0.40, 0.50, 0.49, None, 0.98],
        "yes_ask": [0.50, 0.52, 0.50, None, 0.99],
        "last_price": [0.45, 0.51, 0.50, 0.30, 0.98],
        "volume": [100, 50000, 500000, 10, 3000],
        "open_interest": [200, 10000, 100000, 5, 1000],
        "liquidity": [1000, 100000, 1000000, 0, 5000],
        "close_time": [now + pd.Timedelta(days=d) for d in (2, 10, 1, 3, 60)],
        "rules_primary": ["Resolves YES if Central Park high is 75 or 76 F"] * 5,
    }), now


def test_enrich_and_rank():
    df, now = _frame()
    e = enrich(df, now=now)
    assert e.category_model.tolist() == ["weather", "econ", "sports", "weather", "politics"]
    assert e.mid.tolist()[0] == 0.45 and e.mid.tolist()[3] == 0.30  # falls back to last
    assert e.spread.iloc[0] == pytest.approx(0.10)
    assert e.days_to_close.iloc[0] == 2.0
    assert pd.isna(e.thinness.iloc[3])  # unquoted
    assert e.thinness.iloc[0] > e.thinness.iloc[2]  # wide thin book beats tight deep one
    r = rank_thin_modelable(e, max_days=30)
    assert r.ticker.tolist()[0] == "KXHIGHNY-1"
    assert "KXHIGHNY-2" not in r.ticker.tolist()   # unquoted excluded
    assert "POL-1" not in r.ticker.tolist()        # too far out and extreme price
    assert r.rules_primary.iloc[0].startswith("Resolves YES")
    s = category_summary(e)
    assert s.loc["weather", "n"] == 2
