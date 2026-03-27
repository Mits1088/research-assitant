from __future__ import annotations

from pathlib import Path
from typing import Any


def load_payload_from_manifest(manifest: dict[str, Any]) -> dict[str, Any] | None:
    files = manifest.get("files", {})
    payload_path = Path(str(files.get("payload_path", "") or ""))
    if not payload_path.exists():
        return None

    import json

    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def compare_payloads(
    earlier_payload: dict[str, Any],
    later_payload: dict[str, Any],
    *,
    earlier_manifest: dict[str, Any],
    later_manifest: dict[str, Any],
) -> dict[str, Any]:
    earlier_items = earlier_payload.get("merged", {}).get("items", []) or []
    later_items = later_payload.get("merged", {}).get("items", []) or []

    earlier_map = _item_map(earlier_items)
    later_map = _item_map(later_items)

    earlier_ids = set(earlier_map.keys())
    later_ids = set(later_map.keys())

    added_ids = sorted(later_ids - earlier_ids)
    removed_ids = sorted(earlier_ids - later_ids)
    common_ids = sorted(earlier_ids & later_ids)

    added_items = [later_map[item_id] for item_id in added_ids]
    removed_items = [earlier_map[item_id] for item_id in removed_ids]

    score_changes = []
    for item_id in common_ids:
        earlier_item = earlier_map[item_id]
        later_item = later_map[item_id]
        earlier_score = float(earlier_item.get("score", 0) or 0)
        later_score = float(later_item.get("score", 0) or 0)
        delta = round(later_score - earlier_score, 4)
        if delta == 0:
            continue

        score_changes.append(
            {
                "item_id": item_id,
                "title": later_item.get("title") or earlier_item.get("title") or "(untitled)",
                "source": later_item.get("source") or earlier_item.get("source") or "unknown",
                "earlier_score": earlier_score,
                "later_score": later_score,
                "delta": delta,
                "url": later_item.get("url") or earlier_item.get("url") or "",
            }
        )

    score_changes.sort(key=lambda row: abs(row["delta"]), reverse=True)

    source_counts = _compare_source_counts(earlier_items, later_items)
    keyword_changes = _compare_keywords(earlier_items, later_items)

    summary = _build_summary(
        earlier_manifest=earlier_manifest,
        later_manifest=later_manifest,
        added_items=added_items,
        removed_items=removed_items,
        score_changes=score_changes,
        source_counts=source_counts,
        keyword_changes=keyword_changes,
    )

    return {
        "earlier_run": {
            "run_id": earlier_manifest.get("run_id"),
            "generated_at_utc": earlier_manifest.get("generated_at_utc"),
            "topic": earlier_manifest.get("topic"),
            "query_type": earlier_manifest.get("query_type"),
            "merged_items": earlier_manifest.get("counts", {}).get("merged_items", len(earlier_items)),
        },
        "later_run": {
            "run_id": later_manifest.get("run_id"),
            "generated_at_utc": later_manifest.get("generated_at_utc"),
            "topic": later_manifest.get("topic"),
            "query_type": later_manifest.get("query_type"),
            "merged_items": later_manifest.get("counts", {}).get("merged_items", len(later_items)),
        },
        "summary": summary,
        "counts": {
            "added": len(added_items),
            "removed": len(removed_items),
            "score_changed": len(score_changes),
        },
        "added_items": _serialize_diff_items(added_items[:10]),
        "removed_items": _serialize_diff_items(removed_items[:10]),
        "score_changes": score_changes[:10],
        "source_counts": source_counts,
        "keyword_changes": keyword_changes[:10],
    }


