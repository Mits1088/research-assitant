from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from last30free.models import SOURCE_ORDER, IntentParse, ResearchItem

STOPWORDS = {
    "about",
    "after",
    "again",
    "agent",
    "agents",
    "also",
    "announcement",
    "announcements",
    "best",
    "build",
    "coding",
    "current",
    "discussion",
    "fast",
    "from",
    "good",
    "great",
    "have",
    "into",
    "just",
    "latest",
    "make",
    "more",
    "most",
    "news",
    "people",
    "post",
    "posts",
    "project",
    "projects",
    "really",
    "show",
    "story",
    "than",
    "that",
    "their",
    "there",
    "these",
    "this",
    "thread",
    "threads",
    "tool",
    "tools",
    "update",
    "updates",
    "using",
    "video",
    "videos",
    "what",
    "with",
    "your",
}



def synthesize(
    items: list[ResearchItem],
    *,
    intent: IntentParse,
    results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ranked_items = sorted(items, key=lambda item: item.score, reverse=True)
    patterns = _build_patterns(ranked_items)
    summary_points = _build_summary_points(ranked_items)
    source_stats = _build_source_stats(ranked_items)
    headline = _build_headline(intent.topic, ranked_items, patterns)

    return {
        "headline": headline,
        "summary_points": summary_points,
        "patterns": patterns,
        "source_stats": source_stats,
        "source_status": {
            source: {
                "status": result.get("status", "unknown"),
                "count": result.get("count", 0),
                "error": result.get("error"),
            }
            for source, result in results.items()
        },
        "total_items": len(ranked_items),
        "sources_with_results": sorted({item.source.value for item in ranked_items}),
    }


def _build_headline(
    topic: str,
    items: list[ResearchItem],
    patterns: list[dict[str, Any]],
) -> str:
    if not items:
        return f"No recent cross-source discussion found for {topic}."

    active_sources = sorted({item.source.value for item in items})
    source_count = len(active_sources)

    if len(patterns) >= 2:
        return (
            f"Discussion on {topic} spans {source_count} active sources and clusters around "
            f"{patterns[0]['keyword']} and {patterns[1]['keyword']}."
        )

    if len(patterns) == 1:
        return (
            f"Discussion on {topic} spans {source_count} active sources and repeatedly centers on "
            f"{patterns[0]['keyword']}."
        )

    return f"Discussion on {topic} spans {source_count} active sources in the last 30 days."


def _build_summary_points(items: list[ResearchItem]) -> list[str]:
    if not items:
        return []

    selected: list[ResearchItem] = []
    seen_sources: set[str] = set()

    for item in items:
        source = item.source.value
        if source not in seen_sources:
            selected.append(item)
            seen_sources.add(source)
        if len(selected) >= 4:
            break

    if len(selected) < 4:
        used_ids = {item.source_id for item in selected}
        for item in items:
            if item.source_id in used_ids:
                continue
            selected.append(item)
            used_ids.add(item.source_id)
            if len(selected) >= 4:
                break

    return [_summarize_item(item) for item in selected]


def _summarize_item(item: ResearchItem) -> str:
    quote_text = ""
    if item.quotes:
        first_quote = item.quotes[0].text.strip()
        first_quote = re.sub(r"\s+", " ", first_quote)
        if len(first_quote) > 140:
            first_quote = first_quote[:137].rstrip() + "..."
        quote_text = f' Quote: "{first_quote}"'

    if item.source.value == "reddit":
        community = next((tag for tag in item.tags if tag.startswith("r/")), "reddit")
        return (
            f"{community} pushed \"{item.title}\" with {item.metrics.upvotes} upvotes and "
            f"{item.metrics.comments} comments.{quote_text}"
        )

    if item.source.value == "hn":
        label = "HN"
        if "show_hn" in item.tags:
            label = "Show HN"
        elif "ask_hn" in item.tags:
            label = "Ask HN"
        return (
            f"{label} discussion around \"{item.title}\" reached {item.metrics.points} points and "
            f"{item.metrics.comments} comments.{quote_text}"
        )

    if item.source.value == "youtube":
        channel = str(item.raw.get("channel", "") or item.author or "YouTube").strip()
        return (
            f"{channel} published \"{item.title}\", drawing {item.metrics.views} views and "
            f"{item.metrics.likes} likes.{quote_text}"
        )

    if item.source.value == "x":
        username = str(item.raw.get("username", "") or "").strip()
        handle = f"@{username}" if username else item.author
        return (
            f"{handle} posted \"{item.title}\" with {item.metrics.likes} likes, "
            f"{item.metrics.reposts} reposts, and {item.metrics.comments} replies.{quote_text}"
        )

    if item.source.value == "instagram":
        tag = str(item.raw.get("hashtag", "") or "").strip()
        label = f"#{tag}" if tag else "Instagram"
        return (
            f"{label} post by @{item.author} \"{item.title}\" got {item.metrics.likes} likes "
            f"and {item.metrics.comments} comments.{quote_text}"
        )

    if item.source.value == "tiktok":
        return (
            f"@{item.author} on TikTok: \"{item.title}\" — {item.metrics.views} views, "
            f"{item.metrics.likes} likes.{quote_text}"
        )

    return f"\"{item.title}\" surfaced in {item.source.value}.{quote_text}"


def _build_patterns(items: list[ResearchItem]) -> list[dict[str, Any]]:
    token_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "mentions": 0,
            "sources": set(),
            "examples": [],
        }
    )

    for item in items:
        source = item.source.value
        text = f"{item.title} {item.text}".strip()
        tokens = set(_tokenize(text))
        if not tokens:
            continue

        for token in tokens:
            entry = token_map[token]
            entry["mentions"] += 1
            entry["sources"].add(source)
            if item.title and item.title not in entry["examples"] and len(entry["examples"]) < 3:
                entry["examples"].append(item.title)

    ranked = []
    for keyword, data in token_map.items():
        source_count = len(data["sources"])
        mentions = data["mentions"]
        score = (source_count * 3) + mentions
        ranked.append(
            {
                "keyword": keyword,
                "mentions": mentions,
                "source_count": source_count,
                "sources": sorted(data["sources"]),
                "examples": data["examples"],
                "_rank_score": score,
            }
        )

    ranked.sort(
        key=lambda item: (
            item["_rank_score"],
            item["source_count"],
            item["mentions"],
            item["keyword"],
        ),
        reverse=True,
    )

    trimmed = []
    for item in ranked:
        if item["mentions"] < 2 and item["source_count"] < 2:
            continue
        trimmed.append({k: v for k, v in item.items() if k != "_rank_score"})
        if len(trimmed) >= 5:
            break

    if trimmed:
        return trimmed

    fallback = []
    for item in ranked[:5]:
        fallback.append({k: v for k, v in item.items() if k != "_rank_score"})
    return fallback


