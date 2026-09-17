# Running the prediction stack on the home server

Everything is paper. Nothing here places exchange orders, and the repo must
not gain a path that does. The jobs below score markets, log to the ledger,
write the daily brief, and record the small bets Duncan places by hand.

## Install

```bash
git clone -b claude/new-session-uz9j48 https://github.com/dreece2304/Thesis-Code.git ~/side-projects
cd ~/side-projects
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev,prediction,investing,data]"
cp .env.example .env            # fill in the keys below
pytest                          # 100+ tests, offline, ~3 min
```

Data build (once, ~5 min; the cron jobs keep it fresh afterwards):

```bash
PAPER=1 python -c "from prediction.weather import live; live.refresh_data()"
python -c "from prediction.weather import rain; rain.fit_all()"
```

## Keys and accounts

| key | needed for | where |
|---|---|---|
| none | Kalshi REST market data, Open-Meteo, NWS, GHCN, FRED CSV, USGS, GISTEMP | already works |
| `KALSHI_API_KEY` + RSA private key | Kalshi websocket price stream (auth is required even for public channels); read only | kalshi.com account settings, API keys |
| `FRED_API_KEY` | faster FRED pulls, optional | fred.stlouisfed.org |
| `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | investing paper trading only; base URL is asserted paper | alpaca.markets paper account |
| `NOTION_API_KEY` + page ids | weekly status posting without MCP | notion.so integrations |
| `PAPER=1` | the live job refuses to start without it | .env |

## Schedule (cron, server local time = Pacific)

```cron
# temperature: evening run enters at lead 1 (Kalshi lists tomorrow at 07:00 PT), morning run adds at lead 0
15 7  * * *  cd ~/side-projects && . .venv/bin/activate && PAPER=1 python -m prediction.weather.live --refresh-data >> logs/temp.log 2>&1
15 18 * * *  cd ~/side-projects && . .venv/bin/activate && PAPER=1 python -m prediction.weather.live >> logs/temp.log 2>&1
# rain: after the 00z/12z global runs land and after HRRR/NBM refresh
30 6,12,18 * * *  cd ~/side-projects && . .venv/bin/activate && PAPER=1 python -m prediction.weather.rain >> logs/rain.log 2>&1
# brief, sized bet list, settlement, git push
45 6 * * *  cd ~/side-projects && . .venv/bin/activate && PAPER=1 python -m prediction.weather.daily > /dev/null && python -m prediction.weather.plan >> reports/daily/$(date +\%F).md && python -m prediction.weather.bets settle && git add ledger reports && git commit -qm "Daily brief $(date +\%F)" && git push -q
# weekly refit of the error distributions (Sunday)
0 3 * * 0  cd ~/side-projects && . .venv/bin/activate && python -c "from prediction.weather import rain; rain.fit_all()" >> logs/fit.log 2>&1
```

Ireland is 8 hours ahead of Pacific, so the 06:45 brief lands at 14:45 your time
and the 18:15 evening temperature run at 02:15. Move the brief to 22:45 PT if
you want it in your morning.

## Recording bets

```bash
python -m prediction.weather.bets add KXRAIN-26SEP18-DEN yes 0.56 8 --p 0.72 --market 0.56 --note "NBM+HRRR agree"
python -m prediction.weather.bets report      # hit rate, P&L, Brier vs market by category
python -m prediction.weather.plan             # today's sized list under the daily budget
```

The daily budget starts at $20 and rises to $40 after 50 settled tracked bets
with positive P&L and a Brier no worse than the market, then $80 at 150. It
never rises on paper results.

## Extra feeds worth wiring in next

- **Kalshi websocket** (`ticker`, `trade` channels): store every quote change
  in DuckDB. Gives real historical prices for the backtest instead of the
  reconstructed market. Needs the API key above.
- **ECMWF open data** (`ecmwf-opendata` package): IFS and AIFS GRIB direct
  from ECMWF, 6 hours earlier than Open-Meteo serves them. Free.
- **NOAA NOMADS**: HRRR and NBM GRIB2 direct; useful only if Open-Meteo lags.
- **Launch Library 2** (`ll.thespacedevs.com`): launch schedule for the
  monthly launch-count markets. Free, no key.
- **Climate Reanalyzer ERA5 daily** JSON: month-to-date global temperature,
  used for the GISTEMP monthly anomaly market.
- **OpenRouter rankings** (public page): weekly model market-share markets.
- **GPU**: not needed. WRF or an AI model at home would not beat HRRR or AIFS
  for these stations.