def render_comparison_markdown(comparison: dict[str, Any]) -> str:
    earlier_run = comparison.get("earlier_run", {})
    later_run = comparison.get("later_run", {})
    summary = comparison.get("summary", {})
    lines: list[str] = []

    lines.append("# last30free comparison report")
    lines.append("")
    lines.append(
        f"- Earlier run: {earlier_run.get('run_id', '')} ({earlier_run.get('generated_at_utc', '')})"
    )
    lines.append(
        f"- Later run: {later_run.get('run_id', '')} ({later_run.get('generated_at_utc', '')})"
    )
    lines.append(f"- Topic: {later_run.get('topic') or earlier_run.get('topic') or ''}")
    lines.append("")

    headline = str(summary.get("headline", "") or "").strip()
    if headline:
        lines.append("## Change summary")
        lines.append("")
        lines.append(headline)
        lines.append("")

    bullet_points = summary.get("bullet_points", [])
    if bullet_points:
        lines.append("## Key changes")
        lines.append("")
        for point in bullet_points:
            lines.append(f"- {point}")
        lines.append("")

    source_counts = comparison.get("source_counts", [])
    if source_counts:
        lines.append("## Source count changes")
        lines.append("")
        for row in source_counts:
            lines.append(
                f"- **{row['source']}** — earlier: {row['earlier_count']}, "
                f"later: {row['later_count']}, delta: {row['delta']:+d}"
            )
        lines.append("")

    keyword_changes = comparison.get("keyword_changes", [])
    if keyword_changes:
        lines.append("## Keyword changes")
        lines.append("")
        for row in keyword_changes:
            lines.append(
                f"- **{row['keyword']}** — earlier: {row['earlier_mentions']}, "
                f"later: {row['later_mentions']}, delta: {row['delta']:+d}"
            )
        lines.append("")

    added_items = comparison.get("added_items", [])
    if added_items:
        lines.append("## New items in later run")
        lines.append("")
        for item in added_items:
            lines.append(f"- [{item['title']}]({item['url']}) — {item['source']}")
        lines.append("")

    removed_items = comparison.get("removed_items", [])
    if removed_items:
        lines.append("## Items no longer present")
        lines.append("")
        for item in removed_items:
            lines.append(f"- [{item['title']}]({item['url']}) — {item['source']}")
        lines.append("")

    score_changes = comparison.get("score_changes", [])
    if score_changes:
        lines.append("## Biggest score changes")
        lines.append("")
        for item in score_changes:
            lines.append(
                f"- [{item['title']}]({item['url']}) — {item['source']} | "
                f"{item['earlier_score']:.2f} → {item['later_score']:.2f} "
                f"({item['delta']:+.2f})"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _item_map(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for item in items:
        item_id = _stable_item_id(item)
        mapping[item_id] = item
    return mapping


def _stable_item_id(item: dict[str, Any]) -> str:
    source = str(item.get("source", "") or "")
    source_id = str(item.get("source_id", "") or "")
    url = str(item.get("url", "") or "")
    title = str(item.get("title", "") or "")

    if source and source_id:
        return f"{source}:{source_id}"
    if source and url:
        return f"{source}:{url}"
    return f"{source}:{title}"


def _serialize_diff_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "item_id": _stable_item_id(item),
            "source": item.get("source"),
            "title": item.get("title"),
            "url": item.get("url"),
            "score": item.get("score"),
        }
        for item in items
    ]


