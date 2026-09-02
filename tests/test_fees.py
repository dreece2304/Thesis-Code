import pytest

from prediction.fees import expected_fee_rate, fee_per_contract, kalshi_fee, raw_taker_fee


def test_taker_fee_examples():
    assert raw_taker_fee(0.5) == pytest.approx(0.0175)
    assert kalshi_fee(0.5) == 0.02                      # 1.75c rounds up
    assert kalshi_fee(0.5, contracts=10) == 0.18       # 17.5c rounds up
    assert kalshi_fee(0.5, contracts=100) == 1.75      # exact
    assert kalshi_fee(0.99) == 0.01                    # 0.0693c still rounds up to a cent
    assert kalshi_fee(0.01) == kalshi_fee(0.99)        # symmetric


def test_maker_fee_is_quarter_of_taker():
    assert kalshi_fee(0.5, contracts=100, maker=True) == pytest.approx(0.4375, abs=0.005)
    assert kalshi_fee(0.5, contracts=100, maker=True) == 0.44
    assert kalshi_fee(0.5, maker=True) == 0.01


def test_per_contract_and_rate():
    assert fee_per_contract(0.5, contracts=100) == pytest.approx(0.0175)
    assert fee_per_contract(0.5, contracts=1) == 0.02
    assert expected_fee_rate(0.5) == pytest.approx(0.035)
    assert expected_fee_rate(0.5, maker=True) == pytest.approx(0.00875)


def test_invalid_inputs():
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            kalshi_fee(bad)
    with pytest.raises(ValueError):
        kalshi_fee(0.5, contracts=0)
