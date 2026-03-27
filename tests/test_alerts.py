from __future__ import annotations

import json
from pathlib import Path

from last30free.alerts import build_alert_report_from_manifests
from last30free.reporting import write_run_outputs
from last30free.run_index import latest_run_for_topic, runs_for_topic, update_run_index


def build_payload(version: str) -> dict:
    if version == "earlier":
        items = [
            {
                "source": "reddit",
                "source_id": "r1",
                "url": "https://reddit.com/r1",
                "title": "Workflow-first AI coding setup",
                "text": "Workflow fit matters for editor integrations.",
                "author": "alice",
                "created_at": "2100-01-01T00:00:00Z",
                "score": 8.0,
                "metrics": {"upvotes": 100, "comments": 10, "likes": 0, "reposts": 0, "views": 0, "points": 0},
                "quotes": [],
                "tags": ["r/artificial"],
                "raw": {},
            }
        ]
    else:
        items = [
            {
                "source": "reddit",
                "source_id": "r1",
                "url": "https://reddit.com/r1",
                "title": "Workflow-first AI coding setup",
                "text": "Workflow fit matters for editor integrations and agent loops.",
                "author": "alice",
                "created_at": "2100-01-02T00:00:00Z",
                "score": 9.5,
                "metrics": {"upvotes": 140, "comments": 15, "likes": 0, "reposts": 0, "views": 0, "points": 0},
                "quotes": [],
                "tags": ["r/artificial"],
                "raw": {},
            },
            {
                "source": "youtube",
                "source_id": "y1",
                "url": "https://youtube.com/watch?v=y1",
                "title": "Best AI coding tools this week",
                "text": "Workflow and agent depth are improving quickly.",
                "author": "BuildWithAI",
                "created_at": "2100-01-02T00:00:00Z",
                "score": 8.8,
                "metrics": {"upvotes": 0, "comments": 0, "likes": 600, "reposts": 0, "views": 12000, "points": 0},
                "quotes": [],
                "tags": ["channel:BuildWithAI"],
                "raw": {"channel": "BuildWithAI"},
            },
            {
                "source": "youtube",
                "source_id": "y2",
                "url": "https://youtube.com/watch?v=y2",
                "title": "Agent workflow upgrades for AI coding",
                "text": "Workflow depth and agent control are the main themes.",
                "author": "BuildWithAI",
                "created_at": "2100-01-02T01:00:00Z",
                "score": 8.4,
                "metrics": {"upvotes": 0, "comments": 0, "likes": 550, "reposts": 0, "views": 11000, "points": 0},
                "quotes": [],
                "tags": ["channel:BuildWithAI"],
                "raw": {"channel": "BuildWithAI"},
            },
        ]

    return {
        "status": "ok",
        "message": f"{version} payload",
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
            "hn": {"status": "not_requested", "count": 0, "error": None},
            "youtube": {"status": "not_requested" if version == "earlier" else "ok", "count": 0 if version == "earlier" else 2, "error": None},
            "x": {"status": "not_requested", "count": 0, "error": None},
        },
        "merged": {
            "count": len(items),
            "items": items,
        },
        "synthesis": {
            "headline": f"{version} headline",
            "summary_points": [],
            "patterns": [],
            "source_stats": [],
            "source_status": {
                "reddit": {"status": "ok", "count": 1, "error": None},
                "hn": {"status": "not_requested", "count": 0, "error": None},
                "youtube": {"status": "not_requested" if version == "earlier" else "ok", "count": 0 if version == "earlier" else 2, "error": None},
                "x": {"status": "not_requested", "count": 0, "error": None},
            },
            "total_items": len(items),
            "sources_with_results": sorted({item["source"] for item in items}),
        },
    }


def test_alert_rules_fire_for_new_items_source_spike_and_keyword_spike(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    earlier_dir = output_dir / "20260324T120000Z_ai-coding-tools"
    later_dir = output_dir / "20260325T120000Z_ai-coding-tools"

    earlier_artifacts = write_run_outputs(
        run_dir=earlier_dir,
        payload=build_payload("earlier"),
        raw_query="latest ai coding tools",
        argv=["--save", "latest", "ai", "coding", "tools"],
    )
    later_artifacts = write_run_outputs(
        run_dir=later_dir,
        payload=build_payload("later"),
        raw_query="latest ai coding tools",
        argv=["--save", "latest", "ai", "coding", "tools"],
    )

    earlier_manifest = json.loads(Path(earlier_artifacts["manifest_path"]).read_text(encoding="utf-8"))
    later_manifest = json.loads(Path(later_artifacts["manifest_path"]).read_text(encoding="utf-8"))

    update_run_index(output_dir, earlier_manifest)
    update_run_index(output_dir, later_manifest)

    latest_entry = latest_run_for_topic(output_dir, "ai coding tools")
    assert latest_entry is not None
    assert latest_entry["run_id"] == "20260325T120000Z_ai-coding-tools"

    history = runs_for_topic(output_dir, "ai coding tools", limit=2)
    assert len(history) == 2

    report = build_alert_report_from_manifests(
        earlier_manifest,
        later_manifest,
        new_item_threshold=1,
        source_spike_threshold=1,
        keyword_spike_threshold=1,
    )

    assert report["status"] == "alerting"
    assert report["summary"]["triggered_rules"] >= 2

    rules = {rule["rule_id"]: rule for rule in report["rules"]}
    assert rules["new_item"]["triggered"] is True
    assert rules["source_spike"]["triggered"] is True
    assert rules["keyword_spike"]["triggered"] is True
