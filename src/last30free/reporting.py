from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from last30free.models import IntentParse


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "report"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def create_run_dir(output_dir: Path, topic: str) -> Path:
    run_name = f"{utc_timestamp()}_{slugify(topic)}"
    run_dir = output_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def write_run_outputs(
    *,
    run_dir: Path,
    payload: dict[str, Any],
    raw_query: str,
    argv: list[str],
) -> dict[str, str]:
    run_dir.mkdir(parents=True, exist_ok=True)

    markdown_text = render_markdown_report(payload)
    merged_items_json = json.dumps(payload.get("merged", {}).get("items", []), indent=2, ensure_ascii=False)
    payload_json = json.dumps(payload, indent=2, ensure_ascii=False)
    manifest = build_manifest(
        payload=payload,
        raw_query=raw_query,
        argv=argv,
        run_dir=run_dir,
    )
    manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False)

    report_path = run_dir / "report.md"
    merged_path = run_dir / "merged_items.json"
    payload_path = run_dir / "run_payload.json"
    manifest_path = run_dir / "manifest.json"

    report_path.write_text(markdown_text, encoding="utf-8")
    merged_path.write_text(merged_items_json, encoding="utf-8")
    payload_path.write_text(payload_json, encoding="utf-8")
    manifest_path.write_text(manifest_json, encoding="utf-8")

    return {
        "run_dir": str(run_dir),
        "report_path": str(report_path),
        "merged_items_path": str(merged_path),
        "payload_path": str(payload_path),
        "manifest_path": str(manifest_path),
    }


def build_manifest(
    *,
    payload: dict[str, Any],
    raw_query: str,
    argv: list[str],
    run_dir: Path,
) -> dict[str, Any]:
    intent = payload.get("intent", {})
    runtime = payload.get("runtime", {})
    synthesis = payload.get("synthesis", {})
    results = payload.get("results", {})
    run_id = run_dir.name

    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": payload.get("status"),
        "message": payload.get("message"),
        "raw_query": raw_query,
        "argv": argv,
        "topic": intent.get("topic"),
        "target_tool": intent.get("target_tool"),
        "query_type": intent.get("query_type"),
        "runtime": {
            "days": runtime.get("days"),
            "depth": runtime.get("depth"),
            "limit_per_source": runtime.get("limit_per_source"),
            "selected_sources": runtime.get("selected_sources", []),
            "implemented_selected_sources": runtime.get("implemented_selected_sources", []),
            "skipped_sources": runtime.get("skipped_sources", []),
            "output_dir": runtime.get("output_dir"),
            "cache_dir": runtime.get("cache_dir"),
            "x_enabled": runtime.get("x_enabled"),
            "x_configured": runtime.get("x_configured"),
        },
        "counts": {
            "merged_items": payload.get("merged", {}).get("count", 0),
            "summary_points": len(synthesis.get("summary_points", [])),
            "patterns": len(synthesis.get("patterns", [])),
        },
        "source_status": {
            source: {
                "status": result.get("status"),
                "count": result.get("count", 0),
                "error": result.get("error"),
            }
            for source, result in results.items()
        },
        "files": {
            "run_dir": str(run_dir),
            "report_path": str(run_dir / "report.md"),
            "merged_items_path": str(run_dir / "merged_items.json"),
            "payload_path": str(run_dir / "run_payload.json"),
            "manifest_path": str(run_dir / "manifest.json"),
        },
    }


