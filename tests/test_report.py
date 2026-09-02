from datetime import datetime

import pytest

from shared.report import Status, iso_week, publish, render_report, write_report
from shared.report.notion import status_blocks


def test_status_markdown_and_word_limit():
    s = Status("investing", done=["ported regimes"], next=["backtest"], questions=["ok to use QQQ?"])
    md = s.to_markdown()
    assert md.startswith("## investing") and "- ported regimes" in md and "Blocked" not in md
    assert s.word_count() == 7 and not s.over_limit()
    big = Status("audit", done=["word"] * 151)
    assert big.over_limit()
    with pytest.raises(ValueError):
        Status("not-a-project")


def test_iso_week_and_write_append(tmp_path):
    when = datetime(2026, 9, 6, 10, 0)  # Sunday of ISO week 36
    assert iso_week(when) == "2026-36"
    p = write_report([Status("audit", done=["scan"])], reports_dir=tmp_path, when=when)
    assert p.name == "2026-36.md"
    text = p.read_text()
    assert "# Claude Code status, week 2026-36" in text
    write_report([Status("audit", done=["again"])], reports_dir=tmp_path, when=when)
    text = p.read_text()
    assert text.count("# Claude Code status") == 2 and "\n---\n" in text
    assert render_report([Status("learning", done=["x"] * 200)], when=when).count("over the 150 limit") == 1


def test_publish_falls_back_to_file_without_notion(tmp_path):
    r = publish([Status("prediction", done=["fees"])], reports_dir=tmp_path, when=datetime(2026, 1, 5))
    assert r["file"].endswith("2026-02.md")
    assert r["notion"]["prediction"].startswith("skipped")


def test_notion_blocks_shape():
    blocks = status_blocks(Status("materials", done=["a", "b"], blocked=["c"]), "2026-36")
    assert blocks[0]["type"] == "heading_2"
    assert "Claude Code status" in blocks[0]["heading_2"]["rich_text"][0]["text"]["content"]
    types = [b["type"] for b in blocks]
    assert types == ["heading_2", "heading_3", "bulleted_list_item", "bulleted_list_item",
                     "heading_3", "bulleted_list_item"]
