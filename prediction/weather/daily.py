"""One-shot daily brief: settle, score, and write reports/daily/YYYY-MM-DD.md.

    PAPER=1 python -m prediction.weather.daily

Sections: scorecard (ledger Brier and hit rates vs market, manual bets),
rain picks (calibrated model vs market for today and tomorrow), temperature
picks, and the standing non-weather positions to re-check.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from shared.ledger import Ledger, brier_score

from . import archive as A
from . import bets as BT
from . import errors as E
from . import kalshi as KW
from . import live
from . import rain as R
from .stations import ACTIVE

STANDING = [
    "KXRIEMANN-35-28JAN01", "KXFEDDECISION-26SEP-H25", "KXEFFR-26OCT01-T3.75", "KXEFFR-26OCT01-T3.50",
    "KXNEXTHURDATE-26DEC01-26OCT01", "KXHURCTOTMAJ-26DEC01-T0", "KXHURCTOT-26DEC01-T4", "KXREACTOR-26DEC31",
    "KXRAINHOUM-26SEP-7", "KXRAINHOUM-26SEP-5",
]


def scorecard(ledger: Ledger) -> list[str]:
    lines = ["| project | logged | resolved | Brier ours | Brier market | hit rate ours | hit rate market |", "|---|---:|---:|---:|---:|---:|---:|"]
    for proj in ("weather", "weather_rain"):
        df = ledger.predictions(project=proj)
        res = df.dropna(subset=["outcome"])
        m = res.dropna(subset=["market_prob"])
        if len(res):
            lines.append(f"| {proj} | {len(df)} | {len(res)} | {brier_score(res.model_prob, res.outcome):.3f} | "
                         f"{brier_score(m.market_prob, m.outcome) if len(m) else float('nan'):.3f} | "
                         f"{((res.model_prob > 0.5).astype(int) == res.outcome).mean():.0%} | "
                         f"{((m.market_prob > 0.5).astype(int) == m.outcome).mean() if len(m) else float('nan'):.0%} |")
        else:
            lines.append(f"| {proj} | {len(df)} | 0 | | | | |")
    rep = BT.Bets(ledger).report()
    lines.append("")
    lines.append(f"Manual bets: {rep['bets']} placed, {rep['settled']} settled" +
                 (f", hit rate {rep['hit_rate']:.0%}, P&L ${rep['pnl']:.2f} on ${rep['staked']:.2f} staked" if rep["settled"] else "") + ".")
    return lines


def rain_section(fits: pd.DataFrame, now: datetime) -> tuple[list[str], pd.DataFrame]:
    df = R.screen(fits, now=now)
    if df.empty:
        return ["No open rain markets."], df
    df = df[~df.locked].copy()
    df["gap"] = df[["edge_yes", "edge_no"]].max(axis=1)
    df["pick"] = df.apply(lambda r: "YES" if (r.edge_yes or -1) >= (r.edge_no or -1) else "NO", axis=1)
    top = df.sort_values("gap", ascending=False).head(8)
    lines = ["| market | our P(rain) | market | pick | gap |", "|---|---:|---:|---|---:|"]
    for r in top.itertuples():
        lines.append(f"| {r.ticker} | {r.p:.2f} | {r.yes_bid:.2f}/{r.yes_ask:.2f} | {r.pick} | {r.gap:+.2f} |")
    return lines, df


def temp_section(now: datetime) -> tuple[list[str], pd.DataFrame]:
    a, fits = A.load_archive(), E.load_fits()
    s = live.score(ACTIVE, a, fits, now, snapshots=False)
    if s.empty:
        return ["No scorable temperature markets (lead 0 after the morning cutoff, or none open)."], s
    lines = ["| market | lead | our P | baseline | market bid/ask |", "|---|---:|---:|---:|---|"]
    for r in s.sort_values(["target_date", "station", "threshold"]).itertuples():
        lines.append(f"| {r.ticker} | {r.lead} | {r.p:.2f} | {r.p_baseline:.2f} | {r.yes_bid}/{r.yes_ask} |")
    return lines, s


def standing_section() -> list[str]:
    from shared.data import kalshi as kx
    lines = ["| market | yes bid/ask | status |", "|---|---|---|"]
    for t in STANDING:
        try:
            m = kx.market(t)
            lines.append(f"| {t} | {m.get('yes_bid_dollars','')[:4]}/{m.get('yes_ask_dollars','')[:4]} | {m.get('status')} {m.get('result') or ''} |")
        except Exception as e:  # network hiccup; keep the brief going
            lines.append(f"| {t} | ? | {str(e)[:40]} |")
    return lines


def build(now: datetime | None = None, out_dir: str | Path = "reports/daily") -> Path:
    now = now or datetime.now(timezone.utc)
    with Ledger(live.weather_ledger_path()) as L:
        book = KW.PaperBook(L)
        KW.resolve_settled(L, book, ACTIVE)
        R.resolve_settled(L)
        BT.Bets(L).settle_from_kalshi()
        card = scorecard(L)
        fits = R.load_fits()
        rain_lines, rain_df = rain_section(fits, now)

    temp_lines, _ = temp_section(now)
    lines = [f"# Daily brief {now:%Y-%m-%d %H:%M} UTC", "", "## Scorecard", *card, "", "## Rain", *rain_lines, "",
             "## Temperature", *temp_lines, "", "## Standing positions", *standing_section(), ""]
    out = Path(out_dir) / f"{now:%Y-%m-%d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="reports/daily")
    a = ap.parse_args(argv)
    p = build(out_dir=a.out)
    print(p.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