def render_markdown_report(payload: dict[str, Any]) -> str:
    intent = payload.get("intent", {})
    runtime = payload.get("runtime", {})
    synthesis = payload.get("synthesis", {})
    merged = payload.get("merged", {})
    items = merged.get("items", [])

    lines: list[str] = []
    topic = str(intent.get("topic") or "Unknown topic")
    query_type = str(intent.get("query_type") or "UNKNOWN")
    target_tool = str(intent.get("target_tool") or "unknown")

    lines.append(f"# last30free report — {topic}")
    lines.append("")
    lines.append(f"- Generated at: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Query type: {query_type}")
    lines.append(f"- Target tool: {target_tool}")
    lines.append(f"- Days: {runtime.get('days')}")
    lines.append(f"- Depth: {runtime.get('depth')}")
    lines.append(f"- Sources: {', '.join(runtime.get('selected_sources', [])) or '(none)'}")
    lines.append("")

    headline = str(synthesis.get("headline") or "").strip()
    if headline:
        lines.append("## What I learned")
        lines.append("")
        lines.append(headline)
        lines.append("")

    summary_points = synthesis.get("summary_points", [])
    if summary_points:
        lines.append("## Key takeaways")
        lines.append("")
        for point in summary_points:
            lines.append(f"- {point}")
        lines.append("")

    patterns = synthesis.get("patterns", [])
    if patterns:
        lines.append("## Recurring patterns")
        lines.append("")
        for pattern in patterns:
            keyword = pattern.get("keyword", "")
            mentions = pattern.get("mentions", 0)
            source_count = pattern.get("source_count", 0)
            examples = pattern.get("examples", [])
            example_text = ", ".join(examples[:2]) if examples else ""
            if example_text:
                lines.append(
                    f"- **{keyword}** — {mentions} mentions across {source_count} sources. "
                    f"Examples: {example_text}"
                )
            else:
                lines.append(f"- **{keyword}** — {mentions} mentions across {source_count} sources.")
        lines.append("")

    source_stats = synthesis.get("source_stats", [])
    if source_stats:
        lines.append("## Source stats")
        lines.append("")
        for row in source_stats:
            metric_parts = [
                f"{row['label_1']}: {row['total_1']}",
                f"{row['label_2']}: {row['total_2']}",
            ]
            if "label_3" in row:
                metric_parts.append(f"{row['label_3']}: {row['total_3']}")
            metrics_text = " | ".join(metric_parts)
            lines.append(f"- **{row['source']}** — {row['count']} items | {metrics_text}")
        lines.append("")

    lines.append("## Top merged discussions")
    lines.append("")
    if not items:
        lines.append("No merged results found.")
        lines.append("")
    else:
        for idx, item in enumerate(items[:15], start=1):
            source = item.get("source", "unknown")
            title = item.get("title", "(untitled)")
            url = item.get("url", "")
            score = item.get("score", 0)
            author = item.get("author", "unknown")
            lines.append(f"### {idx}. [{title}]({url})")
            lines.append("")
            lines.append(f"- Source: {source}")
            lines.append(f"- Author: {author}")
            lines.append(f"- Score: {score}")
            lines.append(f"- Created at: {item.get('created_at')}")
            metric_lines = _metric_summary(item)
            if metric_lines:
                lines.append(f"- Metrics: {metric_lines}")
            quotes = item.get("quotes", [])
            if quotes:
                first_quote = quotes[0]
                quote_text = str(first_quote.get("text", "")).strip()
                if quote_text:
                    lines.append(f'- Quote: "{quote_text}"')
            lines.append("")

    source_status = synthesis.get("source_status", {})
    if source_status:
        lines.append("## Source execution")
        lines.append("")
        for source, row in source_status.items():
            status = row.get("status", "unknown")
            count = row.get("count", 0)
            error = row.get("error")
            line = f"- **{source}** — status: {status}, count: {count}"
            if error:
                line += f", error: {error}"
            lines.append(line)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _metric_summary(item: dict[str, Any]) -> str:
    source = item.get("source")
    metrics = item.get("metrics", {})

    if source == "reddit":
        return f"{metrics.get('upvotes', 0)} upvotes | {metrics.get('comments', 0)} comments"
    if source == "hn":
        return f"{metrics.get('points', 0)} points | {metrics.get('comments', 0)} comments"
    if source == "youtube":
        return f"{metrics.get('views', 0)} views | {metrics.get('likes', 0)} likes"
    if source == "x":
        return (
            f"{metrics.get('likes', 0)} likes | "
            f"{metrics.get('reposts', 0)} reposts | "
            f"{metrics.get('comments', 0)} replies"
        )
    return ""
