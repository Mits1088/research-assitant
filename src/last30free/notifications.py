from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_notification_bundle(
    alert_report: dict[str, Any],
    *,
    channels: list[str] | None = None,
) -> dict[str, Any]:
    normalized_channels = normalize_channels(channels)
    summary = alert_report.get("summary", {})
    topic = str(alert_report.get("topic", "") or "unknown topic")
    status = str(alert_report.get("status", "") or "unknown")
    rules = alert_report.get("rules", []) or []

    triggered_rules = [rule for rule in rules if rule.get("triggered")]
    triggered_ids = [str(rule.get("rule_id", "")) for rule in triggered_rules]

    payloads: dict[str, Any] = {}
    if "email" in normalized_channels:
        payloads["email"] = build_email_payload(alert_report)
    if "webhook" in normalized_channels:
        payloads["webhook"] = build_webhook_payload(alert_report)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "status": status,
        "channels": normalized_channels,
        "summary": {
            "headline": str(summary.get("headline", "") or ""),
            "triggered_rules": int(summary.get("triggered_rules", 0) or 0),
            "evaluated_rules": int(summary.get("evaluated_rules", 0) or 0),
            "triggered_rule_ids": triggered_ids,
        },
        "payloads": payloads,
    }


def build_email_payload(alert_report: dict[str, Any]) -> dict[str, Any]:
    topic = str(alert_report.get("topic", "") or "unknown topic")
    summary = alert_report.get("summary", {})
    comparison = alert_report.get("comparison", {})
    earlier = comparison.get("earlier_run", {})
    later = comparison.get("later_run", {})
    rules = alert_report.get("rules", []) or []

    triggered_rules = [rule for rule in rules if rule.get("triggered")]
    status = str(alert_report.get("status", "") or "unknown")

    if status == "alerting":
        subject = f"[last30free] Alert: {topic} ({len(triggered_rules)} rule(s) triggered)"
    else:
        subject = f"[last30free] Clear: {topic}"

    lines: list[str] = []
    lines.append(str(summary.get("headline", "") or "").strip())
    lines.append("")
    lines.append(f"Topic: {topic}")
    lines.append(f"Earlier run: {earlier.get('run_id', '')} ({earlier.get('generated_at_utc', '')})")
    lines.append(f"Later run: {later.get('run_id', '')} ({later.get('generated_at_utc', '')})")
    lines.append("")

    if triggered_rules:
        lines.append("Triggered rules:")
        for rule in triggered_rules:
            lines.append(
                f"- {rule.get('rule_id', '')} [{rule.get('severity', '')}] — {rule.get('message', '')}"
            )
        lines.append("")
    else:
        lines.append("No rules triggered.")
        lines.append("")

    comparison_counts = comparison.get("counts", {})
    lines.append("Change counts:")
    lines.append(f"- Added items: {comparison_counts.get('added', 0)}")
    lines.append(f"- Removed items: {comparison_counts.get('removed', 0)}")
    lines.append(f"- Score changes: {comparison_counts.get('score_changed', 0)}")

    body_text = "\n".join(lines).strip()

    return {
        "subject": subject,
        "body_text": body_text,
        "body_markdown": body_text,
        "metadata": {
            "topic": topic,
            "status": status,
            "triggered_rules": [rule.get("rule_id", "") for rule in triggered_rules],
        },
    }


def build_webhook_payload(alert_report: dict[str, Any]) -> dict[str, Any]:
    summary = alert_report.get("summary", {})
    comparison = alert_report.get("comparison", {})
    earlier = comparison.get("earlier_run", {})
    later = comparison.get("later_run", {})
    rules = alert_report.get("rules", []) or []

    return {
        "event_type": "last30free.alert_report",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "topic": alert_report.get("topic", ""),
        "status": alert_report.get("status", ""),
        "headline": summary.get("headline", ""),
        "summary": {
            "triggered_rules": int(summary.get("triggered_rules", 0) or 0),
            "evaluated_rules": int(summary.get("evaluated_rules", 0) or 0),
        },
        "thresholds": alert_report.get("thresholds", {}),
        "runs": {
            "earlier": {
                "run_id": earlier.get("run_id", ""),
                "generated_at_utc": earlier.get("generated_at_utc", ""),
                "merged_items": earlier.get("merged_items", 0),
            },
            "later": {
                "run_id": later.get("run_id", ""),
                "generated_at_utc": later.get("generated_at_utc", ""),
                "merged_items": later.get("merged_items", 0),
            },
        },
        "rules": [
            {
                "rule_id": rule.get("rule_id", ""),
                "triggered": bool(rule.get("triggered", False)),
                "severity": rule.get("severity", ""),
                "message": rule.get("message", ""),
                "details": rule.get("details", {}),
            }
            for rule in rules
        ],
        "comparison_counts": comparison.get("counts", {}),
    }


def normalize_channels(channels: list[str] | None) -> list[str]:
    default = ["email", "webhook"]
    if not channels:
        return default

    normalized = []
    seen = set()

    for channel in channels:
        value = str(channel or "").strip().lower()
        if value not in {"email", "webhook"}:
            continue
        if value in seen:
            continue
        normalized.append(value)
        seen.add(value)

    return normalized or default
