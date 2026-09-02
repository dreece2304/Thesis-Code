from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_spec_is_in_repo_and_referenced():
    spec = ROOT / "docs" / "KALSHI_WEATHER_SPEC.md"
    assert spec.exists()
    assert "KALSHI_WEATHER_SPEC" in (ROOT / "CLAUDE.md").read_text()


def test_weather_package_has_spec_modules():
    for name in ("stations", "archive", "errors", "model", "market_model", "kalshi", "backtest", "live", "report"):
        assert (ROOT / "prediction" / "weather" / f"{name}.py").exists(), name
