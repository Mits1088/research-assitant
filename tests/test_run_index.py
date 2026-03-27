from __future__ import annotations

import json
from pathlib import Path

from last30free.reporting import write_run_outputs
from last30free.run_index import index_path, list_saved_runs, resolve_saved_run, update_run_index


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


def test_run_index_updates_lists_and_resolves_saved_runs(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    run_dir = output_dir / "20260324T120000Z_ai-coding-tools"

    artifacts = write_run_outputs(
        run_dir=run_dir,
        payload=build_payload(),
        raw_query="latest ai coding tools",
        argv=["--save", "latest", "ai", "coding", "tools"],
    )

    manifest = json.loads(Path(artifacts["manifest_path"]).read_text(encoding="utf-8"))
    entry = update_run_index(output_dir, manifest)

    assert entry["run_id"] == "20260324T120000Z_ai-coding-tools"
    assert index_path(output_dir).exists()

    entries = list_saved_runs(output_dir)
    assert len(entries) == 1
    assert entries[0]["topic"] == "ai coding tools"

    resolved = resolve_saved_run(output_dir, "20260324T120000Z_ai-coding-tools")
    assert resolved is not None
    assert resolved["topic"] == "ai coding tools"

    resolved_by_topic = resolve_saved_run(output_dir, "coding tools")
    assert resolved_by_topic is not None
    assert resolved_by_topic["run_id"] == "20260324T120000Z_ai-coding-tools"
