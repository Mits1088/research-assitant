from __future__ import annotations

import json
from pathlib import Path

from last30free.cli import run_watchlist_entries
from last30free.config import load_settings
from last30free.watchlist import init_watchlist, load_watchlist, resolve_watch_topics


def test_watchlist_init_resolve_and_batch_run(monkeypatch, tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    monkeypatch.setenv("LAST30_OUTPUT_DIR", str(output_dir))

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
                "days": 30,
                "depth": "quick",
                "sources": ["reddit", "hn"],
                "target_tool": "unknown",
            },
        ],
    }
    path.write_text(json.dumps(watchlist_payload, indent=2), encoding="utf-8")

    selected = resolve_watch_topics(output_dir, refs=None, enabled_only=True)
    assert len(selected) == 2

    def fake_build_payload_for_query(*, raw_query, settings, days=None, tool=None, sources=None, quick=False, deep=False):
        return {
            "status": "ok",
            "message": "fake payload",
            "intent": {
                "topic": raw_query,
                "target_tool": tool or "unknown",
                "query_type": "GENERAL",
            },
            "runtime": {
                "days": days or 30,
                "depth": "quick" if quick else ("deep" if deep else "balanced"),
                "limit_per_source": 25,
                "selected_sources": sources or ["reddit", "hn", "youtube"],
                "implemented_selected_sources": sources or ["reddit", "hn", "youtube"],
                "skipped_sources": [],
                "output_dir": str(output_dir),
                "cache_dir": str(tmp_path / "cache"),
                "x_enabled": False,
                "x_configured": False,
            },
            "results": {
                "reddit": {"status": "ok", "count": 1, "error": None},
                "hn": {"status": "ok", "count": 1, "error": None},
                "youtube": {"status": "ok", "count": 0, "error": None},
                "x": {"status": "not_requested", "count": 0, "error": None},
            },
            "merged": {
                "count": 1,
                "items": [
                    {
                        "source": "reddit",
                        "source_id": raw_query.replace(" ", "-"),
                        "url": "https://reddit.com/example",
                        "title": raw_query,
                        "text": f"Discussion for {raw_query}",
                        "author": "alice",
                        "created_at": "2100-01-01T00:00:00Z",
                        "score": 9.0,
                        "metrics": {
                            "upvotes": 100,
                            "comments": 10,
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
                "headline": f"Headline for {raw_query}",
                "summary_points": [f"Summary for {raw_query}"],
                "patterns": [],
                "source_stats": [],
                "source_status": {
                    "reddit": {"status": "ok", "count": 1, "error": None},
                    "hn": {"status": "ok", "count": 1, "error": None},
                    "youtube": {"status": "ok", "count": 0, "error": None},
                    "x": {"status": "not_requested", "count": 0, "error": None},
                },
                "total_items": 1,
                "sources_with_results": ["reddit"],
            },
        }

    monkeypatch.setattr("last30free.orchestrator.build_payload_for_query", fake_build_payload_for_query)

    settings = load_settings()
    results = run_watchlist_entries(settings, selected, output_dir=output_dir)

    assert len(results) == 2
    assert all(row["status"] == "ok" for row in results)
    assert all(Path(row["report_path"]).exists() for row in results)
    assert (output_dir / "run_index.json").exists()
