from datetime import date, datetime

import pandas as pd
import pytest

from prediction.weather import kalshi as W
from prediction.weather.stations import STATIONS
from shared.data import kalshi as kx
from shared.ledger import Ledger


def test_parse_event_date_and_strikes():
    assert W.parse_event_date("KXHIGHNY-26SEP02-T82") == date(2026, 9, 2)
    assert W.parse_event_date("KXHIGHCHI-26SEP02") == date(2026, 9, 2)
    assert W.parse_strike({"strike_type": "greater", "floor_strike": 82, "cap_strike": None}) == ("above", 83, None)
    assert W.parse_strike({"strike_type": "less", "floor_strike": None, "cap_strike": 75}) == ("below", 74, None)
    assert W.parse_strike({"strike_type": "between", "floor_strike": 80.5, "cap_strike": 82.5,
                           "title": "Will the maximum temperature be 81-82° on Sep 2, 2026?"}) == ("between", 81, 82)
    assert W.parse_strike({"title": "Will the maximum temperature be >82° on Sep 2, 2026?"}) == ("above", 83, None)
    assert W.parse_strike({"title": "Will the maximum temperature be <75° on Sep 2, 2026?"}) == ("below", 74, None)
    with pytest.raises(ValueError):
        W.parse_strike({"title": "nothing"})
    assert W.rules_station("If the maximum temperature recorded at Chicago (CLIMDW) for Sep 2 ...") == "CLIMDW"
    assert W.rules_station(None) is None


def test_discover_and_settled_values(monkeypatch):
    def fake_markets(status="open", series_ticker=None, **kw):
        if status == "settled":
            return pd.DataFrame({"ticker": [f"{series_ticker}-26AUG31-T85", f"{series_ticker}-26AUG31-T78"],
                                 "expiration_value": ["78.00", "78.00"], "result": ["no", "no"]})
        return pd.DataFrame({
            "ticker": [f"{series_ticker}-26SEP02-T82", f"{series_ticker}-26SEP02-B81.5"],
            "title": ["Will the maximum temperature be >82° on Sep 2, 2026?", "Will the maximum temperature be 81-82° on Sep 2, 2026?"],
            "strike_type": ["greater", "between"], "floor_strike": [82, 80.5], "cap_strike": [None, 82.5],
            "rules_primary": ["... recorded at New York City (CLINYC) ...", "... recorded at New York City (CLINYC) ..."],
            "yes_bid": [0.1, 0.4], "yes_ask": [0.12, 0.45], "last_price": [0.1, 0.4]})
    monkeypatch.setattr(kx, "markets", fake_markets)
    df = W.discover([STATIONS["NYC"], STATIONS["CHI"]])
    assert len(df) == 4 and set(df.station) == {"NYC", "CHI"}
    ny = df[df.station == "NYC"]
    assert ny.side.tolist() == ["above", "between"] and ny.threshold.tolist() == [83, 81]
    assert ny.station_ok.all()
    assert not df[df.station == "CHI"].station_ok.any()   # rules say CLINYC, station expects CLIMDW
    sv = W.settled_values(STATIONS["NYC"])
    assert len(sv) == 1 and sv.kalshi_value.iloc[0] == 78.0 and sv.target_date.iloc[0] == date(2026, 8, 31)


def test_maker_fill_rule():
    q = {"yes_bid": 0.40, "yes_ask": 0.45}
    f = W.maker_fill("yes", 0.45, q, 10)
    assert f.filled and f.price == 0.45 and f.fee == pytest.approx(0.05)  # 10 x 0.07x.45x.55x.25 = 4.3c -> 5c
    assert not W.maker_fill("yes", 0.44, q, 10).filled
    assert W.maker_fill("no", 0.60, q, 10).filled            # best NO ask = 1 - 0.40 = 0.60
    assert not W.maker_fill("no", 0.59, q, 10).filled
    assert not W.maker_fill("yes", 0.5, {"yes_bid": None, "yes_ask": None}, 1).filled
    with pytest.raises(ValueError):
        W.maker_fill("maybe", 0.5, q, 1)


def test_paper_book_lifecycle():
    with Ledger(":memory:") as L:
        book = W.PaperBook(L)
        q = {"yes_bid": 0.40, "yes_ask": 0.45}
        o1 = book.place("KXHIGHNY-26SEP02-T82", "yes", 0.45, 10, q, fair=0.55, station="NYC",
                        target_date=date(2026, 9, 2), bet_key="NYC:2026-09-02", now=datetime(2026, 8, 30))
        o2 = book.place("KXHIGHNY-26SEP02-T82", "yes", 0.40, 10, q, bet_key="NYC:2026-09-02")
        assert o1["status"] == "filled" and o2["status"] == "resting"
        exp = book.open_exposure()
        assert exp.cost.iloc[0] == pytest.approx(10 * 0.45 + 0.05)
        assert book.cancel_resting() == 1
        assert book.orders("cancelled").id.iloc[0] == o2["id"]
        assert book.settle("KXHIGHNY-26SEP02-T82", yes_won=True) == 1
        s = book.pnl_summary()
        assert s["settled"] == 1 and s["pnl"] == pytest.approx(10 * 0.55 - 0.05) and s["wins"] == 1
        assert book.open_exposure().empty
        with pytest.raises(ValueError):
            book.place("X", "yes", 1.2, 1, q)


def test_resolve_settled(monkeypatch):
    settled = pd.DataFrame({"ticker": ["KXHIGHNY-26SEP01-T80", "KXHIGHNY-26SEP01-T70"], "result": ["yes", "no"],
                            "expiration_value": ["81.00", "81.00"]})
    monkeypatch.setattr(kx, "markets", lambda status="open", series_ticker=None, **kw:
                        settled.copy() if status == "settled" and series_ticker == "KXHIGHNY" else pd.DataFrame())
    with Ledger(":memory:") as L:
        book = W.PaperBook(L)
        L.log_prediction("weather", "KXHIGHNY-26SEP01-T80", 0.7, market_prob=0.6)
        L.log_prediction("weather", "KXHIGHCHI-26SEP01-T70", 0.1)
        book.place("KXHIGHNY-26SEP01-T70", "no", 0.95, 5, {"yes_bid": 0.05, "yes_ask": 0.08})
        n = W.resolve_settled(L, book, [STATIONS["NYC"], STATIONS["CHI"]])
        assert n == 1
        assert L.predictions(resolved=True).outcome.iloc[0] == 1
        assert book.orders().settled.iloc[0] == 0 and book.orders().pnl.iloc[0] > 0
