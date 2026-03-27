from __future__ import annotations

import json

from last30free.reporting import render_markdown_report, write_run_outputs


def build_payload() -> dict:
    return {
        "status": "ok",
        "message": "test payload",
        "intent": {
            "topic": "ai coding tools",
            "target_tool": "unknown",
            "query_type": "GENERAL",
        },
        "runtime": {
            "days": 30,
            "depth": "balanced",
            "limit_per_source": 25,
            "selected_sources": ["reddit", "hn", "youtube"],
            "implemented_selected_sources": ["reddit", "hn", "youtube"],
            "skipped_sources": [],
            "output_dir": "outputs",
            "cache_dir": "cache",
            "x_enabled": False,
            "x_configured": False,
        },
        "results": {
            "reddit": {"status": "ok", "count": 1, "error": None},
            "hn": {"status": "ok", "count": 1, "error": None},
            "youtube": {"status": "ok", "count": 1, "error": None},
            "x": {"status": "not_requested", "count": 0, "error": None},
        },
        "merged": {
            "count": 1,
            "items": [
                {
                    "source": "reddit",
                    "source_id": "abc123",
                    "url": "https://reddit.com/example",
                    "title": "Workflow-first AI coding setup",
                    "text": "People keep debating workflow fit.",
                    "author": "alice",
                    "created_at": "2100-01-01T00:00:00Z",
                    "score": 9.5,
                    "metrics": {"upvotes": 120, "comments": 18, "likes": 0, "reposts": 0, "views": 0, "points": 0},
                    "quotes": [{"text": "Workflow fit matters most.", "author": "bob", "source_label": "r/artificial"}],
                    "tags": ["r/artificial"],
                    "raw": {},
                }
            ],
        },
        "synthesis": {
            "headline": "Discussion on ai coding tools spans multiple sources.",
            "summary_points": ["r/artificial pushed workflow-first setups."],
            "patterns": [
                {
                    "keyword": "workflow",
                    "mentions": 3,
                    "source_count": 2,
                    "sources": ["reddit", "hn"],
                    "examples": ["Workflow-first AI coding setup"],
                }
            ],
            "source_stats": [
                {
                    "source": "reddit",
                    "count": 1,
                    "label_1": "upvotes",
                    "total_1": 120,
                    "label_2": "comments",
                    "total_2": 18,
                }
            ],
            "source_status": {
                "reddit": {"status": "ok", "count": 1, "error": None},
                "hn": {"status": "ok", "count": 1, "error": None},
                "youtube": {"status": "ok", "count": 1, "error": None},
                "x": {"status": "not_requested", "count": 0, "error": None},
            },
            "total_items": 1,
            "sources_with_results": ["reddit"],
        },
    }


def test_reporting_writes_markdown_manifest_and_payload(tmp_path) -> None:
    payload = build_payload()

    markdown = render_markdown_report(payload)
    assert "# last30free report" in markdown
    assert "## Key takeaways" in markdown
    assert "## Top merged discussions" in markdown

    artifacts = write_run_outputs(
        run_dir=tmp_path / "run_001",
        payload=payload,
        raw_query="latest ai coding tools",
        argv=["--save", "latest", "ai", "coding", "tools"],
    )

    assert (tmp_path / "run_001" / "report.md").exists()
    assert (tmp_path / "run_001" / "manifest.json").exists()
    assert (tmp_path / "run_001" / "merged_items.json").exists()
    assert (tmp_path / "run_001" / "run_payload.json").exists()

    manifest = json.loads((tmp_path / "run_001" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["raw_query"] == "latest ai coding tools"
    assert manifest["topic"] == "ai coding tools"
    assert manifest["counts"]["merged_items"] == 1
    assert artifacts["report_path"].endswith("report.md")
