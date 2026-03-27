from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from last30free.reporting import slugify


def notification_root(output_dir: Path) -> Path:
    return output_dir / "notifications"


def notification_index_path(output_dir: Path) -> Path:
    return output_dir / "notification_index.json"


def topic_key(value: str) -> str:
    return slugify(str(value or "").strip())


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_notification_index(output_dir: Path) -> dict[str, Any]:
    path = notification_index_path(output_dir)
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


def create_notification_snapshot_dir(output_dir: Path, topic: str) -> Path:
    key = topic_key(topic)
    snapshot_id = f"{utc_timestamp()}_{key}"
    root = notification_root(output_dir) / key
    snapshot_dir = root / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    return snapshot_dir


def build_notification_manifest(bundle: dict[str, Any], snapshot_dir: Path) -> dict[str, Any]:
    payloads = bundle.get("payloads", {})
    topic = str(bundle.get("topic", "") or "")
    key = topic_key(topic)
    snapshot_id = snapshot_dir.name

    files: dict[str, Any] = {
        "snapshot_dir": str(snapshot_dir),
        "bundle_path": str(snapshot_dir / "bundle.json"),
        "manifest_path": str(snapshot_dir / "manifest.json"),
    }

    if "email" in payloads:
        files["email_payload_path"] = str(snapshot_dir / "email_payload.json")
        files["email_body_path"] = str(snapshot_dir / "email_body.txt")

    if "webhook" in payloads:
        files["webhook_payload_path"] = str(snapshot_dir / "webhook_payload.json")

    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "topic_key": key,
        "status": bundle.get("status"),
        "channels": bundle.get("channels", []),
        "summary": bundle.get("summary", {}),
        "files": files,
    }


def build_notification_entry(manifest: dict[str, Any]) -> dict[str, Any]:
    files = manifest.get("files", {})
    summary = manifest.get("summary", {})

    return {
        "snapshot_id": manifest.get("snapshot_id"),
        "generated_at_utc": manifest.get("generated_at_utc"),
        "topic": manifest.get("topic"),
        "topic_key": manifest.get("topic_key"),
        "status": manifest.get("status"),
        "channels": manifest.get("channels", []),
        "triggered_rules": int(summary.get("triggered_rules", 0) or 0),
        "headline": str(summary.get("headline", "") or ""),
        "snapshot_dir": files.get("snapshot_dir"),
        "bundle_path": files.get("bundle_path"),
        "manifest_path": files.get("manifest_path"),
    }


def update_notification_index(output_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    payload = load_notification_index(output_dir)
    entry = build_notification_entry(manifest)

    existing_entries = [
        item
        for item in payload.get("entries", [])
        if str(item.get("snapshot_id", "")) != str(entry["snapshot_id"])
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

    path = notification_index_path(output_dir)
    path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
    return entry


def write_notification_bundle(output_dir: Path, bundle: dict[str, Any]) -> dict[str, Any]:
    topic = str(bundle.get("topic", "") or "unknown-topic")
    snapshot_dir = create_notification_snapshot_dir(output_dir, topic)
    manifest = build_notification_manifest(bundle, snapshot_dir)
    files = manifest["files"]

    bundle_path = Path(str(files["bundle_path"]))
    manifest_path = Path(str(files["manifest_path"]))

    bundle_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    payloads = bundle.get("payloads", {})

    if "email" in payloads:
        email_payload = payloads["email"]
        Path(str(files["email_payload_path"])).write_text(
            json.dumps(email_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        Path(str(files["email_body_path"])).write_text(
            str(email_payload.get("body_text", "") or ""),
            encoding="utf-8",
        )

    if "webhook" in payloads:
        webhook_payload = payloads["webhook"]
        Path(str(files["webhook_payload_path"])).write_text(
            json.dumps(webhook_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    index_entry = update_notification_index(output_dir, manifest)

    return {
        "snapshot_dir": str(snapshot_dir),
        "manifest_path": str(manifest_path),
        "bundle_path": str(bundle_path),
        "index_path": str(notification_index_path(output_dir)),
        "index_entry": index_entry,
        **files,
    }


def list_notification_snapshots(
    output_dir: Path,
    topic_ref: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    payload = load_notification_index(output_dir)
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        return []

    filtered = sorted(
        entries,
        key=lambda item: str(item.get("generated_at_utc") or ""),
        reverse=True,
    )

    if topic_ref:
        ref = str(topic_ref).strip()
        ref_key = topic_key(ref)

        exact_matches = []
        partial_matches = []

        for entry in filtered:
            topic = str(entry.get("topic", "") or "")
            key = str(entry.get("topic_key", "") or topic_key(topic))
            snapshot_id = str(entry.get("snapshot_id", "") or "")
            manifest_path = str(entry.get("manifest_path", "") or "")
            bundle_path = str(entry.get("bundle_path", "") or "")

            if ref in {topic, key, snapshot_id, manifest_path, bundle_path} or ref_key == key:
                exact_matches.append(entry)
                continue

            haystacks = [
                topic.lower(),
                key.lower(),
                snapshot_id.lower(),
                manifest_path.lower(),
                bundle_path.lower(),
            ]
            if any(ref.lower() in hay for hay in haystacks):
                partial_matches.append(entry)

        filtered = exact_matches if exact_matches else partial_matches

    if limit is None or limit <= 0:
        return filtered

    return filtered[:limit]
