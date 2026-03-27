from __future__ import annotations

import json
from pathlib import Path

from last30free.reporting import write_run_outputs
from last30free.run_index import latest_run_for_topic, latest_runs_by_topic, update_run_index
from last30free.watchlist import build_watchlist_runner_payloads, init_watchlist


def build_payload(topic: str, score: float) -> dict:
    return {
        "status": "ok",
        "message": "test payload",
        "intent": {
            "topic": topic,
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
            "hn": {"status": "ok", "count": 0, "error": None},
            "youtube": {"status": "ok", "count": 0, "error": None},
            "x": {"status": "not_requested", "count": 0, "error": None},
        },
        "merged": {
            "count": 1,
            "items": [
                {
                    "source": "reddit",
                    "source_id": topic.replace(" ", "-"),
                    "url": "https://reddit.com/example",
                    "title": topic,
                    "text": f"Discussion for {topic}",
                    "author": "alice",
                    "created_at": "2100-01-01T00:00:00Z",
                    "score": score,
                    "metrics": {
                        "upvotes": 120,
                        "comments": 18,
                        "likes": 0,
                        "reposts": 0,
                        "views": 0,
                        "points": 0,
                    },
                    "quotes": [],
                    "tags": ["r/artificial"],
                    "raw": {},
                }
            ],
        },
        "synthesis": {
            "headline": f"Discussion on {topic}.",
            "summary_points": [f"Summary for {topic}"],
            "patterns": [],
            "source_stats": [],
            "source_status": {
                "reddit": {"status": "ok", "count": 1, "error": None},
                "hn": {"status": "ok", "count": 0, "error": None},
                "youtube": {"status": "ok", "count": 0, "error": None},
                "x": {"status": "not_requested", "count": 0, "error": None},
            },
            "total_items": 1,
            "sources_with_results": ["reddit"],
        },
    }


def test_latest_lookup_and_watch_payload_builder(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    earlier_dir = output_dir / "20260324T120000Z_ai-coding-tools"
    later_dir = output_dir / "20260325T120000Z_ai-coding-tools"
    other_dir = output_dir / "20260325T130000Z_project-management-tools"

    earlier_artifacts = write_run_outputs(
        run_dir=earlier_dir,
        payload=build_payload("ai coding tools", 8.0),
        raw_query="latest ai coding tools",
        argv=["--save", "latest", "ai", "coding", "tools"],
    )
    later_artifacts = write_run_outputs(
        run_dir=later_dir,
        payload=build_payload("ai coding tools", 9.0),
        raw_query="latest ai coding tools",
        argv=["--save", "latest", "ai", "coding", "tools"],
    )
    other_artifacts = write_run_outputs(
        run_dir=other_dir,
        payload=build_payload("project management tools", 7.0),
        raw_query="best project management tools",
        argv=["--save", "best", "project", "management", "tools"],
    )

    for artifacts in (earlier_artifacts, later_artifacts, other_artifacts):
        manifest = json.loads(Path(artifacts["manifest_path"]).read_text(encoding="utf-8"))
        update_run_index(output_dir, manifest)

    latest_entries = latest_runs_by_topic(output_dir)
    assert len(latest_entries) == 2
    assert any(entry["topic"] == "ai coding tools" for entry in latest_entries)
    assert any(entry["topic"] == "project management tools" for entry in latest_entries)

    latest_ai = latest_run_for_topic(output_dir, "ai coding tools")
    assert latest_ai is not None
    assert latest_ai["run_id"] == "20260325T120000Z_ai-coding-tools"

    path, created = init_watchlist(output_dir, overwrite=True)
    assert created is True
    assert path.exists()

    watchlist_payload = {
        "schema_version": "1.0",
        "updated_at_utc": None,
        "topics": [
            {
                "id": "ai-coding-tools",
                "query": "latest AI coding tools",
                "enabled": True,
                "days": 30,
                "depth": "balanced",
                "sources": ["reddit", "hn", "youtube"],
                "target_tool": "unknown",
            },
            {
                "id": "project-management-tools",
                "query": "best project management tools",
                "enabled": True,
                "days": 14,
                "depth": "quick",
                "sources": ["reddit", "hn"],
                "target_tool": "unknown",
            },
        ],
    }
    path.write_text(json.dumps(watchlist_payload, indent=2), encoding="utf-8")

    payloads = build_watchlist_runner_payloads(output_dir, refs=["ai-coding"], enabled_only=True)
    assert len(payloads) == 1
    assert payloads[0]["topic_id"] == "ai-coding-tools"
    assert payloads[0]["command_argv"][0] == "last30free"
    assert "--save" in payloads[0]["command_argv"]
    assert "--days" in payloads[0]["command_argv"]
    assert "--source" in payloads[0]["command_argv"]
    assert "latest AI coding tools" in payloads[0]["command_string"]
