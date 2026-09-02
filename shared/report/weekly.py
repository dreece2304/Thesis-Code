"""Build the Sunday status report: per project, done / blocked / next / questions."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

PROJECTS = [
    "investing", "prediction", "forecasting", "nanofab_saas", "materials", "learning", "audit",
]

WORD_LIMIT = 150


@dataclass
class Status:
    project: str
    done: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    next: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.project not in PROJECTS:
            raise ValueError(f"unknown project {self.project!r}; expected one of {PROJECTS}")

    def to_markdown(self, heading_level: int = 2) -> str:
        h = "#" * heading_level
        parts = [f"{h} {self.project}"]
        for label, items in (("Done", self.done), ("Blocked", self.blocked),
                             ("Next", self.next), ("Questions for Duncan", self.questions)):
            if items:
                parts.append(f"**{label}**")
                parts.extend(f"- {i}" for i in items)
        return "\n".join(parts) + "\n"

    def word_count(self) -> int:
        text = " ".join(self.done + self.blocked + self.next + self.questions)
        return len(re.findall(r"\S+", text))

    def over_limit(self) -> bool:
        return self.word_count() > WORD_LIMIT


def iso_week(d: date | datetime | None = None) -> str:
    d = d or date.today()
    y, w, _ = d.isocalendar()
    return f"{y}-{w:02d}"


def render_report(statuses: list[Status], week: str | None = None,
                  when: datetime | None = None) -> str:
    week = week or iso_week(when)
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M")
    out = [f"# Claude Code status, week {week}", f"_generated {stamp}_", ""]
    for s in statuses:
        out.append(s.to_markdown())
        if s.over_limit():
            out.append(f"> note: {s.project} status is {s.word_count()} words, over the {WORD_LIMIT} limit\n")
    return "\n".join(out)


def write_report(statuses: list[Status], reports_dir: str | Path = "reports",
                 when: datetime | None = None) -> Path:
    """Write (or append to) ``reports/YYYY-WW.md``. Returns the path."""
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{iso_week(when)}.md"
    text = render_report(statuses, when=when)
    if path.exists():
        with path.open("a", encoding="utf-8") as f:
            f.write("\n---\n\n" + text)
    else:
        path.write_text(text, encoding="utf-8")
    return path
