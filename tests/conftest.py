import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Every test gets its own data cache and ledger so nothing hits the repo tree."""
    monkeypatch.setenv("DATA_CACHE_DIR", str(tmp_path / "data_cache"))
    monkeypatch.setenv("LEDGER_PATH", str(tmp_path / "ledger.duckdb"))
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    yield


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if any test reaches the network."""
    import requests

    def _blocked(*a, **k):
        raise RuntimeError("network access is disabled in tests; stub shared.data.http")

    monkeypatch.setattr(requests.Session, "request", _blocked)
    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "patch", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
