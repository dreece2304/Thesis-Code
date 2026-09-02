"""Hard rule 2: no live-money code path may exist in this repo."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE_DIRS = ["shared", "investing", "prediction", "forecasting", "nanofab_saas", "materials", "learning", "audit"]

# Alpaca live endpoint (paper is paper-api.alpaca.markets).
LIVE_ALPACA = re.compile(r"https://api\.alpaca\.markets")
# Kalshi order placement.
KALSHI_ORDERS = re.compile(r"/portfolio/orders|/trade-api/v2/orders")
# Any non-GET HTTP verb against Kalshi in the read-only module.
NON_GET = re.compile(r"\.(post|put|delete|patch)\(")


def _py_files():
    for d in CODE_DIRS:
        yield from (ROOT / d).rglob("*.py")


def test_no_live_alpaca_url():
    for f in _py_files():
        assert not LIVE_ALPACA.search(f.read_text()), f"live Alpaca URL in {f}"


def test_no_kalshi_order_endpoints():
    for f in _py_files():
        assert not KALSHI_ORDERS.search(f.read_text()), f"Kalshi order endpoint in {f}"


def test_kalshi_module_is_read_only():
    text = (ROOT / "shared" / "data" / "kalshi.py").read_text()
    assert not NON_GET.search(text)
    assert "Authorization" not in text
    assert "READ ONLY" in text


def test_env_example_has_no_secrets():
    for line in (ROOT / ".env.example").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            if any(s in key for s in ("KEY", "SECRET", "TOKEN")):
                assert val.strip() == "", f"{key} must be blank in .env.example"
    assert "paper-api.alpaca.markets" in (ROOT / ".env.example").read_text()
