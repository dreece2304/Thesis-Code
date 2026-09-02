# Kalshi weather model: build spec

Part of the `prediction/` package in the side-projects monorepo. Supersedes the weather milestones in `CLAUDE.md`. Paper trading only until the go-live gate is met and Duncan explicitly approves.

## Decisions (final)
- Markets: Kalshi daily high temperature series (KXHIGH*) for NYC, Chicago, Miami. Add LA and Austin only after the first three pass the calibration gate.
- Contract type: threshold ("X or above" / "X or below") contracts first. Range buckets only if a threshold contract is unavailable, and never with more than one bucket per city-day.
- Probability model: per-station, per-lead-day (1 to 5), per-month error distributions fitted for each ensemble model (ECMWF IFS, GFS, ICON) against the settlement value. Combine by inverse recent error variance over a rolling 60-day window. Predictive distribution is a fitted skew-t (fall back to a kernel density if the fit is unstable), never an assumed normal.
- Entry: 3 days out, only when edge after fees exceeds 5 percentage points. One add at 1 day out if the edge persists above 3 points. Hold to settlement.
- Sizing: quarter Kelly per contract. Max 5% of bankroll per city-day, max 15% across all open positions. All contracts for one city-day are one bet. Cities under the same synoptic system (flag when the ensemble mean errors for two cities are correlated above 0.5 over the trailing 30 days) count as one bet.
- Orders: limit orders only (maker fee). Post at our fair value minus the required edge; if unfilled by the next model update, cancel and re-post.
- Bankroll: paper $2,000, separate ledger from the investing project.
- Go-live gate: over at least 200 resolved predictions across all three cities, our Brier score must be lower than the market-implied Brier score with a paired bootstrap 90% interval that excludes zero, and paper P&L after fees must be positive. Then Duncan decides; no code path goes live without a manual flag.

## Data
- Settlement: NWS Daily Climate Report (CLI product) for the exact station named in each contract's rules. Store the rules text with every market. Map: NYC to Central Park (KNYC), Chicago to Midway (KMDW), Miami to Miami International (KMIA). Verify against the live rules before assuming.
- Historical settlement values: NOAA GHCN-Daily TMAX for the same stations, cross-checked against archived CLI reports where available.
- Forecast archives: Open-Meteo Historical Forecast API (free) for ECMWF IFS, GFS, ICON, daily max temperature at lead 1 to 5 days, at least three years. Cache as Parquet.
- Live forecasts: Open-Meteo forecast endpoint, pulled at 06:00 and 18:00 local for each city (after major model cycles). Also pull the NWS point forecast so we can reconstruct the "market model" as a baseline.
- Kalshi: REST API for markets, order books, trade history; websocket for live prices during paper trading. Store the full order book snapshot at every decision.
- Optional later: MOS (NBM) guidance, station observations through the day for the 1-day add.

## Pipeline
1. `prediction/weather/stations.py`: station registry with lat/lon, GHCN id, NWS CLI id, Kalshi series prefix, time zone, and rounding rules.
2. `prediction/weather/archive.py`: pull and cache three years of forecasts and settlements; produce a tidy table `(station, target_date, lead, model, forecast, settlement, error)`.
3. `prediction/weather/errors.py`: fit error distributions per station, lead, month; save parameters; produce diagnostic plots (error vs lead, seasonal bias).
4. `prediction/weather/model.py`: `probability(station, date, threshold, side, lead) -> (p, sd, components)`; ensemble weighting; skew-t; unit tests with synthetic data.
5. `prediction/weather/market_model.py`: reconstruct the commoditised baseline (NWS point forecast, fixed 3°F normal) to measure how much of our edge is model vs crowd sloppiness.
6. `prediction/weather/kalshi.py`: market discovery for KXHIGH*, rules parser, order book snapshot, paper order simulator with maker fee and partial-fill rule (fill only if our limit price is at or better than the best opposing quote at snapshot time; otherwise unfilled).
7. `prediction/weather/backtest.py`: walk-forward over the archive, one month at a time, retrain error fits on trailing data only; report Brier ours vs market vs baseline, calibration plot, P&L, drawdown, trades. Use historical Kalshi prices where obtainable; where not, use the reconstructed market model plus noise calibrated from any live data collected.
8. `prediction/weather/live.py`: scheduled job (cron on the home server, 06:15 and 18:15 local per city) that scores every open market, applies entry and sizing rules, posts paper orders, and logs to the shared ledger.
9. `prediction/weather/report.py`: weekly Notion status via `shared/report`: predictions made, resolved, Brier ours vs market, P&L, biggest miss and why.

## Backtest protocol (must hold or the result does not count)
- No lookahead: error fits use only data before the target date.
- Fees on every fill; maker fee only if the limit-fill rule is satisfied.
- Report per-city and pooled results; a model that works in Miami only is a Miami model.
- Report the baseline (commoditised) strategy alongside ours on the same days.
- Bootstrap the Brier difference; show the interval.

## Tests
- Synthetic-data tests for `model.py` (recovers known bias and sd), `kalshi.py` fee formula against the published schedule, sizing caps, and correlation grouping.
- A regression test that the live job refuses to run without `PAPER=1`.

## Order of work for Claude Code
1. Stations, archive pull, error fits, diagnostics (week 1).
2. Model, market model, tests (week 2).
3. Kalshi client, rules parser, paper simulator (week 2 to 3).
4. Backtest and first report (week 3 to 4). Post to Notion with the Brier gap and a recommendation.
5. Live paper job on the home server (week 4). Runs until the gate is met.

## Open items for Duncan (do not block on these)
- Confirm station mapping from live contract rules once the Kalshi client works.
- Decide whether to add Kalshi precipitation markets after the temperature gate.
