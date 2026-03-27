from __future__ import annotations

import json
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from last30free.reporting import slugify

VALID_SOURCES = {"reddit", "hn", "youtube", "x"}
VALID_DEPTHS = {"quick", "balanced", "deep"}


def watchlist_path(output_dir: Path) -> Path:
    return output_dir / "watchlist.json"


def default_watchlist() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "updated_at_utc": None,
        "topics": [
            {
                "id": "latest-ai-coding-tools",
                "query": "latest AI coding tools",
                "target_tool": "unknown",
                "enabled": False,
                "days": 30,
                "depth": "balanced",
                "sources": ["reddit", "hn", "youtube"],
                "notes": "Example topic. Edit this file, add your own topics, and set enabled=true.",
            }
        ],
    }


def load_watchlist(output_dir: Path) -> dict[str, Any]:
    path = watchlist_path(output_dir)
    default = {"schema_version": "1.0", "updated_at_utc": None, "topics": []}

    if not path.exists():
        return default

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default

    if not isinstance(payload, dict):
        return default

    topics = payload.get("topics", [])
    if not isinstance(topics, list):
        topics = []

    normalized_topics = [
        normalize_watch_topic(topic, index=idx)
        for idx, topic in enumerate(topics)
        if isinstance(topic, dict)
    ]

    return {
        "schema_version": str(payload.get("schema_version") or "1.0"),
        "updated_at_utc": payload.get("updated_at_utc"),
        "topics": normalized_topics,
    }


def save_watchlist(output_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = watchlist_path(output_dir)

    topics = payload.get("topics", [])
    if not isinstance(topics, list):
        topics = []

    normalized_topics = [
        normalize_watch_topic(topic, index=idx)
        for idx, topic in enumerate(topics)
        if isinstance(topic, dict)
    ]

    saved = {
        "schema_version": "1.0",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "topics": normalized_topics,
    }

    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return saved


def init_watchlist(output_dir: Path, *, overwrite: bool = False) -> tuple[Path, bool]:
    path = watchlist_path(output_dir)

    if path.exists() and not overwrite:
        return path, False

    save_watchlist(output_dir, default_watchlist())
    return path, True


def list_watch_topics(output_dir: Path, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    payload = load_watchlist(output_dir)
    topics = payload.get("topics", [])
    if not isinstance(topics, list):
        return []

    if enabled_only:
        return [topic for topic in topics if bool(topic.get("enabled", False))]
    return topics


def resolve_watch_topics(
    output_dir: Path,
    refs: list[str] | None = None,
    *,
    enabled_only: bool = True,
) -> list[dict[str, Any]]:
    topics = list_watch_topics(output_dir, enabled_only=enabled_only)
    if not refs:
        return topics

    resolved: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for ref in refs:
        needle = str(ref).strip()
        if not needle:
            continue

        exact_matches = []
        partial_matches = []

        for topic in topics:
            topic_id = str(topic.get("id", "") or "")
            query = str(topic.get("query", "") or "")
            notes = str(topic.get("notes", "") or "")

            if needle in {topic_id, query}:
                exact_matches.append(topic)
                continue

            haystacks = [topic_id.lower(), query.lower(), notes.lower()]
            if any(needle.lower() in hay for hay in haystacks):
                partial_matches.append(topic)

        chosen = exact_matches[0] if exact_matches else (partial_matches[0] if partial_matches else None)
        if chosen is None:
            continue

        topic_id = str(chosen.get("id", "") or "")
        if topic_id in seen_ids:
            continue

        resolved.append(chosen)
        seen_ids.add(topic_id)

    return resolved


def build_watchlist_runner_payloads(
    output_dir: Path,
    refs: list[str] | None = None,
    *,
    enabled_only: bool = True,
) -> list[dict[str, Any]]:
    topics = resolve_watch_topics(output_dir, refs=refs, enabled_only=enabled_only)
    payloads = []

    for topic in topics:
        argv = build_watch_topic_argv(topic)
        payloads.append(
            {
                "topic_id": topic["id"],
                "query": topic["query"],
                "target_tool": topic["target_tool"],
                "enabled": topic["enabled"],
                "days": topic["days"],
                "depth": topic["depth"],
                "sources": topic["sources"],
                "notes": topic["notes"],
                "watchlist_path": str(watchlist_path(output_dir)),
                "command_argv": argv,
                "command_string": shlex.join(argv),
                "scheduler_hint": "Execute this argv list from cron, a shell script, CI, or another task runner.",
            }
        )

    return payloads


def build_watch_topic_argv(topic: dict[str, Any]) -> list[str]:
    argv = ["last30free", "--save"]

    days = int(topic.get("days", 30) or 30)
    argv.extend(["--days", str(days)])

    depth = str(topic.get("depth", "balanced") or "balanced").strip().lower()
    if depth == "quick":
        argv.append("--quick")
    elif depth == "deep":
        argv.append("--deep")

    target_tool = str(topic.get("target_tool", "unknown") or "unknown").strip()
    if target_tool and target_tool != "unknown":
        argv.extend(["--tool", target_tool])

    for source in topic.get("sources", []) or []:
        argv.extend(["--source", str(source)])

    argv.append(str(topic.get("query", "") or ""))
    return argv


def normalize_watch_topic(topic: dict[str, Any], *, index: int = 0) -> dict[str, Any]:
    query = str(topic.get("query", "") or "").strip()
    topic_id = str(topic.get("id", "") or "").strip() or slugify(query) or f"topic-{index + 1}"

    depth = str(topic.get("depth", "balanced") or "balanced").strip().lower()
    if depth not in VALID_DEPTHS:
        depth = "balanced"

    try:
        days = int(topic.get("days", 30) or 30)
    except (TypeError, ValueError):
        days = 30
    days = max(1, days)

    raw_sources = topic.get("sources", ["reddit", "hn", "youtube"])
    if not isinstance(raw_sources, list):
        raw_sources = ["reddit", "hn", "youtube"]

    normalized_sources = []
    seen_sources = set()
    for source in raw_sources:
        value = str(source).strip().lower()
        if value in VALID_SOURCES and value not in seen_sources:
            normalized_sources.append(value)
            seen_sources.add(value)

    if not normalized_sources:
        normalized_sources = ["reddit", "hn", "youtube"]

    return {
        "id": topic_id,
        "query": query,
        "target_tool": str(topic.get("target_tool", "unknown") or "unknown").strip() or "unknown",
        "enabled": bool(topic.get("enabled", False)),
        "days": days,
        "depth": depth,
        "sources": normalized_sources,
        "notes": str(topic.get("notes", "") or "").strip(),
    }
