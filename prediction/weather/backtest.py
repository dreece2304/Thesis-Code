"""Walk-forward backtest over the archive, one month at a time.

Error fits for month M use only target dates before M. Recent-variance
weights and correlation groups use only dates before each decision date.
Market prices are reconstructed from the commoditised baseline (bias-corrected
mean model forecast, 3 deg F normal) plus logit noise, quoted with a two-tick spread;
fills follow the maker rule; fees on every fill.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from shared.sim.metrics import max_drawdown

from ..fees import fee_per_contract
from .archive import ensemble_mean_errors
from .errors import fit_errors, lookup, recent_bias, recent_variance
from .evaluation import calibration, go_live_gate, paired_bootstrap
from .kalshi import maker_fill
from .market_model import baseline_forecast, baseline_probability, reconstructed_quotes
from .model import probability
from .sizing import (CAP_PER_BET, CAP_TOTAL, KELLY_MULT, PAPER_BANKROLL, bet_key,
                     correlation_groups, size_bet)
from .stations import cut


@dataclass
class BacktestConfig:
    bankroll: float = PAPER_BANKROLL
    entry_lead: int = 1            # Kalshi lists each day's markets the day before (14:00 UTC)
    add_lead: int | None = None    # spec wanted 3 then 1; only lead 1 (and lead 0 live) exist
    entry_edge: float = 0.05
    add_edge: float = 0.03
    offsets: tuple = (-2, -1, 0, 1, 2)      # thresholds around the baseline forecast
    noise_sd_logit: float = 0.25
    baseline_sd: float = 3.0
    warmup_months: int = 6
    kelly_mult: float = KELLY_MULT
    cap_bet: float = CAP_PER_BET
    cap_total: float = CAP_TOTAL
    seed: int = 0
    max_months: int | None = None


@dataclass
class BacktestReport:
    predictions: pd.DataFrame
    trades: pd.DataFrame
    equity: pd.Series
    config: BacktestConfig
    summary: dict = field(default_factory=dict)

    def to_markdown(self) -> str:
        s = self.summary
        lines = [f"# Weather backtest ({s['start']} to {s['end']})", "",
                 f"predictions: {s['n_predictions']}, city-days: {s['n_city_days']}, "
                 f"trade candidates: {s['n_candidates']}, filled: {s['n_trades']} ({s['fill_rate']:.0%})", "",
                 "| scope | n | Brier ours | Brier market | Brier baseline | gap (mkt-ours) | 90% CI |",
                 "|---|---:|---:|---:|---:|---:|---|"]
        for scope, r in s["brier"].items():
            lines.append(f"| {scope} | {r['n']} | {r['brier_ours']:.4f} | {r['brier_market']:.4f} | "
                         f"{r['brier_baseline']:.4f} | {r['diff']:+.4f} | [{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}] |")
        lines += ["", f"P&L after fees: ${s['pnl']:.2f} on ${self.config.bankroll:.0f} "
                  f"({s['return']:+.1%}), max drawdown {s['max_drawdown']:.1%}, fees ${s['fees']:.2f}",
                  f"gate: {'PASS' if s['gate']['passes'] else 'FAIL'} ({s['gate']['reason']})", ""]
        return "\n".join(lines)


def candidate_contracts(baseline_forecast: float, offsets) -> list[tuple[int, str]]:
    base = int(np.floor(baseline_forecast + 0.5))
    return [(base + k, side) for k in offsets for side in ("above", "below")]


def _edge(p: float, side: str, quotes: dict) -> tuple[str, float | None, float]:
    """Best of buying YES or NO for a contract with our probability p of YES."""
    ask_yes = quotes["yes_ask"]
    ask_no = None if quotes["yes_bid"] is None else round(1 - quotes["yes_bid"], 4)
    best = ("yes", ask_yes, -np.inf)
    if ask_yes is not None and 0 < ask_yes < 1:
        best = ("yes", ask_yes, p - ask_yes - fee_per_contract(ask_yes, 100, maker=True))
    if ask_no is not None and 0 < ask_no < 1:
        e = (1 - p) - ask_no - fee_per_contract(ask_no, 100, maker=True)
        if e > best[2]:
            best = ("no", ask_no, e)
    return best


def _settle(t: dict, settlement: float) -> float:
    lo, hi = cut(t["threshold"], t["side"])
    yes = lo < settlement < hi
    won = yes if t["buy"] == "yes" else not yes
    pnl = (t["contracts"] * (1 - t["price"]) if won else -t["contracts"] * t["price"]) - t["fee"]
    t.update({"outcome_yes": int(yes), "won": bool(won), "pnl": pnl})
    return pnl


def run_backtest(archive: pd.DataFrame, cfg: BacktestConfig | None = None) -> BacktestReport:
    """Walk forward by decision date. See the module docstring for the rules."""
    cfg = cfg or BacktestConfig()
    rng = np.random.default_rng(cfg.seed)
    a = archive.dropna(subset=["settlement"]).copy()
    a["target_date"] = pd.to_datetime(a["target_date"])
    leads = (cfg.entry_lead,) if cfg.add_lead is None or cfg.add_lead == cfg.entry_lead else (cfg.entry_lead, cfg.add_lead)
    settle_map = a.groupby(["station", "target_date"])["settlement"].first().to_dict()
    fc_map = {k: dict(zip(g.model, g.forecast)) for k, g in a.groupby(["station", "target_date", "lead"])}
    stations = sorted(a.station.unique())
    months = sorted(a["target_date"].dt.to_period("M").unique())
    months = months[cfg.warmup_months:]
    if cfg.max_months:
        months = months[-cfg.max_months:]
    err_wide = ensemble_mean_errors(a, cfg.entry_lead)
    preds, trades = [], []
    bankroll = cfg.bankroll
    equity = {}
    open_bets: dict[str, float] = {}
    open_trades: list[dict] = []
    chosen: dict[tuple, tuple] = {}

    for month in months:
        m_start = month.to_timestamp()
        m_end = (month + 1).to_timestamp()
        fits = fit_errors(a, before=m_start, leads=leads, months=(month.month, (month + 1).month))
        if fits.empty:
            continue
        for d in pd.date_range(m_start, m_end - pd.Timedelta(days=1), freq="D"):
            # 1. settle trades whose target is today
            still = []
            for t in open_trades:
                if t["target_date"] == d:
                    pnl = _settle(t, settle_map[(t["station"], d)])
                    bankroll += pnl + t["stake"]
                    open_bets[t["bet_key"]] = max(0.0, open_bets.get(t["bet_key"], 0.0) - t["stake"])
                    trades.append(t)
                else:
                    still.append(t)
            open_trades = still
            equity[d] = bankroll + sum(t["stake"] for t in open_trades)
            groups = correlation_groups(err_wide, asof=d)
            # 2. decide: entries at entry_lead, adds at add_lead
            for lead in leads:
                target = d + pd.Timedelta(days=lead)
                for station in stations:
                    fc = fc_map.get((station, target, lead))
                    settlement = settle_map.get((station, target))
                    if not fc or settlement is None:
                        continue
                    dists = lookup(fits, station, lead, target.month)
                    if not dists:
                        continue
                    rv = recent_variance(a, station, lead, asof=d)
                    rb = recent_bias(a, station, lead, asof=d)
                    base_fc = baseline_forecast(fc, rb)
                    key = bet_key(station, target, groups)
                    is_entry = lead == cfg.entry_lead
                    prior = chosen.get((station, target))
                    best = None
                    for threshold, side in candidate_contracts(base_fc, cfg.offsets):
                        p, sd, comp = probability(fc, dists, rv, threshold, side)
                        p_base = baseline_probability(base_fc, threshold, side, cfg.baseline_sd)
                        bid, ask, mid = reconstructed_quotes(p_base, rng, cfg.noise_sd_logit)
                        lo, hi = cut(threshold, side)
                        outcome = int(lo < settlement < hi)
                        preds.append({"station": station, "target_date": target, "decision_date": d, "lead": lead,
                                      "threshold": threshold, "side": side, "p_ours": p, "sd": sd,
                                      "p_market": mid, "p_baseline": p_base, "outcome": outcome})
                        if not is_entry and prior is not None and (threshold, side) != prior:
                            continue
                        buy, opp, edge = _edge(p, side, {"yes_bid": bid, "yes_ask": ask})
                        if best is None or edge > best["edge"]:
                            best = {"threshold": threshold, "side": side, "buy": buy, "edge": edge, "p": p,
                                    "quotes": {"yes_bid": bid, "yes_ask": ask}, "opp": opp}
                    if best is None:
                        continue
                    if not is_entry and prior is None:
                        continue  # adds only on top of an entry
                    required = cfg.entry_edge if is_entry else cfg.add_edge
                    if best["edge"] <= required:
                        continue
                    p_side = best["p"] if best["buy"] == "yes" else 1 - best["p"]
                    limit = round(p_side - required, 2)
                    if not 0 < limit < 1:
                        continue
                    fill = maker_fill(best["buy"], limit, best["quotes"], 1)
                    size = size_bet(p_side, limit, bankroll, existing_bet_stake=open_bets.get(key, 0.0),
                                    existing_total_stake=sum(open_bets.values()), multiplier=cfg.kelly_mult,
                                    cap_bet=cfg.cap_bet, cap_total=cfg.cap_total)
                    rec = {"station": station, "target_date": target, "decision_date": d, "lead": lead,
                           "threshold": best["threshold"], "side": best["side"], "buy": best["buy"],
                           "p": best["p"], "edge": best["edge"], "limit": limit, "opposing": best["opp"],
                           "filled": fill.filled, "contracts": size.contracts, "price": limit,
                           "bet_key": key, "capped_by": size.capped_by, "is_entry": is_entry}
                    if not fill.filled or size.contracts == 0:
                        rec.update({"stake": 0.0, "fee": 0.0, "pnl": np.nan, "won": None, "outcome_yes": None})
                        trades.append(rec)
                        continue
                    fee = fee_per_contract(limit, 100, maker=True) * size.contracts
                    stake = size.contracts * limit + fee
                    rec.update({"stake": stake, "fee": fee})
                    bankroll -= stake
                    open_bets[key] = open_bets.get(key, 0.0) + stake
                    open_trades.append(rec)
                    if is_entry:
                        chosen[(station, target)] = (best["threshold"], best["side"])

    for t in open_trades:  # settle whatever is left with known outcomes
        pnl = _settle(t, settle_map[(t["station"], t["target_date"])])
        bankroll += pnl + t["stake"]
        trades.append(t)

    P = pd.DataFrame(preds)
    T = pd.DataFrame(trades)
    eq = pd.Series(equity).sort_index()
    if not eq.empty:
        eq.iloc[-1] = bankroll
    filled = T[T.filled & (T.contracts > 0)] if len(T) else T
    brier = {}
    if len(P):
        scopes = {"pooled": P, **{st: g for st, g in P.groupby("station")}}
        for name, g in scopes.items():
            b = paired_bootstrap(g.p_ours, g.p_market, g.outcome, seed=cfg.seed)
            b["brier_baseline"] = float(np.mean((g.p_baseline - g.outcome) ** 2))
            brier[name] = b
    pnl = float(filled.pnl.sum()) if len(filled) else 0.0
    summary = {
        "start": str(P.target_date.min().date()) if len(P) else None,
        "end": str(P.target_date.max().date()) if len(P) else None,
        "n_predictions": int(len(P)), "n_city_days": int(P.groupby(["station", "target_date"]).ngroups) if len(P) else 0,
        "n_trades": int(len(filled)), "fill_rate": float((T.filled & (T.contracts > 0)).mean()) if len(T) else 0.0,
        "n_candidates": int(len(T)),
        "brier": brier, "pnl": pnl, "return": pnl / cfg.bankroll,
        "fees": float(filled.fee.sum()) if len(filled) else 0.0,
        "max_drawdown": max_drawdown(eq.to_numpy()) if len(eq) > 1 else 0.0,
        "calibration": calibration(P.p_ours, P.outcome).to_dict("records") if len(P) else [],
        "gate": go_live_gate(P.p_ours, P.p_market, P.outcome, pnl, seed=cfg.seed) if len(P) else
                {"passes": False, "reason": "no predictions"},
    }
    return BacktestReport(P, T, eq, cfg, summary)
