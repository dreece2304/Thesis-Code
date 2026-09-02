"""Weekly status for the weather model via shared.report."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd

from shared.ledger import Ledger
from shared.report import Status, publish

from .evaluation import go_live_gate
from .kalshi import PaperBook
from .live import PROJECT


def weekly_status(ledger: Ledger, book: PaperBook | None = None, now: datetime | None = None) -> Status:
    now = now or datetime.now()
    week_ago = now - timedelta(days=7)
    df = ledger.predictions(project=PROJECT)
    made = df[df.timestamp >= week_ago]
    resolved = df.dropna(subset=["outcome"])
    with_mkt = resolved.dropna(subset=["market_prob"])
    pnl = book.pnl_summary() if book is not None else {"pnl": 0.0, "filled": 0, "settled": 0}
    gate = go_live_gate(with_mkt.model_prob, with_mkt.market_prob, with_mkt.outcome, pnl["pnl"]) if len(with_mkt) \
        else {"n": 0, "brier_ours": float("nan"), "brier_market": float("nan"), "passes": False, "reason": "no resolved rows"}
    done = [f"{len(made)} predictions this week, {len(resolved)} resolved in total, {pnl['filled']} paper fills.",
            f"Brier ours {gate['brier_ours']:.4f} vs market {gate['brier_market']:.4f} on {gate['n']} rows; "
            f"paper P&L after fees ${pnl['pnl']:.2f}."]
    if len(resolved):
        miss = resolved.assign(err=(resolved.model_prob - resolved.outcome).abs()).sort_values("err").iloc[-1]
        try:
            n = json.loads(miss.notes or "{}")
            where = f"{n.get('station')} {n.get('side')} {n.get('threshold')} lead {n.get('lead')}"
        except (json.JSONDecodeError, TypeError):
            where = miss.market_or_asset
        done.append(f"Biggest miss: {where}, p={miss.model_prob:.2f}, outcome {int(miss.outcome)}.")
    blocked = [] if gate["passes"] else [f"Go-live gate: {gate['reason']}."]
    nxt = ["Keep the paper job running twice daily; review calibration monthly."]
    return Status("prediction", done=done, blocked=blocked, next=nxt)


def publish_weekly(ledger: Ledger, book: PaperBook | None = None, reports_dir="reports", now=None) -> dict:
    return publish([weekly_status(ledger, book, now)], reports_dir=reports_dir, when=now)
