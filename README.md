# side-projects

Personal monorepo for seven linked side projects. See `CLAUDE.md` for the
full brief, hard rules and milestones.

| package | project | state |
|---|---|---|
| `shared/` | ledger (DuckDB + Brier), data pullers, sim utilities, weekly reports | working, tested |
| `investing/` | volatility-targeted trend following, paper-traded (Alpaca paper only) | skeleton |
| `prediction/` | Kalshi weather model (lead project, `docs/KALSHI_WEATHER_SPEC.md`), market mapper, fees, Kelly sim | weather pipeline built, paper only |
| `forecasting/` | non-LLM regime and event forecasts feeding 1 and 2 | skeleton |
| `nanofab_saas/` | PSF service (Geant4), thin-film fitting, lab ops spec | skeleton |
| `materials/` | open closed-loop materials discovery | skeleton |
| `learning/` | AI-for-science 12-month path | skeleton |
| `audit/` | inventory of existing projects, micro-SaaS scoring | scanner + report |

## Setup

```bash
uv venv .venv && source .venv/bin/activate      # or: python -m venv .venv
uv pip install -e ".[dev,investing,prediction]" # add data, forecasting, ... as needed
cp .env.example .env                            # fill in keys; .env is gitignored
pytest
```

## Using the shared pieces

```python
from shared.ledger import Ledger
with Ledger() as L:                       # $LEDGER_PATH, default data_cache/ledger.duckdb
    pid = L.log_prediction("prediction", "KXHIGHNY-26SEP05-B75", 0.62, market_prob=0.55)
    L.resolve(pid, outcome=1)
    print(L.brier_by_project())
    L.reliability_plot(path="reports/reliability.png")

from shared.data import open_meteo, nws, kalshi, fred
ens = open_meteo.ensemble(40.78, -73.97)   # GFS, ECMWF, ICON members, long format
obs = nws.station_observations("KNYC", start="2026-09-01")
mk = kalshi.markets(status="open")         # read only; no order code exists here
cpi = fred.series("CPIAUCSL")              # works without a key

from prediction.fees import kalshi_fee
from prediction.sim.kelly import simulate_preset
print(simulate_preset("weather_daily", kelly_multiplier=0.25).summary())
```

Weekly status: build `shared.report.Status` objects and call
`shared.report.publish(...)`. It always writes `reports/YYYY-WW.md` and posts to
Notion when `NOTION_API_KEY` and `NOTION_PAGE_<PROJECT>` are set.

## Weather model (project 2, lead)

```bash
PAPER=1 python -m prediction.weather.live --refresh-data   # build 3-year archive, fit errors, score, paper orders
python -c "from prediction.weather import archive, backtest; print(backtest.run_backtest(archive.load_archive()).to_markdown())"
```

Everything is paper: the job raises without `PAPER=1`, orders go to a
`paper_orders` table in `data_cache/ledger_weather.duckdb`, and no code in the
repo can place an exchange order.

## Audit of an existing machine

Run inside WSL, where the old projects live:

```bash
python -m audit.scan ~ ~/projects --out audit/inventory.json --md audit/INVENTORY.md
```

## Legacy: MATLAB thesis code

The `.m` and `.mat` files at the repo root are the 2018 MATLAB model of a
hybrid battery plus supercapacitor energy-storage system for grid frequency
response (control logic, cycle counting, NPV). They are catalogued in
`audit/REPORT.md` and are not imported by anything here.
