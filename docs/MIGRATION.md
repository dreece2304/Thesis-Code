# Migrating to a standalone `side-projects` repo on WSL2

The monorepo was built inside `Thesis-Code` on branch `claude/new-session-uz9j48`.
Everything below moves it to its own repository and sets up the machine.

## 1. Create the repo

On GitHub: new private repository `side-projects`, no README, no licence
(the branch already has both). Do not initialise it.

## 2. Move the history over (WSL)

```bash
mamba create -n tools -c conda-forge git-filter-repo -y && mamba activate tools
cd ~/projects
curl -sO https://raw.githubusercontent.com/dreece2304/Thesis-Code/claude/new-session-uz9j48/scripts/migrate_to_side_projects.sh
bash migrate_to_side_projects.sh git@github.com:dreece2304/side-projects.git
```

The script clones the branch, strips every `.m` and `.mat` file from history
(the two 50 MB `.mat` files would otherwise follow you forever), renames the
branch `main`, and pushes. `Thesis-Code` is untouched and keeps the thesis.

## 3. Environments (miniforge)

```bash
cd ~/projects/side-projects
mamba env create -f envs/side-projects.yml
mamba activate side-projects
uv pip install -e ".[dev,prediction,investing,forecasting,data,nanofab]"
cp .env.example .env      # fill in keys; see docs/HOME_SERVER.md
pytest                    # ~3 min, offline
```

Heavy stacks live in their own envs so the main one stays fast:
`envs/materials.yml` (GPAW, ASE, MACE), `envs/learning.yml` (PyTorch CUDA),
`envs/geant4.yml` (prebuilt Geant4 from conda-forge, for the PSF service).
Create them when those projects start, not now.

## 4. Data build

```bash
PAPER=1 python -c "from prediction.weather import live; live.refresh_data()"   # ~4 min
python -c "from prediction.weather import rain; rain.fit_all()"                # ~12 min
```

## 5. Schedule

Enable systemd so cron survives: in `/etc/wsl.conf`

```ini
[boot]
systemd=true
```

then `wsl --shutdown` from PowerShell, reopen, `sudo systemctl enable --now cron`,
and paste the cron block from `docs/HOME_SERVER.md` into `crontab -e`.
WSL only runs while a window or `wsl` process is open; for an always-on job
keep a terminal open or move the crontab to the home server.

## 6. Claude Code on WSL

```bash
npm install -g @anthropic-ai/claude-code
cd ~/projects/side-projects && claude
```

First session: `/init` is not needed (CLAUDE.md exists). Ask it to audit the
repo against `CLAUDE.md`, `docs/KALSHI_WEATHER_SPEC.md` and `docs/MARKETS.md`.
Connect Notion and GitHub under `/mcp` so the weekly status posts work.

## 7. Cloud routine

Delete the cloud routine "Kalshi weather daily brief" once cron runs locally,
or keep it as a backup. It pushes to `claude/new-session-uz9j48` on the old
repo, so repoint it (or recreate it) at `side-projects` `main`.

## Worth installing on WSL2

| tool | why |
|---|---|
| `git`, `gh` | GitHub CLI for PRs and issues from the shell |
| `uv` (in the env) | fast installs; pyproject extras |
| `direnv` | auto-load `.env` and activate the env per directory |
| `tmux` | keep the paper jobs and Claude sessions alive across terminal closes |
| `ripgrep`, `fd`, `jq` | Claude Code searches faster with them present |
| `duckdb` CLI | poke at `ledger/weather.duckdb` directly |
| Docker Desktop with WSL integration | PSF service container later |
| VS Code + WSL extension | edit in Windows, run in Linux |
| Windows Terminal | tabs per env |

Optional: `nvidia-smi` works inside WSL2 once the Windows NVIDIA driver is
installed; no Linux driver needed. That covers the learning env's CUDA build.
