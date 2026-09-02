"""Post status to Notion project pages.

Preferred route is the Notion MCP from a Claude Code session. This module is
the programmatic fallback: it uses the Notion REST API when ``NOTION_API_KEY``
and ``NOTION_PAGE_<PROJECT>`` are set, and always writes the Markdown file.
"""
from __future__ import annotations

import os
from pathlib import Path

from .weekly import Status, write_report

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def page_id_for(project: str) -> str | None:
    return os.environ.get(f"NOTION_PAGE_{project.upper()}") or None


def _rich(text: str) -> dict:
    return {"type": "text", "text": {"content": text[:2000]}}


def status_blocks(status: Status, week: str) -> list[dict]:
    """Notion block children for one project's status under a status heading."""
    blocks = [{"object": "block", "type": "heading_2",
               "heading_2": {"rich_text": [_rich(f"Claude Code status, week {week}")]}}]
    for label, items in (("Done", status.done), ("Blocked", status.blocked),
                         ("Next", status.next), ("Questions for Duncan", status.questions)):
        if not items:
            continue
        blocks.append({"object": "block", "type": "heading_3",
                       "heading_3": {"rich_text": [_rich(label)]}})
        for item in items:
            blocks.append({"object": "block", "type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": [_rich(item)]}})
    return blocks


def _append_blocks(page_id: str, blocks: list[dict], api_key: str) -> dict:
    import requests

    r = requests.patch(
        f"{NOTION_API}/blocks/{page_id}/children",
        headers={"Authorization": f"Bearer {api_key}", "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"},
        json={"children": blocks}, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def publish(statuses: list[Status], reports_dir: str | Path = "reports", when=None) -> dict:
    """Write the Markdown report and try Notion for each project.

    Returns ``{"file": path, "notion": {project: "posted" | "skipped: reason"}}``.
    """
    from .weekly import iso_week

    path = write_report(statuses, reports_dir=reports_dir, when=when)
    week = iso_week(when)
    api_key = os.environ.get("NOTION_API_KEY")
    result = {"file": str(path), "notion": {}}
    for s in statuses:
        page = page_id_for(s.project)
        if not api_key:
            result["notion"][s.project] = "skipped: NOTION_API_KEY not set"
        elif not page:
            result["notion"][s.project] = f"skipped: NOTION_PAGE_{s.project.upper()} not set"
        else:
            try:
                _append_blocks(page, status_blocks(s, week), api_key)
                result["notion"][s.project] = "posted"
            except Exception as e:  # network or auth; the file is the fallback
                result["notion"][s.project] = f"failed: {e}"
    return result
