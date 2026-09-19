#!/usr/bin/env bash
# Turn the claude/new-session-uz9j48 branch of Thesis-Code into a clean side-projects repo.
# Run inside WSL from the directory that should contain the new repo. Needs git-filter-repo.
#   bash scripts/migrate_to_side_projects.sh git@github.com:dreece2304/side-projects.git
set -euo pipefail
NEW_REMOTE="${1:?new remote url}"
SRC="https://github.com/dreece2304/Thesis-Code.git"
git clone -b claude/new-session-uz9j48 --single-branch "$SRC" side-projects
cd side-projects
git remote remove origin
# Drop the 2018 MATLAB thesis files and their 100 MB of .mat history from every commit.
git filter-repo --invert-paths --path-glob '*.m' --path-glob '*.mat' --force
git checkout -b main
git remote add origin "$NEW_REMOTE"
git push -u origin main
echo "done: $(git rev-list --count HEAD) commits, $(du -sh .git | cut -f1) history"
