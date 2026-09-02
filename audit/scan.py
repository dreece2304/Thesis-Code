"""Scan directories for projects and write an inventory.

Run this inside WSL (Claude Code on the web cannot see the WSL home dir):

    python -m audit.scan ~ ~/projects --out audit/inventory.json --md audit/INVENTORY.md

For each project root found it records language mix, last modified date,
dependency manifests, Geant4 markers (to locate the PhD PSF code) and hits on
employer-related terms (to flag anything that must stay out of this repo).
It never reads file contents beyond small manifests and a bounded grep.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT_MARKERS = (
    ".git", "pyproject.toml", "setup.py", "package.json", "CMakeLists.txt",
    "Cargo.toml", "environment.yml", "requirements.txt", "Makefile", "go.mod",
)
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "build", "dist",
    ".cache", ".mypy_cache", ".pytest_cache", "site-packages", ".conda", "miniforge3",
    "mambaforge", "anaconda3", ".npm", ".cargo", ".rustup", "snap", ".local",
}
LANG_BY_EXT = {
    ".py": "python", ".ipynb": "notebook", ".m": "matlab", ".cc": "c++", ".cpp": "c++",
    ".cxx": "c++", ".hh": "c++", ".h": "c/c++", ".c": "c", ".js": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript", ".rs": "rust",
    ".go": "go", ".jl": "julia", ".r": "r", ".sh": "shell", ".mac": "geant4-macro",
    ".f90": "fortran", ".f": "fortran", ".java": "java", ".cs": "c#", ".sql": "sql",
}
GEANT4_PATTERNS = re.compile(r"G4RunManager|G4VUserDetectorConstruction|G4VUserPrimaryGeneratorAction|find_package\(Geant4", re.I)
PSF_PATTERNS = re.compile(r"point.?spread|\bPSF\b|proximity|radial.*energy|energy.*radial", re.I)
DEFAULT_FLAG_TERMS = ("fab2", "atomic semi", "atomicsemi")
GREP_EXTS = {".py", ".cc", ".cpp", ".hh", ".h", ".txt", ".md", ".mac", ".m", ".ipynb", ".toml", ".yml", ".yaml", ".json"}
MAX_GREP_BYTES = 200_000
MAX_GREP_FILES = 400


def is_project_root(d: Path) -> bool:
    if any((d / m).exists() for m in ROOT_MARKERS):
        return True
    try:
        mfiles = sum(1 for p in d.iterdir() if p.suffix == ".m")
    except PermissionError:
        return False
    return mfiles >= 3


def find_projects(roots: list[Path], max_depth: int = 4) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        root = root.expanduser().resolve()
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            if d.name in SKIP_DIRS:
                continue
            if d != root and is_project_root(d):
                found.append(d)
                continue  # do not descend into a project
            if depth >= max_depth:
                continue
            try:
                for child in sorted(d.iterdir()):
                    if child.is_dir() and not child.is_symlink():
                        stack.append((child, depth + 1))
            except PermissionError:
                continue
        if is_project_root(root):
            found.append(root)
    return sorted(set(found))


def _walk_files(project: Path):
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
        for f in filenames:
            yield Path(dirpath) / f


def _read_head(p: Path, n: int = MAX_GREP_BYTES) -> str:
    try:
        with p.open("rb") as fh:
            return fh.read(n).decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _deps(project: Path) -> dict:
    deps: dict[str, list[str]] = {}
    req = project / "requirements.txt"
    if req.exists():
        deps["requirements.txt"] = [
            re.split(r"[=<>!~\[ ]", ln.strip())[0] for ln in _read_head(req).splitlines()
            if ln.strip() and not ln.startswith("#")
        ][:40]
    py = project / "pyproject.toml"
    if py.exists():
        text = _read_head(py)
        m = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
        deps["pyproject.toml"] = re.findall(r'"([A-Za-z0-9_.-]+)', m.group(1))[:40] if m else []
    env = project / "environment.yml"
    if env.exists():
        deps["environment.yml"] = [
            ln.strip("- ").split("=")[0] for ln in _read_head(env).splitlines()
            if ln.strip().startswith("-") and ":" not in ln
        ][:40]
    pkg = project / "package.json"
    if pkg.exists():
        try:
            js = json.loads(_read_head(pkg))
            deps["package.json"] = sorted({**js.get("dependencies", {}), **js.get("devDependencies", {})})[:40]
        except json.JSONDecodeError:
            deps["package.json"] = []
    cm = project / "CMakeLists.txt"
    if cm.exists():
        deps["CMakeLists.txt"] = re.findall(r"find_package\((\w+)", _read_head(cm))[:40]
    return deps


def _readme_line(project: Path) -> str:
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = project / name
        if p.exists():
            for ln in _read_head(p, 4000).splitlines():
                ln = ln.strip().lstrip("#").strip()
                if ln:
                    return ln[:200]
    return ""


def scan_project(project: Path, flag_terms=DEFAULT_FLAG_TERMS) -> dict:
    langs: dict[str, int] = {}
    n_files = 0
    size = 0
    last = 0.0
    geant4 = False
    psf_hits: list[str] = []
    flag_hits: list[str] = []
    grepped = 0
    flag_re = re.compile("|".join(re.escape(t) for t in flag_terms), re.I) if flag_terms else None
    for p in _walk_files(project):
        try:
            st = p.stat()
        except OSError:
            continue
        n_files += 1
        size += st.st_size
        last = max(last, st.st_mtime)
        lang = LANG_BY_EXT.get(p.suffix.lower())
        if lang:
            langs[lang] = langs.get(lang, 0) + 1
        if p.suffix.lower() in GREP_EXTS and grepped < MAX_GREP_FILES:
            grepped += 1
            text = _read_head(p)
            rel = str(p.relative_to(project))
            if GEANT4_PATTERNS.search(text):
                geant4 = True
            if PSF_PATTERNS.search(text) and len(psf_hits) < 10:
                psf_hits.append(rel)
            if flag_re and flag_re.search(text) and len(flag_hits) < 10:
                flag_hits.append(rel)
    return {
        "name": project.name,
        "path": str(project),
        "git": (project / ".git").exists(),
        "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])),
        "primary_language": max(langs, key=langs.get) if langs else "unknown",
        "n_files": n_files,
        "size_mb": round(size / 1e6, 1),
        "last_modified": datetime.fromtimestamp(last).date().isoformat() if last else None,
        "dependencies": _deps(project),
        "readme": _readme_line(project),
        "geant4": geant4,
        "psf_hits": psf_hits,
        "flag_hits": flag_hits,
        # Filled in by hand during the audit.
        "runs": "unknown",
        "saas_score": {"recurring_problem": None, "paying_for_worse": None,
                       "reachable_buyer": None, "clean_ip": None},
        "notes": "",
    }


def to_markdown(inventory: list[dict]) -> str:
    lines = ["| project | language | files | MB | last modified | git | Geant4 | flags | readme |",
             "|---|---|---:|---:|---|---|---|---|---|"]
    for it in inventory:
        flags = "EMPLOYER?" if it["flag_hits"] else ""
        lines.append(
            f"| {it['name']} | {it['primary_language']} | {it['n_files']} | {it['size_mb']} | "
            f"{it['last_modified'] or ''} | {'y' if it['git'] else ''} | {'y' if it['geant4'] else ''} | "
            f"{flags} | {it['readme'].replace('|', '/')} |"
        )
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roots", nargs="+", help="directories to scan")
    ap.add_argument("--out", default="audit/inventory.json")
    ap.add_argument("--md", default="audit/INVENTORY.md")
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--flag-terms", default=",".join(DEFAULT_FLAG_TERMS),
                    help="comma-separated terms whose presence flags employer material")
    a = ap.parse_args(argv)
    terms = tuple(t.strip() for t in a.flag_terms.split(",") if t.strip())
    projects = find_projects([Path(r) for r in a.roots], a.max_depth)
    inventory = [scan_project(p, terms) for p in projects]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(inventory, indent=2))
    Path(a.md).write_text(to_markdown(inventory))
    print(f"{len(inventory)} projects -> {a.out}, {a.md}", file=sys.stderr)
    for it in inventory:
        if it["geant4"]:
            print(f"Geant4 project: {it['path']}", file=sys.stderr)
        if it["flag_hits"]:
            print(f"FLAG (employer terms): {it['path']} {it['flag_hits'][:3]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
