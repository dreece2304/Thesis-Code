# CLAUDE.md

This file is the working brief for Claude Code on this repo. The master brief
follows verbatim; a "Repo state" section records what exists and what is
blocked. Keep both current. The weather model spec it references lives at
`docs/KALSHI_WEATHER_SPEC.md`.

## Repo state (update every session)

- Branching: sessions run on the branch the harness assigns (currently
  `claude/new-session-uz9j48`). Per-project branches (`inv/`, `pm/`, ...) start
  once this skeleton is on `main`.
- Environment: `uv venv .venv && uv pip install -e ".[dev,investing,prediction]"`, then `pytest`.
  Tests are offline (network is blocked in the test session).
- Done: repo skeleton, CI, `shared/ledger`, `shared/data` (FRED, Open-Meteo
  forecast/ensemble/archive/previous-runs, NWS, GHCN, Kalshi read-only,
  yfinance), `shared/sim`, `shared/report`, `prediction/fees.py`,
  `prediction/sim/kelly.py` (from spec), `prediction/mapper.py`,
  `prediction/weather/` (stations, archive, errors, model, market_model,
  kalshi, sizing, evaluation, backtest, live, report), `forecasting/data.py`,
  `forecasting/baseline.py`, `investing/backtest.py`, `investing/overlay.py`,
  `audit/scan.py`, `audit/REPORT.md` for this repo.
- Weather model: paper only. `prediction/weather/live.py` refuses to run
  without `PAPER=1`. Ledger for it is `data_cache/ledger_weather.duckdb`
  (project name `weather`), separate from the investing ledger.
- Live facts confirmed 2026-09-02: Kalshi KXHIGH* rules name CLINYC, CLIMDW,
  CLIMIA, CLILAX, CLIAUS, CLIDEN, CLIPHL and settle "according to The Weather
  Company"; settled markets expose the settled high in `expiration_value`;
  the API now serves `*_dollars` string prices and `orderbook_fp`. Open-Meteo
  previous-runs serves hourly leads 1..5 for 3 years in one call per model.
- Blocked, needs Duncan: `kelly_bankroll_simulator.jsx` and
  `regime_portfolio_simulator.jsx` are not in this repo (sim built from spec).
  The WSL scan must be run locally with `python -m audit.scan`; the Geant4 PSF
  code is not in this repo. Yahoo Finance is unreachable from the web sandbox
  so the investing real-data backtest has to run on the home machine.
- This repo was `Thesis-Code` (2018 MATLAB battery model). Those files stay at
  the root untouched until Duncan decides where they go.

---

# Master brief for Claude Code

You are building a personal monorepo for Duncan: seven linked side projects covering systematic investing, prediction-market modelling, a forecasting engine, a micro-SaaS toolkit for nanofab users, open materials discovery, an AI-for-science learning path, and an audit of existing code. Work autonomously in the background. Prefer shipping small working pieces with tests over large unfinished ones.

## Who you are working for
- Senior process development engineer (ALD/MLD, plasma etch, lithography), PhD in chemical engineering, strong at modelling (physics, statistics, software). Comfortable with Python, C++, Geant4, WSL2, miniforge/mamba, Notion MCP.
- Environment: WSL2 on a Windows machine, miniforge/mamba, an always-on home server (Linux) being built for these services. Assume a consumer NVIDIA GPU may be available; degrade gracefully to CPU.
- Communication style: concise, plain language, no em dashes, no filler. Ask questions one at a time and only when blocked.

## Hard rules
1. Nothing from Duncan's employer (Fab2, formerly Atomic Semi): no tool data, recipes, chamber designs, lithography work, or code from work. Everything here runs on personal hardware and public data. If a task looks like it touches employer IP, stop and flag it.
2. No live money. All trading and prediction-market code runs against paper accounts, sandboxes, or logged hypothetical trades only. A live-trading path must not exist in this repo.
3. No secrets in code. Read API keys from `.env` (gitignored). Create `.env.example` with placeholders.
4. The Geant4 PSF code from the UW PhD is cleared for reuse (Duncan confirmed the UW IP position). Locate it during the audit and build the service on it.
5. Every model that produces a probability logs it to the shared calibration ledger with the outcome when known.
6. Tests for anything that touches money, probabilities, or physics. `pytest` must pass before you mark a milestone done.
7. Commit small, with clear messages. One branch per project: `inv/`, `pm/`, `fc/`, `saas/`, `mat/`, `learn/`, `audit/`. Merge to `main` only when tests pass.

## Repo layout
```
side-projects/
  README.md                 # what this is, how to run each part
  CLAUDE.md                 # this file, kept current
  pyproject.toml            # shared deps; project extras per package
  .env.example
  shared/                   # common infrastructure
    ledger/                 # calibration ledger (DuckDB), Brier scoring, plots
    data/                   # data pullers: FRED, Open-Meteo, NWS, Kalshi, yfinance
    sim/                    # Monte Carlo utilities, seeded RNG, Kelly sizing
    report/                 # weekly report generator, Notion MCP writer
  investing/                # project 1
  prediction/               # project 2
  forecasting/              # project 3 (feeds 1 and 2)
  nanofab_saas/             # project 4: psf_service/, thinfilm_fit/, lab_ops/
  materials/                # project 5
  learning/                 # project 6
  audit/                    # project 7: WSL project scan results
  notebooks/                # exploration only, never imported by code
  tests/
```