def _tokenize(text: str) -> list[str]:
    normalized = text.lower()
    tokens = re.findall(r"[a-z][a-z0-9\-\+]{2,}", normalized)

    cleaned = []
    for token in tokens:
        token = token.strip("-+")
        if len(token) < 4:
            continue
        if token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        cleaned.append(token)

    return cleaned


def _build_source_stats(items: list[ResearchItem]) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {
        "reddit": {
            "source": "reddit",
            "count": 0,
            "label_1": "upvotes",
            "total_1": 0,
            "label_2": "comments",
            "total_2": 0,
        },
        "hn": {
            "source": "hn",
            "count": 0,
            "label_1": "points",
            "total_1": 0,
            "label_2": "comments",
            "total_2": 0,
        },
        "youtube": {
            "source": "youtube",
            "count": 0,
            "label_1": "views",
            "total_1": 0,
            "label_2": "likes",
            "total_2": 0,
        },
        "x": {
            "source": "x",
            "count": 0,
            "label_1": "likes",
            "total_1": 0,
            "label_2": "reposts",
            "total_2": 0,
            "label_3": "replies",
            "total_3": 0,
        },
        "instagram": {
            "source": "instagram",
            "count": 0,
            "label_1": "likes",
            "total_1": 0,
            "label_2": "comments",
            "total_2": 0,
        },
        "tiktok": {
            "source": "tiktok",
            "count": 0,
            "label_1": "views",
            "total_1": 0,
            "label_2": "likes",
            "total_2": 0,
            "label_3": "shares",
            "total_3": 0,
        },
        "facebook": {
            "source": "facebook",
            "count": 0,
            "label_1": "likes",
            "total_1": 0,
            "label_2": "comments",
            "total_2": 0,
            "label_3": "reposts",
            "total_3": 0,
        },
    }

    for item in items:
        source = item.source.value
        if source not in stats:
            continue

        stats[source]["count"] += 1

        if source == "reddit":
            stats[source]["total_1"] += item.metrics.upvotes
            stats[source]["total_2"] += item.metrics.comments
        elif source == "hn":
            stats[source]["total_1"] += item.metrics.points
            stats[source]["total_2"] += item.metrics.comments
        elif source == "youtube":
            stats[source]["total_1"] += item.metrics.views
            stats[source]["total_2"] += item.metrics.likes
        elif source == "x":
            stats[source]["total_1"] += item.metrics.likes
            stats[source]["total_2"] += item.metrics.reposts
            stats[source]["total_3"] += item.metrics.comments
        elif source == "instagram":
            stats[source]["total_1"] += item.metrics.likes
            stats[source]["total_2"] += item.metrics.comments
        elif source == "tiktok":
            stats[source]["total_1"] += item.metrics.views
            stats[source]["total_2"] += item.metrics.likes
            stats[source]["total_3"] += item.metrics.reposts
        elif source == "facebook":
            stats[source]["total_1"] += item.metrics.likes
            stats[source]["total_2"] += item.metrics.comments
            stats[source]["total_3"] += item.metrics.reposts

    ordered = []
    for source in SOURCE_ORDER:
        row = stats[source]
        if row["count"] > 0:
            ordered.append(row)
    return ordered
