import numpy as np
import pandas as pd
import pytest

from prediction.weather import sizing as S


def test_size_bet_kelly_and_caps():
    s = S.size_bet(p=0.58, price=0.50, bankroll=2000)
    assert s.kelly_full > 0 and s.contracts > 0 and s.capped_by is None
    assert s.stake <= 0.05 * 2000 + 1
    assert S.size_bet(p=0.50, price=0.50, bankroll=2000).contracts == 0
    big = S.size_bet(p=0.95, price=0.50, bankroll=2000)
    assert big.capped_by == "per_bet" and big.stake <= 0.05 * 2000 + 0.6
    # existing exposure eats the room
    none = S.size_bet(p=0.95, price=0.50, bankroll=2000, existing_bet_stake=100)
    assert none.contracts == 0
    tot = S.size_bet(p=0.95, price=0.50, bankroll=2000, existing_total_stake=290)
    assert tot.capped_by == "total" and tot.stake <= 10.6


def test_correlation_groups_and_bet_key():
    idx = pd.date_range("2026-08-01", periods=40, freq="D")
    rng = np.random.default_rng(0)
    base = rng.normal(0, 2, 40)
    df = pd.DataFrame({"NYC": base + rng.normal(0, 0.5, 40),
                       "PHL": base + rng.normal(0, 0.5, 40),
                       "MIA": rng.normal(0, 2, 40)}, index=idx)
    groups = S.correlation_groups(df, asof="2026-09-10")
    assert {"NYC", "PHL"} in groups and {"MIA"} in groups
    assert S.bet_key("NYC", "2026-09-02", groups) == "NYC+PHL:2026-09-02"
    assert S.bet_key("MIA", "2026-09-02", groups) == "MIA:2026-09-02"
    # too little history -> everyone separate
    assert len(S.correlation_groups(df, asof="2026-08-05")) == 3
    # window excludes the correlated period
    later = pd.DataFrame({"NYC": rng.normal(0, 2, 40), "PHL": rng.normal(0, 2, 40)}, index=idx + pd.Timedelta(days=40))
    both = pd.concat([df[["NYC", "PHL"]], later])
    assert len(S.correlation_groups(both, asof="2026-10-20")) == 2