## Shared infrastructure (build first, week 1)
- `shared/ledger`: DuckDB table `predictions(id, project, market_or_asset, timestamp, model_prob, market_prob, stake, outcome, resolved_at, notes)`. Functions: `log_prediction`, `resolve`, `brier_by_project`, `calibration_curve`, `reliability_plot`.
- `shared/data`: thin, cached pullers with rate limiting. FRED (`fredapi`), Open-Meteo (free, no key), NWS API (station obs), Kalshi REST (markets, order book, history), yfinance monthly prices. Cache to Parquet under `data_cache/` (gitignored).
- `shared/sim`: `mulberry`-style seeded RNG wrapper on numpy, Kelly fraction with fee, drawdown and CAGR metrics.
- `shared/report`: builds a Markdown weekly report per project and posts it to the matching Notion project page (Life Wiki > Projects) via MCP. Fall back to writing `reports/YYYY-WW.md` if MCP is unavailable.

## Project 1: Systematic Investing Engine (`investing/`)
Goal: volatility-targeted trend following on a small ETF basket, paper-traded, with the regime signal from project 3 as an optional overlay.
Milestones:
1. Port `regime_portfolio_simulator.jsx` logic to Python (`investing/sim/regimes.py`) with the same three regimes; reproduce its qualitative results in a test.
2. Real-data backtest 1990 to present using monthly yfinance data for SPY, QQQ, TLT, GLD, BIL (use proxies or index data before ETF inception). Strategy: 10-month moving average filter, per-asset vol targeting to a 10% portfolio budget, cash otherwise. Walk-forward, no lookahead. Report CAGR, max drawdown, Sharpe, turnover, and an estimate of tax drag (short vs long term).
3. Compare to 60/40 and to SPY. Sensitivity over lookback 3 to 12 months and vol target 5 to 20%.
4. Alpaca paper-trading script: monthly rebalance, logs every order, never touches a live endpoint (assert on base URL).
5. Weekly report to Notion.
Kill signals to surface in the report: strategy underperforms 60/40 risk-adjusted over the walk-forward window; turnover implies costs above 50 bps a year.

## Project 2: Prediction Market Models (`prediction/`)
Goal: calibrated models for niche Kalshi markets, paper-traded, sized by fractional Kelly with Kalshi fees.
Fee model: taker fee per contract = 0.07 × price × (1 − price), maker = 25% of taker, rounded up to the cent.
Milestones:
1. Port `kelly_bankroll_simulator.jsx` to `prediction/sim/kelly.py` with the market-type presets; tests on expected ruin behaviour.
2. Kalshi market mapper: pull all open markets, classify by category, liquidity, time to resolution, and store the exact resolution rule text. Output a ranked table of thin, modelable markets.
3. Weather model (first target): follow `KALSHI_WEATHER_SPEC.md` exactly. It contains the final decisions on cities, contract type, probability model, entry and exit, sizing, order handling, data sources, pipeline, backtest protocol, tests, and the go-live gate. Start here before any other project 2 work.
4. Paper trading loop: as specified in `KALSHI_WEATHER_SPEC.md` (scheduled job, limit orders, quarter Kelly, correlation grouping, shared ledger).
5. Econ nowcast (second target): CPI and payrolls distribution from Cleveland Fed nowcast, GDPNow, consensus scrape, and alt data (AAA gas, Truflation if accessible). Compare bucket probabilities to market.
6. Fed consistency scanner: check that Kalshi single-meeting and cumulative rate-path markets are mutually consistent with CME futures; flag violations.
7. Longshot-selling base-rate model: for "will X happen by date" markets, estimate historical base rates by event class (LLM used only to classify and extract, never to set the probability).
Go-live gate (report only, no code path): weather Brier score beats the market-implied Brier over 200 resolved predictions.

## Project 3: Forecasting Engine (`forecasting/`)
Goal: non-LLM forecasts and regime states that feed projects 1 and 2 through the shared ledger.
Milestones:
1. Data pipelines: FRED (CPI, payrolls, claims, yields), VIX and VIX term structure, realised vol from daily SPY.
2. Baseline: market-implied probabilities only. Every model must beat this on Brier or it is not used.
3. Regime model: hidden Markov model (3 states) on monthly returns and VIX term structure. Validate that states predict next-month realised vol out of sample. Expose `current_regime()` for project 1.
4. Event models: Fed decision probability vs futures; CPI and payrolls distributions (shared with project 2).
5. Combination: log-odds averaging of model and market probabilities with shrinkage; tune shrinkage on the ledger.
6. Daily JSON output `forecasting/out/latest.json` consumed by projects 1 and 2; weekly report.
Gate: a regime signal below 60% out-of-sample accuracy must not be used for sizing (project 1 test enforces this).

