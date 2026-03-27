from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from last30free.reporting import slugify


def index_path(output_dir: Path) -> Path:
    return output_dir / "run_index.json"


def topic_key(value: str) -> str:
    return slugify(str(value or "").strip())


def load_run_index(output_dir: Path) -> dict[str, Any]:
    path = index_path(output_dir)
    default = {
        "schema_version": "1.0",
        "updated_at_utc": None,
        "entries": [],
    }

    if not path.exists():
        return default

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default

    if not isinstance(payload, dict):
        return default

    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        entries = []

    return {
        "schema_version": str(payload.get("schema_version") or "1.0"),
        "updated_at_utc": payload.get("updated_at_utc"),
        "entries": entries,
    }


def build_index_entry(manifest: dict[str, Any]) -> dict[str, Any]:
    files = manifest.get("files", {})
    run_dir = Path(str(files.get("run_dir", "") or ""))
    runtime = manifest.get("runtime", {})
    counts = manifest.get("counts", {})

    topic = str(manifest.get("topic", "") or "")
    key = topic_key(topic)

    return {
        "run_id": manifest.get("run_id") or run_dir.name,
        "generated_at_utc": manifest.get("generated_at_utc"),
        "topic": topic,
        "topic_key": key,
        "target_tool": manifest.get("target_tool"),
        "query_type": manifest.get("query_type"),
        "status": manifest.get("status"),
        "merged_items": counts.get("merged_items", 0),
        "selected_sources": runtime.get("selected_sources", []),
        "report_path": files.get("report_path"),
        "manifest_path": files.get("manifest_path"),
        "run_dir": files.get("run_dir"),
    }


def update_run_index(output_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    payload = load_run_index(output_dir)
    entry = build_index_entry(manifest)

    existing_entries = [
        item
        for item in payload.get("entries", [])
        if str(item.get("run_id", "")) != str(entry["run_id"])
    ]
    existing_entries.append(entry)
    existing_entries.sort(
        key=lambda item: str(item.get("generated_at_utc") or ""),
        reverse=True,
    )

    updated = {
        "schema_version": "1.0",
        "updated_at_utc": manifest.get("generated_at_utc"),
        "entries": existing_entries,
    }

    path = index_path(output_dir)
    path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
    return entry


def list_saved_runs(output_dir: Path, limit: int | None = None) -> list[dict[str, Any]]:
    payload = load_run_index(output_dir)
    entries = payload.get("entries", [])

    if not isinstance(entries, list):
        return []

    sorted_entries = sorted(
        entries,
        key=lambda item: str(item.get("generated_at_utc") or ""),
        reverse=True,
    )

    if limit is None or limit <= 0:
        return sorted_entries

    return sorted_entries[:limit]


def runs_for_topic(output_dir: Path, topic_ref: str, limit: int | None = None) -> list[dict[str, Any]]:
    ref = str(topic_ref).strip()
    if not ref:
        return []

    entries = list_saved_runs(output_dir, limit=None)
    if not entries:
        return []

    ref_key = topic_key(ref)
    exact_matches = []
    partial_matches = []

    for entry in entries:
        run_id = str(entry.get("run_id", "") or "")
        topic = str(entry.get("topic", "") or "")
        key = str(entry.get("topic_key", "") or topic_key(topic))
        manifest_path = str(entry.get("manifest_path", "") or "")
        report_path = str(entry.get("report_path", "") or "")

        if ref in {run_id, topic, key, manifest_path, report_path} or ref_key == key:
            exact_matches.append(entry)
            continue

        haystacks = [
            run_id.lower(),
            topic.lower(),
            key.lower(),
            manifest_path.lower(),
            report_path.lower(),
        ]
        if any(ref.lower() in hay for hay in haystacks):
            partial_matches.append(entry)

    chosen = exact_matches if exact_matches else partial_matches
    chosen = sorted(
        chosen,
        key=lambda item: str(item.get("generated_at_utc") or ""),
        reverse=True,
    )

    if limit is None or limit <= 0:
        return chosen

    return chosen[:limit]


def latest_runs_by_topic(output_dir: Path, limit: int | None = None) -> list[dict[str, Any]]:
    entries = list_saved_runs(output_dir, limit=None)
    latest: dict[str, dict[str, Any]] = {}

    for entry in entries:
        key = str(entry.get("topic_key", "") or topic_key(str(entry.get("topic", "") or "")))
        if not key:
            continue
        if key not in latest:
            latest[key] = entry

    values = sorted(
        latest.values(),
        key=lambda item: str(item.get("generated_at_utc") or ""),
        reverse=True,
    )

    if limit is None or limit <= 0:
        return values

    return values[:limit]


def latest_run_for_topic(output_dir: Path, topic_ref: str) -> dict[str, Any] | None:
    matches = runs_for_topic(output_dir, topic_ref, limit=1)
    return matches[0] if matches else None


def read_manifest(manifest_path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def resolve_saved_run(output_dir: Path, run_ref: str) -> dict[str, Any] | None:
    ref = str(run_ref).strip()
    if not ref:
        return None

    direct_path = Path(ref)
    if direct_path.exists():
        manifest_path = direct_path / "manifest.json" if direct_path.is_dir() else direct_path
        return read_manifest(manifest_path)

    entries = list_saved_runs(output_dir, limit=None)
    if not entries:
        return None

    exact_matches = []
    partial_matches = []

    for entry in entries:
        run_id = str(entry.get("run_id", "") or "")
        topic = str(entry.get("topic", "") or "")
        key = str(entry.get("topic_key", "") or topic_key(topic))
        manifest_path_str = str(entry.get("manifest_path", "") or "")
        report_path_str = str(entry.get("report_path", "") or "")

        if ref in {run_id, topic, key, manifest_path_str, report_path_str}:
            exact_matches.append(entry)
            continue

        haystacks = [
            run_id.lower(),
            topic.lower(),
            key.lower(),
            manifest_path_str.lower(),
            report_path_str.lower(),
        ]
        if any(ref.lower() in hay for hay in haystacks):
            partial_matches.append(entry)

    chosen = exact_matches[0] if exact_matches else (partial_matches[0] if partial_matches else None)
    if chosen is None:
        return None

    manifest_path = Path(str(chosen.get("manifest_path", "") or ""))
    if not manifest_path.exists():
        return None

    return read_manifest(manifest_path)
