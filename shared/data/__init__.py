"""Thin, cached, rate-limited data pullers.

All network access goes through ``shared.data.http`` so tests can stub it.
Results are cached as Parquet under ``$DATA_CACHE_DIR`` (default
``data_cache/``, gitignored). Pass ``refresh=True`` to bypass the cache.
"""