## Project 4: Nanofab SaaS toolkit (`nanofab_saas/`)
Goal: three products for one buyer (nanofab users, facility managers, small hardware fabs), built in order.
### 4a `psf_service/` (first)
- Geant4 app (start from the existing PhD code found in the audit): electron beam into a user-defined multilayer stack on Si (or other substrate), 1 to 200 keV, Gaussian beam, records energy deposited in the resist layer vs radial distance. Batch mode, macro-driven, no visualisation.
- Post-processing: radial PSF to CSV, fit double and triple Gaussian (alpha, beta, eta, and a mid-range term), export a BEAMER-compatible PSF text block and a plot.
- Service: FastAPI with a job queue (RQ or a simple SQLite queue), Docker container with Geant4 prebuilt, web form for stack entry, email or link when done. Pricing hooks for per-run and monthly via Stripe test mode.
- Validate against published PSF data for PMMA on Si at 30 and 100 keV; test tolerances.
### 4b `thinfilm_fit/` (second)
- Transfer-matrix engine (numpy) for multilayer reflectance, transmittance, and ellipsometric Psi and Delta; dispersion models: Cauchy, Sellmeier, Tauc-Lorentz, Drude, EMA for roughness; use `tmm` or `refellips` as reference for tests.
- Fitting: least squares with bounds, multi-start, uncertainty from the Jacobian; guard against unphysical solutions.
- Web app: upload CSV (wavelength, Psi, Delta or R), define stack, fit, export report. Free single-layer, paid multilayer and batch.
### 4c `lab_ops/` (later, spec only for now)
- Write a product spec and data model for tool booking, run logs, chemical inventory, and recipe tracking for small fabs. No code until validation conversations are done.

## Project 5: Open Materials AI Scientist (`materials/`)
Goal: open, closed-loop materials discovery on public data and simulation. Public data only; choose a chemistry space clearly outside employer scope (propose three and flag for Duncan to pick).
Milestones:
1. Environment: ASE, pymatgen, GPAW (CPU), MACE and MatterSim, BoTorch. Verify a GPAW relaxation and a MACE energy on a simple oxide agree within expected error.
2. Active learning for a potential (the first demo): hidden 1D or 2D energy surface as the "DFT" oracle, an ensemble surrogate, uncertainty-driven sampling vs random. Metric: oracle calls to reach a target force error. Then swap in a real system: MACE fine-tuned on GPAW frames of a small oxide.
3. Melt-quench MD with the ML potential for an amorphous film; extract density and RDF.
4. Bayesian optimisation over a small composition space against the surrogate plus periodic DFT checks.
5. Experiment tracking with MLflow; results mirrored to Notion weekly.

## Project 6: AI for Science learning path (`learning/`)
Goal: scaffold the 12-month path so each week has a runnable exercise.
Milestones:
1. Environment with PyTorch, transformers, PEFT, and a tiny chemistry corpus (public abstracts).
2. nanoGPT trained on that corpus; a notebook that shows attention written from scratch.
3. LoRA fine-tune of a 1B to 3B open model for structured extraction of process conditions from ALD abstracts (public papers only). Eval harness with exact-match and F1 on a hand-labelled set.
4. Weekly checklist synced to the Notion learning page.

## Project 7: Audit existing WSL projects (`audit/`)
Scan the WSL2 home directory and any project folders Duncan points to. For each project: what it does, language, last modified, dependencies, whether it runs, and a score against the micro-SaaS tests (recurring problem, people already paying for something worse, reachable buyer, clean IP). Flag anything that looks like employer work. Locate the Geant4 PSF project and note its state. Write `audit/REPORT.md` and post a summary to the micro-SaaS Notion page.

## Order of work
1. Repo skeleton, shared infrastructure, tests, CI (GitHub Actions running pytest).
2. Project 2 weather model per `KALSHI_WEATHER_SPEC.md` (lead project; highest priority).
3. Project 7 audit (cheap, informs project 4).
4. Project 2 milestone 2 (market mapper), project 3 milestone 1 and 2, project 1 milestone 1 and 2. These share data code, so build them together.
5. Project 4a PSF service prototype.
6. Project 5 milestone 1 and 2, project 6 milestone 1 and 2.
7. Everything else in milestone order, rotating weekly so no project stalls.

## Reporting
Every Sunday (or whenever a milestone completes) write a short status per project: done, blocked, next, and any question for Duncan. Post to the matching Notion page under a "Claude Code status" heading and append to `reports/`. Keep each status under 150 words.

## When to stop and ask
- Anything touching employer IP
- Any step that would cost money (cloud GPUs, paid APIs, Stripe live mode)
- A design decision that changes a project's goal rather than its implementation
Otherwise proceed.
