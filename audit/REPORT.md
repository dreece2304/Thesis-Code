# Audit report

Scope so far: the contents of this repository. The WSL2 home directory is not
reachable from Claude Code on the web, so the machine-wide scan has to be run
locally:

```bash
python -m audit.scan ~ ~/projects --out audit/inventory.json --md audit/INVENTORY.md
```

Commit the two output files and the next session will fill in the per-project
assessments below. The scanner flags Geant4 projects (to locate the PhD PSF
code) and any file containing employer terms.

## Projects found

### 1. Thesis-Code (this repo, root `.m` files)

| field | value |
|---|---|
| what it does | Sizes a hybrid energy-storage system (lithium battery plus supercapacitor) for grid frequency response. Simulates control against a frequency trace, counts cycles for battery ageing, and evaluates net present value over the system life. Includes an optimiser wrapper and surface plots over capacity pairs. |
| language | MATLAB (12 scripts and functions) plus two `.mat` data files (`Frequency.mat` 52 MB, `LongCodeRun.mat` 53 MB) |
| last modified | 2018-08-28 (git history 2018-08-13 to 2018-08-28) |
| dependencies | MATLAB base; likely Optimization Toolbox for `opt.m` |
| runs | untested here (no MATLAB); code is self-contained and loads `Frequency.mat` |
| entry points | `System.m` (single design), `opt.m` (optimise), `SurfacePlots.m`, `Graphs.m` |
| employer flag | none. University thesis work from 2018, predates the current employer, unrelated domain (grid storage economics). |
| Geant4 PSF | no |

Micro-SaaS score (0 to 3 each):

| test | score | note |
|---|---:|---|
| recurring problem | 1 | storage sizing is a real recurring problem but for utilities and developers, not the nanofab buyer |
| people paying for something worse | 1 | commercial tools exist (HOMER, PLEXOS); this is a simplified academic model |
| reachable buyer | 0 | no overlap with the chosen buyer (nanofab users) |
| clean IP | 3 | own thesis work |

Recommendation: archive. Not a product candidate. Worth a single Python port
only if the battery-plus-supercapacitor control logic is wanted as a teaching
example. The two 50 MB `.mat` files should move to Git LFS or out of the repo
if this repository becomes the monorepo home.

## Still to locate

- Geant4 PSF project from the UW PhD (hard rule 4). Expected markers:
  `G4RunManager`, `find_package(Geant4)`, `.mac` macros, radial energy
  deposition output. Run the scanner and check the `geant4` column.
- `regime_portfolio_simulator.jsx` and `kelly_bankroll_simulator.jsx`, needed
  for project 1 milestone 1 and project 2 milestone 1. The scanner records
  `javascript` files per project; grep the inventory for `.jsx`.

## Data-source checks done on the way (2026-09-02)

- GHCN-Daily TMAX matches Kalshi's settled high on 199 of 204 days for NYC,
  CHI, MIA; the rest are unpublished GHCN days and one 5 F Miami gap.
- Kalshi rules name CLINYC, CLIMDW, CLIMIA, CLILAX, CLIAUS, CLIDEN, CLIPHL
  and settle "according to The Weather Company".