def _compare_source_counts(
    earlier_items: list[dict[str, Any]],
    later_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sources = {"reddit", "hn", "youtube", "x"}
    earlier_counts = {source: 0 for source in sources}
    later_counts = {source: 0 for source in sources}

    for item in earlier_items:
        source = str(item.get("source", "") or "")
        if source in earlier_counts:
            earlier_counts[source] += 1

    for item in later_items:
        source = str(item.get("source", "") or "")
        if source in later_counts:
            later_counts[source] += 1

    rows = []
    for source in sorted(sources):
        earlier_count = earlier_counts[source]
        later_count = later_counts[source]
        if earlier_count == 0 and later_count == 0:
            continue

        rows.append(
            {
                "source": source,
                "earlier_count": earlier_count,
                "later_count": later_count,
                "delta": later_count - earlier_count,
            }
        )

    rows.sort(key=lambda row: abs(row["delta"]), reverse=True)
    return rows


def _compare_keywords(
    earlier_items: list[dict[str, Any]],
    later_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    earlier_counts = _keyword_counts(earlier_items)
    later_counts = _keyword_counts(later_items)

    keywords = set(earlier_counts) | set(later_counts)
    rows = []

    for keyword in keywords:
        earlier_mentions = earlier_counts.get(keyword, 0)
        later_mentions = later_counts.get(keyword, 0)
        delta = later_mentions - earlier_mentions
        if delta == 0:
            continue

        rows.append(
            {
                "keyword": keyword,
                "earlier_mentions": earlier_mentions,
                "later_mentions": later_mentions,
                "delta": delta,
            }
        )

    rows.sort(key=lambda row: (abs(row["delta"]), row["later_mentions"], row["keyword"]), reverse=True)
    return rows


def _keyword_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    stopwords = {
        "about", "after", "again", "also", "best", "build", "current", "from", "have",
        "into", "just", "latest", "more", "most", "news", "people", "post", "posts",
        "really", "than", "that", "their", "there", "these", "this", "thread", "threads",
        "tool", "tools", "update", "updates", "using", "video", "videos", "what", "with",
        "your",
    }

    import re

    for item in items:
        text = f"{item.get('title', '')} {item.get('text', '')}".lower()
        tokens = set(re.findall(r"[a-z][a-z0-9\-\+]{2,}", text))
        for token in tokens:
            token = token.strip("-+")
            if len(token) < 4:
                continue
            if token in stopwords:
                continue
            counts[token] = counts.get(token, 0) + 1

    return counts


def _build_summary(
    *,
    earlier_manifest: dict[str, Any],
    later_manifest: dict[str, Any],
    added_items: list[dict[str, Any]],
    removed_items: list[dict[str, Any]],
    score_changes: list[dict[str, Any]],
    source_counts: list[dict[str, Any]],
    keyword_changes: list[dict[str, Any]],
) -> dict[str, Any]:
    earlier_count = int(earlier_manifest.get("counts", {}).get("merged_items", 0) or 0)
    later_count = int(later_manifest.get("counts", {}).get("merged_items", 0) or 0)
    delta_items = later_count - earlier_count

    headline_parts = [
        f"The later run has {later_count} merged items versus {earlier_count} earlier "
        f"({delta_items:+d})."
    ]

    if added_items:
        headline_parts.append(f"{len(added_items)} new items appeared.")
    if removed_items:
        headline_parts.append(f"{len(removed_items)} items dropped out.")

    strongest_source = source_counts[0] if source_counts else None
    if strongest_source and strongest_source["delta"] != 0:
        direction = "up" if strongest_source["delta"] > 0 else "down"
        headline_parts.append(
            f"{strongest_source['source']} moved {direction} by {abs(strongest_source['delta'])} items."
        )

    bullet_points = []

    if added_items:
        top_added = added_items[0]
        bullet_points.append(
            f"New in the later run: {top_added.get('title', '(untitled)')} ({top_added.get('source', 'unknown')})."
        )

    if removed_items:
        top_removed = removed_items[0]
        bullet_points.append(
            f"No longer present: {top_removed.get('title', '(untitled)')} ({top_removed.get('source', 'unknown')})."
        )

    if score_changes:
        strongest_score = score_changes[0]
        trend = "rose" if strongest_score["delta"] > 0 else "fell"
        bullet_points.append(
            f"Biggest score change: {strongest_score['title']} {trend} by {abs(strongest_score['delta']):.2f}."
        )

    if keyword_changes:
        strongest_keyword = keyword_changes[0]
        trend = "increased" if strongest_keyword["delta"] > 0 else "decreased"
        bullet_points.append(
            f"Keyword shift: {strongest_keyword['keyword']} {trend} by {abs(strongest_keyword['delta'])} mentions."
        )

    return {
        "headline": " ".join(headline_parts).strip(),
        "bullet_points": bullet_points,
    }
