"""One HTTP session with retries. Tests monkeypatch ``get_json``/``get_text``."""
from __future__ import annotations

import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .ratelimit import LIMITERS

_session: requests.Session | None = None
DEFAULT_TIMEOUT = 30


def user_agent() -> str:
    return os.environ.get("NWS_USER_AGENT", "side-projects (contact: see .env)")


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(total=4, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET",))
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.headers.update({"User-Agent": user_agent(), "Accept": "application/json"})
        _session = s
    return _session


def _get(url: str, params=None, headers=None, timeout=DEFAULT_TIMEOUT, source: str | None = None):
    if source and source in LIMITERS:
        LIMITERS[source].wait()
    r = session().get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r


def get_json(url: str, params=None, headers=None, timeout=DEFAULT_TIMEOUT, source: str | None = None):
    return _get(url, params, headers, timeout, source).json()


def get_text(url: str, params=None, headers=None, timeout=DEFAULT_TIMEOUT, source: str | None = None) -> str:
    return _get(url, params, headers, timeout, source).text
