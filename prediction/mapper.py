"""Kalshi market mapper: classify open markets and rank thin, modelable ones.

Keeps the exact resolution rule text (``rules_primary``/``rules_secondary``)
alongside every row so a model can be checked against how the market settles.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from shared.data import kalshi

# Order matters: first match wins. Patterns run on "TICKER TITLE SUBTITLE".
CATEGORY_RULES: list[tuple[str, re.Pattern]] = [
    ("weather", re.compile(r"^KX(HIGH|LOW|TEMP|RAIN|SNOW|PRECIP)|\bhigh temp|\blow temp|\brain\b|\bsnow|precipitation|degrees|°", re.I)),
    ("fed", re.compile(r"^KXFED|\bFOMC\b|\bfed\b.*\brate|rate (cut|hike)|federal funds", re.I)),
    ("econ", re.compile(r"^KX(CPI|PAYROLL|JOBS|GDP|UNEMP|INFL|CLAIMS)|\bCPI\b|payroll|nonfarm|\bGDP\b|unemployment|inflation|jobless", re.I)),
    ("crypto", re.compile(r"bitcoin|\bBTC\b|ethereum|\bETH\b|solana|crypto", re.I)),
    ("politics", re.compile(r"elect|president|senate|congress|governor|approval|nominee|impeach|cabinet|\bbill\b|executive order", re.I)),
    ("sports", re.compile(r"\bNFL\b|\bNBA\b|\bMLB\b|\bNHL\b|\bNCAA\b|\bMLS\b|\bUFC\b|\bPGA\b|\bF1\b|grand prix|super bowl|world series|championship|\bwins?\b.*\b(game|match|series|cup)\b", re.I)),
    ("entertainment", re.compile(r"box office|oscar|grammy|emmy|billboard|album|movie|rotten tomatoes|spotify|netflix", re.I)),
    ("science_tech", re.compile(r"launch|spacex|nasa|\bAI\b|openai|apple|iphone|tesla", re.I)),
]

# How much we believe a non-LLM model can add, by category (0 = do not bother).
MODELABILITY = {
    "weather": 3.0, "econ": 2.5, "fed": 2.0, "crypto": 1.0, "science_tech": 0.5,
    "politics": 0.5, "sports": 0.5, "entertainment": 0.25, "other": 0.25,
}


def classify(ticker: str | None, title: str | None = None, subtitle: str | None = None,
             category_field: str | None = None) -> str:
    """Category from Kalshi's own field when usable, else ticker/title rules."""
    if isinstance(category_field, str) and category_field.strip():
        cf = category_field.strip().lower()
        for name in MODELABILITY:
            if name in cf or cf in name:
                return name
        if "climate" in cf or "weather" in cf:
            return "weather"
        if "economic" in cf or "financial" in cf:
            return "econ"
    text = " ".join(str(x) for x in (ticker, title, subtitle) if isinstance(x, str))
    for name, pat in CATEGORY_RULES:
        if pat.search(text):
            return name
    return "other"


def enrich(markets: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Add category_model, mid, spread, days_to_close, liquidity_score, thinness."""
    df = markets.copy()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    df["category_model"] = [
        classify(t, ti, su, cf) for t, ti, su, cf in zip(
            df.get("ticker"), df.get("title"), df.get("subtitle"), df.get("category"))
    ]
    bid = pd.to_numeric(df.get("yes_bid"), errors="coerce")
    ask = pd.to_numeric(df.get("yes_ask"), errors="coerce")
    last = pd.to_numeric(df.get("last_price"), errors="coerce")
    mid = (bid + ask) / 2
    df["mid"] = mid.where(mid.notna(), last)
    df["spread"] = (ask - bid)
    close = pd.to_datetime(df.get("close_time"), utc=True, errors="coerce")
    df["days_to_close"] = (close - pd.Timestamp(now)).dt.total_seconds() / 86400.0
    vol = pd.to_numeric(df.get("volume"), errors="coerce").fillna(0)
    oi = pd.to_numeric(df.get("open_interest"), errors="coerce").fillna(0)
    liq = pd.to_numeric(df.get("liquidity"), errors="coerce").fillna(0)
    # log scale so a handful of huge markets do not dominate
    df["liquidity_score"] = np.log1p(vol) + np.log1p(oi) + 0.5 * np.log1p(liq)
    # thin = wide spread and little activity, but still quoted on both sides
    quoted = bid.notna() & ask.notna() & (bid > 0) & (ask < 1)
    df["thinness"] = np.where(quoted, df["spread"].fillna(1.0) * 10 + 1 / (1 + df["liquidity_score"]), np.nan)
    df["has_rules"] = df.get("rules_primary").fillna("").astype(str).str.len() > 0
    return df


def rank_thin_modelable(enriched: pd.DataFrame, max_days: float = 30, min_days: float = 0.0,
                        min_mid: float = 0.03, max_mid: float = 0.97) -> pd.DataFrame:
    """Score = modelability x thinness, for markets closing within ``max_days``.

    Excludes unquoted markets and prices at the extremes where fees eat any edge.
    """
    df = enriched.copy()
    ok = (
        df["thinness"].notna()
        & df["days_to_close"].between(min_days, max_days)
        & df["mid"].between(min_mid, max_mid)
    )
    df = df[ok].copy()
    df["modelability"] = df["category_model"].map(MODELABILITY).fillna(0.25)
    df["score"] = df["modelability"] * df["thinness"]
    cols = ["ticker", "category_model", "title", "mid", "spread", "days_to_close",
            "volume", "open_interest", "liquidity_score", "thinness", "modelability", "score",
            "rules_primary"]
    cols = [c for c in cols if c in df.columns]
    return df.sort_values("score", ascending=False)[cols].reset_index(drop=True)


def category_summary(enriched: pd.DataFrame) -> pd.DataFrame:
    g = enriched.groupby("category_model")
    return pd.DataFrame({
        "n": g.size(),
        "median_spread": g["spread"].median(),
        "median_days": g["days_to_close"].median(),
        "total_volume": g["volume"].apply(lambda s: pd.to_numeric(s, errors="coerce").sum()),
    }).sort_values("n", ascending=False)


def snapshot(out_dir: str | Path = "prediction/out", max_days: float = 30, top: int = 40,
             refresh: bool = True) -> pd.DataFrame:
    """Pull all open markets, enrich, persist parquet + markdown, return ranked table."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = kalshi.markets(status="open", refresh=refresh)
    df = enrich(raw)
    ranked = rank_thin_modelable(df, max_days=max_days)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    df.to_parquet(out_dir / f"markets_{stamp}.parquet", index=False)
    df.to_parquet(out_dir / "markets_latest.parquet", index=False)
    md = ["# Kalshi open markets, " + stamp, "", category_summary(df).to_markdown(), "",
          f"## Top {top} thin, modelable markets closing within {max_days} days", "",
          ranked.head(top).drop(columns=["rules_primary"]).to_markdown(index=False, floatfmt=".2f")]
    (out_dir / "ranked_latest.md").write_text("\n".join(md))
    return ranked


if __name__ == "__main__":
    r = snapshot()
    print(r.head(40).drop(columns=["rules_primary"]).to_string())
