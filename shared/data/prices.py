"""Price history via yfinance (lazy import) and proxy splicing for pre-inception."""
from __future__ import annotations

import pandas as pd

from .cache import cached_frame


@cached_frame("prices_daily", ttl_seconds=12 * 3600)
def daily_prices(tickers, start: str = "1990-01-01", end: str | None = None) -> pd.DataFrame:
    """Adjusted close, one column per ticker."""
    import yfinance as yf  # optional dependency

    tickers = [tickers] if isinstance(tickers, str) else list(tickers)
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False,
                      group_by="column", threads=False)
    close = raw["Close"] if "Close" in raw else raw
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close.index = pd.to_datetime(close.index)
    return close.sort_index()


def to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Month-end prices from daily prices."""
    return daily.resample("ME").last()


def monthly_prices(tickers, start: str = "1990-01-01", end: str | None = None, **kw) -> pd.DataFrame:
    return to_monthly(daily_prices(tickers, start=start, end=end, **kw))


def splice_with_proxy(primary: pd.Series, proxy: pd.Series) -> pd.Series:
    """Extend ``primary`` backwards using ``proxy`` returns before inception.

    The proxy is rescaled so its level matches the primary on the first date
    both exist. Returns a series covering the union of dates.
    """
    primary = primary.dropna()
    proxy = proxy.dropna()
    if primary.empty:
        return proxy
    first = primary.index[0]
    before = proxy.loc[proxy.index < first]
    if before.empty:
        return primary
    overlap = proxy.loc[proxy.index >= first]
    if overlap.empty:
        raise ValueError("proxy must overlap primary on at least one date")
    scale = primary.iloc[0] / overlap.iloc[0]
    return pd.concat([before * scale, primary]).sort_index()
