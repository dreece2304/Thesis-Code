"""Parquet cache with a time-to-live, keyed by function arguments."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable

import pandas as pd


def cache_dir() -> Path:
    return Path(os.environ.get("DATA_CACHE_DIR", "data_cache"))


def _key(args, kwargs) -> str:
    blob = json.dumps([list(args), dict(sorted(kwargs.items()))], default=str, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def cache_path(namespace: str, key: str) -> Path:
    return cache_dir() / namespace / f"{key}.parquet"


def load_cached(namespace: str, key: str, ttl_seconds: float | None) -> pd.DataFrame | None:
    p = cache_path(namespace, key)
    if not p.exists():
        return None
    if ttl_seconds is not None and time.time() - p.stat().st_mtime > ttl_seconds:
        return None
    return pd.read_parquet(p)


def save_cached(namespace: str, key: str, df: pd.DataFrame) -> Path:
    p = cache_path(namespace, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=True)
    return p


def cached_frame(namespace: str, ttl_seconds: float | None = 6 * 3600) -> Callable:
    """Decorate a function returning a DataFrame to cache its result on disk.

    Adds a ``refresh`` keyword to the wrapped function. ``ttl_seconds=None``
    caches forever (for immutable history).
    """
    def deco(fn: Callable[..., pd.DataFrame]) -> Callable[..., pd.DataFrame]:
        @functools.wraps(fn)
        def wrapper(*args, refresh: bool = False, **kwargs):
            key = _key(args, kwargs)
            if not refresh:
                hit = load_cached(namespace, key, ttl_seconds)
                if hit is not None:
                    return hit
            df = fn(*args, **kwargs)
            if isinstance(df, pd.DataFrame) and not df.empty:
                save_cached(namespace, key, df)
            return df
        wrapper.cache_namespace = namespace
        return wrapper
    return deco


def clear(namespace: str | None = None) -> int:
    """Delete cached files (one namespace or all). Returns files removed."""
    root = cache_dir() / namespace if namespace else cache_dir()
    n = 0
    if root.exists():
        for p in root.rglob("*.parquet"):
            p.unlink()
            n += 1
    return n
