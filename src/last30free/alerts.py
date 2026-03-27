from __future__ import annotations

from typing import Any

from last30free.comparison import compare_payloads, load_payload_from_manifest


def build_alert_report_from_manifests(
    earlier_manifest: dict[str, Any],
    later_manifest: dict[str, Any],
    *,
    new_item_threshold: int = 1,
    source_spike_threshold: int = 2,
    keyword_spike_threshold: int = 2,
) -> dict[str, Any]:
    earlier_payload = load_payload_from_manifest(earlier_manifest)
    later_payload = load_payload_from_manifest(later_manifest)

    if earlier_payload is None or later_payload is None:
        raise ValueError("One or both manifests are missing readable payload files")

    comparison = compare_payloads(
        earlier_payload,
        later_payload,
        earlier_manifest=earlier_manifest,
        later_manifest=later_manifest,
    )

    return evaluate_alerts(
        comparison,
        new_item_threshold=new_item_threshold,
        source_spike_threshold=source_spike_threshold,
        keyword_spike_threshold=keyword_spike_threshold,
    )


def evaluate_alerts(
    comparison: dict[str, Any],
    *,
    new_item_threshold: int = 1,
    source_spike_threshold: int = 2,
    keyword_spike_threshold: int = 2,
) -> dict[str, Any]:
    topic = (
        str(comparison.get("later_run", {}).get("topic", "") or "")
        or str(comparison.get("earlier_run", {}).get("topic", "") or "")
    )

    added_count = int(comparison.get("counts", {}).get("added", 0) or 0)
    added_items = comparison.get("added_items", []) or []

    source_matches = [
        row
        for row in comparison.get("source_counts", []) or []
        if int(row.get("delta", 0) or 0) >= new_threshold(source_spike_threshold)
    ]

    keyword_matches = [
        row
        for row in comparison.get("keyword_changes", []) or []
        if int(row.get("delta", 0) or 0) >= new_threshold(keyword_spike_threshold)
    ]

    rules = []

    new_item_triggered = added_count >= new_threshold(new_item_threshold)
    rules.append(
        {
            "rule_id": "new_item",
            "triggered": new_item_triggered,
            "severity": severity_from_count(added_count) if new_item_triggered else "none",
            "message": (
                f"{added_count} new item(s) appeared in the later run."
                if new_item_triggered
                else f"No new-item alert. Threshold: {new_threshold(new_item_threshold)}."
            ),
            "details": {
                "threshold": new_threshold(new_item_threshold),
                "added_count": added_count,
                "items": added_items[:5],
            },
        }
    )

    source_spike_triggered = len(source_matches) > 0
    rules.append(
        {
            "rule_id": "source_spike",
            "triggered": source_spike_triggered,
            "severity": severity_from_count(max((row["delta"] for row in source_matches), default=0))
            if source_spike_triggered
            else "none",
            "message": (
                "Source spike detected: "
                + ", ".join(f"{row['source']} ({row['delta']:+d})" for row in source_matches[:5])
                if source_spike_triggered
                else f"No source spike alert. Threshold: {new_threshold(source_spike_threshold)}."
            ),
            "details": {
                "threshold": new_threshold(source_spike_threshold),
                "matches": source_matches[:10],
            },
        }
    )

    keyword_spike_triggered = len(keyword_matches) > 0
    rules.append(
        {
            "rule_id": "keyword_spike",
            "triggered": keyword_spike_triggered,
            "severity": severity_from_count(max((row["delta"] for row in keyword_matches), default=0))
            if keyword_spike_triggered
            else "none",
            "message": (
                "Keyword spike detected: "
                + ", ".join(f"{row['keyword']} ({row['delta']:+d})" for row in keyword_matches[:5])
                if keyword_spike_triggered
                else f"No keyword spike alert. Threshold: {new_threshold(keyword_spike_threshold)}."
            ),
            "details": {
                "threshold": new_threshold(keyword_spike_threshold),
                "matches": keyword_matches[:10],
            },
        }
    )

    triggered_rules = [rule for rule in rules if rule["triggered"]]
    status = "alerting" if triggered_rules else "clear"

    if triggered_rules:
        headline = (
            f"{len(triggered_rules)} alert rule(s) fired for {topic or 'this topic'} "
            f"between {comparison.get('earlier_run', {}).get('run_id', '')} and "
            f"{comparison.get('later_run', {}).get('run_id', '')}."
        )
    else:
        headline = (
            f"No alert rules fired for {topic or 'this topic'} between "
            f"{comparison.get('earlier_run', {}).get('run_id', '')} and "
            f"{comparison.get('later_run', {}).get('run_id', '')}."
        )

    return {
        "topic": topic,
        "status": status,
        "summary": {
            "headline": headline,
            "triggered_rules": len(triggered_rules),
            "evaluated_rules": len(rules),
        },
        "thresholds": {
            "new_item_threshold": new_threshold(new_item_threshold),
            "source_spike_threshold": new_threshold(source_spike_threshold),
            "keyword_spike_threshold": new_threshold(keyword_spike_threshold),
        },
        "rules": rules,
        "comparison": comparison,
    }


def severity_from_count(value: int) -> str:
    if value >= 5:
        return "high"
    if value >= 3:
        return "medium"
    if value >= 1:
        return "low"
    return "none"


def new_threshold(value: int) -> int:
    return max(1, int(value or 1))
