from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from .adapters import AdapterError, FacebookAdapter, HNAdapter, InstagramAdapter, RedditAdapter, TikTokAdapter, XAdapter, YouTubeAdapter
from .alerts import build_alert_report_from_manifests
from .comparison import compare_payloads, load_payload_from_manifest, render_comparison_markdown
from .config import Settings, load_settings
from .models import ALL_SOURCES, IntentParse, QueryType, ResearchItem
from .notification_store import (
    list_notification_snapshots,
    notification_index_path,
    write_notification_bundle,
)
from .notifications import build_notification_bundle
from .reporting import create_run_dir, write_run_outputs
from .run_index import (
    index_path,
    latest_run_for_topic,
    latest_runs_by_topic,
    list_saved_runs,
    read_manifest,
    resolve_saved_run,
    runs_for_topic,
    update_run_index,
)
from .generator import GeneratorError, generate, list_formats
from .synthesis import synthesize
from .watchlist import (
    build_watchlist_runner_payloads,
    init_watchlist,
    load_watchlist,
    resolve_watch_topics,
    watchlist_path,
)

PROMPTING_HINTS = (
    "prompt",
    "prompts",
    "prompting",
    "mockup",
    "mockups",
    "ui",
    "design",
    "image",
    "images",
    "video",
    "videos",
    "thumbnail",
    "thumbnails",
)

IMPLEMENTED_SOURCES = ALL_SOURCES


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def detect_query_type(raw_query: str) -> QueryType:
    lowered = raw_query.lower().strip()

    if re.search(r"\s+(vs|versus)\s+", lowered):
        return QueryType.COMPARISON

    if any(
        phrase in lowered
        for phrase in (
            "best ",
            "top ",
            "recommended ",
            "recommend ",
            "what should i use",
            "what are the best",
            "most popular ",
        )
    ):
        return QueryType.RECOMMENDATIONS

    if any(
        phrase in lowered
        for phrase in (
            "what's happening",
            "whats happening",
            "what is happening",
            "latest on",
            "latest ",
            " news",
            "update",
            "updates",
            "announcement",
            "announcements",
        )
    ):
        return QueryType.NEWS

    if any(hint in lowered for hint in PROMPTING_HINTS):
        return QueryType.PROMPTING

    return QueryType.GENERAL


def clean_topic_text(text: str, query_type: QueryType) -> str:
    value = normalize_spaces(text)

    if query_type == QueryType.RECOMMENDATIONS:
        value = re.sub(
            r"^(what (are|is) the )?(best|top|recommended)\s+",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"^most popular\s+", "", value, flags=re.IGNORECASE)
        value = re.sub(r"^recommend\s+", "", value, flags=re.IGNORECASE)

    elif query_type == QueryType.NEWS:
        value = re.sub(
            r"^(what('s| is)? happening (with|on)\s+|latest on\s+|latest\s+|news on\s+)",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"\s+news$", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+updates?$", "", value, flags=re.IGNORECASE)

    elif query_type == QueryType.PROMPTING:
        value = re.sub(r"^(prompting for|prompts? for)\s+", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+prompts?$", "", value, flags=re.IGNORECASE)

    return normalize_spaces(value.strip(" -"))


def extract_topic_and_tool(
    raw_query: str,
    query_type: QueryType,
    tool_override: str | None,
) -> tuple[str, str]:
    if tool_override:
        return clean_topic_text(raw_query, query_type), normalize_spaces(tool_override)

    if query_type == QueryType.COMPARISON:
        return normalize_spaces(raw_query), "unknown"

    if " for " in raw_query.lower():
        left, right = re.split(r"\bfor\b", raw_query, maxsplit=1, flags=re.IGNORECASE)
        left = normalize_spaces(left)
        right = normalize_spaces(right)

        if query_type == QueryType.PROMPTING or any(hint in left.lower() for hint in PROMPTING_HINTS):
            return clean_topic_text(left, query_type), right or "unknown"

    return clean_topic_text(raw_query, query_type), "unknown"


def parse_user_intent(raw_query: str, tool_override: str | None = None, literal: bool = False) -> IntentParse:
    query = normalize_spaces(raw_query)

    if literal:
        return IntentParse(
            raw_query=query,
            topic=query,
            target_tool=normalize_spaces(tool_override) if tool_override else "unknown",
            query_type=QueryType.GENERAL,
        )

    query_type = detect_query_type(query)

    if query_type == QueryType.COMPARISON:
        parts = re.split(r"\s+(?:vs|versus)\s+", query, maxsplit=1, flags=re.IGNORECASE)
        topic_a = normalize_spaces(parts[0])
        topic_b = normalize_spaces(parts[1]) if len(parts) > 1 else ""
        return IntentParse(
            raw_query=query,
            topic=f"{topic_a} vs {topic_b}".strip(),
            target_tool=normalize_spaces(tool_override) if tool_override else "unknown",
            query_type=query_type,
            topic_a=topic_a or None,
            topic_b=topic_b or None,
        )

    topic, target_tool = extract_topic_and_tool(query, query_type, tool_override)

    return IntentParse(
        raw_query=query,
        topic=topic,
        target_tool=target_tool,
        query_type=query_type,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free",
        description="Free-source last-30-days research engine scaffold.",
    )
    parser.add_argument("query", nargs="+", help="Research query, for example: best project management tools")
    parser.add_argument("--days", type=int, default=None, help="Lookback window in days")
    parser.add_argument("--tool", default=None, help="Override the target tool")
    parser.add_argument(
        "--source",
        action="append",
        choices=["reddit", "hn", "youtube", "x", "instagram", "tiktok", "facebook"],
        help="Limit runtime to one or more sources; can be passed multiple times",
    )
    parser.add_argument("--literal", action="store_true", help="Pass the query verbatim to all sources — skip intent parsing and topic cleaning")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    parser.add_argument("--save", action="store_true", help="Write report and run artifacts to the output directory")
    parser.add_argument("--results", type=int, default=0, help="Number of merged results to display (default: 0 = all)")
    parser.add_argument("--per-source-limit", type=int, default=None, dest="per_source_limit", help="Override fetch limit per source (overrides .env search limit settings)")
    parser.add_argument(
        "--filter",
        action="append",
        dest="filters",
        metavar="KEYWORD",
        help="Keep only results containing this keyword (case-insensitive); can be passed multiple times (AND logic)",
    )
    parser.add_argument("--version", action="version", version="last30free 0.1.0")

    depth_group = parser.add_mutually_exclusive_group()
    depth_group.add_argument("--quick", action="store_true", help="Use a lighter/faster runtime profile")
    depth_group.add_argument("--deep", action="store_true", help="Use a deeper/more comprehensive runtime profile")

    return parser


def build_runs_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free runs",
        description="List saved last30free runs from the local output index.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of runs to show")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_show_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free show",
        description="Show a saved report by run id, topic match, or manifest path.",
    )
    parser.add_argument("run_ref", help="Run id, partial topic, run directory, or manifest path")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_compare_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free compare",
        description="Compare two saved runs and generate a change summary.",
    )
    parser.add_argument("earlier_ref", help="Earlier run id, partial topic, run directory, or manifest path")
    parser.add_argument("later_ref", help="Later run id, partial topic, run directory, or manifest path")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_latest_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free latest",
        description="Show the latest saved run per topic, or the latest run for a specific topic.",
    )
    parser.add_argument("topic_ref", nargs="?", help="Optional topic or run reference")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of topics to show")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_alerts_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free alerts",
        description="Evaluate alert rules on the latest saved run changes.",
    )
    parser.add_argument("topic_ref", nargs="?", help="Optional topic or run reference")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of topics to inspect when no topic is given")
    parser.add_argument("--new-item-threshold", type=int, default=1)
    parser.add_argument("--source-spike-threshold", type=int, default=2)
    parser.add_argument("--keyword-spike-threshold", type=int, default=2)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_notify_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free notify",
        description="Generate notification payloads from alert reports without sending them.",
    )
    parser.add_argument("topic_ref", nargs="?", help="Optional topic or run reference")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of topics to inspect when no topic is given")
    parser.add_argument("--new-item-threshold", type=int, default=1)
    parser.add_argument("--source-spike-threshold", type=int, default=2)
    parser.add_argument("--keyword-spike-threshold", type=int, default=2)
    parser.add_argument("--channel", action="append", choices=["email", "webhook"], help="Notification channel to include; can be passed multiple times")
    parser.add_argument("--save", action="store_true", help="Save notification bundles to output history")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_notify_history_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free notify-history",
        description="Show saved notification snapshot history.",
    )
    parser.add_argument("topic_ref", nargs="?", help="Optional topic or snapshot reference")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of snapshots to show")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_watchlist_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free watchlist",
        description="Manage a file-based watchlist and run saved topics manually.",
    )
    subparsers = parser.add_subparsers(dest="watchlist_command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a starter watchlist.json file")
    init_parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing watchlist file")
    init_parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")

    show_parser = subparsers.add_parser("show", help="Show watchlist topics")
    show_parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")

    payloads_parser = subparsers.add_parser("payloads", help="Build scheduler-ready payloads for enabled topics")
    payloads_parser.add_argument("topic_refs", nargs="*", help="Optional topic ids or partial matches")
    payloads_parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")

    run_parser = subparsers.add_parser("run", help="Run enabled watchlist topics and save outputs")
    run_parser.add_argument("topic_refs", nargs="*", help="Optional topic ids or partial matches to run")
    run_parser.add_argument("--dry-run", action="store_true", help="Show which topics would run without executing")
    run_parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")

    return parser


def resolve_sources(settings: Settings, requested_sources: list[str] | None) -> tuple[list[str], list[str]]:
    available = ["reddit", "hn", "youtube"]
    if settings.x.enable and settings.x.configured:
        available.append("x")
    if settings.instagram.enable:
        available.append("instagram")
    if settings.tiktok.enable:
        available.append("tiktok")
    if settings.facebook.enable and settings.facebook.configured:
        available.append("facebook")

    if not requested_sources:
        return available, []

    selected = [source for source in requested_sources if source in available]
    skipped = [source for source in requested_sources if source not in available]
    return selected, skipped


def resolve_limit(settings: Settings, *, quick: bool, deep: bool) -> int:
    if quick:
        return 10
    if deep:
        return 40
    return settings.app.max_items_per_source


def serialize_items(items: list[ResearchItem]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in items]


def summarize_item_signal(item: dict[str, Any]) -> str:
    source = item["source"]
    metrics = item["metrics"]

    if source == "reddit":
        return f"{metrics['upvotes']} ups / {metrics['comments']} cmt"
    if source == "hn":
        return f"{metrics['points']} pts / {metrics['comments']} cmt"
    if source == "youtube":
        return f"{metrics['views']} views / {metrics['likes']} likes"
    if source == "x":
        return f"{metrics['likes']} likes / {metrics['reposts']} rts / {metrics['comments']} replies"
    if source == "instagram":
        return f"{metrics['likes']} likes / {metrics['comments']} cmt"
    if source == "tiktok":
        return f"{metrics['views']} views / {metrics['likes']} likes / {metrics['reposts']} shares"
    if source == "facebook":
        return f"{metrics['likes']} likes / {metrics['comments']} cmt / {metrics['reposts']} shares"
    return "-"


def summarize_item_community(item: dict[str, Any]) -> str:
    if item["source"] == "reddit":
        for tag in item.get("tags", []):
            if tag.startswith("r/"):
                return tag
        return "reddit"

    if item["source"] == "hn":
        tags = item.get("tags", [])
        if "show_hn" in tags:
            return "show_hn"
        if "ask_hn" in tags:
            return "ask_hn"
        return "HN"

    if item["source"] == "youtube":
        for tag in item.get("tags", []):
            if tag.startswith("channel:"):
                return tag.removeprefix("channel:")
        return "YouTube"

    if item["source"] == "x":
        username = str(item.get("raw", {}).get("username", "") or "").strip()
        if not username:
            # Fallback: extract from URL (https://x.com/{username}/status/{id})
            url = item.get("url", "")
            import re as _re
            m = _re.match(r"https://x\.com/([^/]+)/status/", url)
            if m:
                username = m.group(1)
        return f"@{username}" if username else "X"

    if item["source"] == "instagram":
        username = str(item.get("raw", {}).get("username", "") or "").strip()
        return f"@{username}" if username else "Instagram"

    if item["source"] == "tiktok":
        username = str(item.get("raw", {}).get("username", "") or "").strip()
        return f"@{username}" if username else "TikTok"

    if item["source"] == "facebook":
        author = str(item.get("raw", {}).get("author", "") or "").strip()
        return author if author else "Facebook"

    return item["source"]


def init_result() -> dict[str, Any]:
    return {
        "status": "not_requested",
        "count": 0,
        "items": [],
        "error": None,
    }


def run_reddit(settings: Settings, topic: str, *, days: int, limit: int) -> tuple[dict[str, Any], list[ResearchItem]]:
    adapter = RedditAdapter(settings)
    try:
        items = adapter.search(topic, days=days, limit=limit)
        return (
            {
                "status": "ok",
                "count": len(items),
                "items": serialize_items(items),
                "error": None,
            },
            items,
        )
    except AdapterError as exc:
        return (
            {
                "status": "error",
                "count": 0,
                "items": [],
                "error": str(exc),
            },
            [],
        )
    finally:
        adapter.close()


def run_hn(settings: Settings, topic: str, *, days: int, limit: int) -> tuple[dict[str, Any], list[ResearchItem]]:
    adapter = HNAdapter(settings)
    try:
        items = adapter.search(topic, days=days, limit=limit)
        return (
            {
                "status": "ok",
                "count": len(items),
                "items": serialize_items(items),
                "error": None,
            },
            items,
        )
    except AdapterError as exc:
        return (
            {
                "status": "error",
                "count": 0,
                "items": [],
                "error": str(exc),
            },
            [],
        )
    finally:
        adapter.close()


def run_youtube(settings: Settings, topic: str, *, days: int, limit: int) -> tuple[dict[str, Any], list[ResearchItem]]:
    adapter = YouTubeAdapter(settings)
    try:
        items = adapter.search(topic, days=days, limit=limit)
        return (
            {
                "status": "ok",
                "count": len(items),
                "items": serialize_items(items),
                "error": None,
            },
            items,
        )
    except AdapterError as exc:
        return (
            {
                "status": "error",
                "count": 0,
                "items": [],
                "error": str(exc),
            },
            [],
        )
    finally:
        adapter.close()


def run_x(settings: Settings, topic: str, *, days: int, limit: int) -> tuple[dict[str, Any], list[ResearchItem]]:
    adapter = XAdapter(settings)
    try:
        items = adapter.search(topic, days=days, limit=limit)
        return (
            {
                "status": "ok",
                "count": len(items),
                "items": serialize_items(items),
                "error": None,
            },
            items,
        )
    except AdapterError as exc:
        return (
            {
                "status": "error",
                "count": 0,
                "items": [],
                "error": str(exc),
            },
            [],
        )
    finally:
        adapter.close()


def run_instagram(settings: Settings, topic: str, *, days: int, limit: int) -> tuple[dict[str, Any], list[ResearchItem]]:
    if not settings.instagram.authenticated:
        return (
            {
                "status": "not_configured",
                "count": 0,
                "items": [],
                "error": "Set INSTAGRAM_SESSION_ID env var to enable (get it from browser DevTools → Cookies → instagram.com → sessionid)",
            },
            [],
        )
    adapter = InstagramAdapter(settings)
    try:
        items = adapter.search(topic, days=days, limit=limit)
        return (
            {
                "status": "ok",
                "count": len(items),
                "items": serialize_items(items),
                "error": None,
            },
            items,
        )
    except AdapterError as exc:
        return (
            {
                "status": "error",
                "count": 0,
                "items": [],
                "error": str(exc),
            },
            [],
        )
    finally:
        adapter.close()


def run_tiktok(settings: Settings, topic: str, *, days: int, limit: int) -> tuple[dict[str, Any], list[ResearchItem]]:
    adapter = TikTokAdapter(settings)
    try:
        items = adapter.search(topic, days=days, limit=limit)
        return (
            {
                "status": "ok",
                "count": len(items),
                "items": serialize_items(items),
                "error": None,
            },
            items,
        )
    except AdapterError as exc:
        return (
            {
                "status": "error",
                "count": 0,
                "items": [],
                "error": str(exc),
            },
            [],
        )
    finally:
        adapter.close()


def run_facebook(settings: Settings, topic: str, *, days: int, limit: int) -> tuple[dict[str, Any], list[ResearchItem]]:
    if not settings.facebook.configured:
        return (
            {
                "status": "not_configured",
                "count": 0,
                "items": [],
                "error": (
                    "Set FACEBOOK_C_USER and FACEBOOK_XS env vars to enable "
                    "(get them from browser DevTools → Application → Cookies → facebook.com)"
                ),
            },
            [],
        )
    adapter = FacebookAdapter(settings)
    try:
        items = adapter.search(topic, days=days, limit=limit)
        return (
            {
                "status": "ok",
                "count": len(items),
                "items": serialize_items(items),
                "error": None,
            },
            items,
        )
    except AdapterError as exc:
        return (
            {
                "status": "error",
                "count": 0,
                "items": [],
                "error": str(exc),
            },
            [],
        )
    finally:
        adapter.close()


def build_payload_for_query(
    *,
    raw_query: str,
    settings: Settings,
    days: int | None = None,
    tool: str | None = None,
    sources: list[str] | None = None,
    filters: list[str] | None = None,
    per_source_limit: int | None = None,
    quick: bool = False,
    deep: bool = False,
    literal: bool = False,
) -> dict[str, Any]:
    intent = parse_user_intent(raw_query, tool_override=tool, literal=literal)
    selected_sources, skipped_sources = resolve_sources(settings, sources)

    if deep:
        depth = "deep"
    elif quick:
        depth = "quick"
    else:
        depth = "balanced"

    runtime_days = days or settings.app.default_days
    runtime_limit = resolve_limit(settings, quick=quick, deep=deep)
    if per_source_limit is not None:
        runtime_limit = per_source_limit
        settings.reddit.search_limit = per_source_limit
        settings.hn.search_limit = per_source_limit
        settings.youtube.search_limit = per_source_limit
        settings.x.search_limit = per_source_limit
        settings.instagram.search_limit = per_source_limit
        settings.tiktok.search_limit = per_source_limit
        settings.facebook.search_limit = per_source_limit
    implemented_selected = [source for source in selected_sources if source in IMPLEMENTED_SOURCES]

    results: dict[str, Any] = {
        "reddit": init_result(),
        "hn": init_result(),
        "youtube": init_result(),
        "x": init_result(),
        "instagram": init_result(),
        "tiktok": init_result(),
        "facebook": init_result(),
    }

    merged_items: list[ResearchItem] = []

    if "reddit" in implemented_selected:
        reddit_result, reddit_items = run_reddit(
            settings,
            intent.topic,
            days=runtime_days,
            limit=runtime_limit,
        )
        results["reddit"] = reddit_result
        merged_items.extend(reddit_items)

    if "hn" in implemented_selected:
        hn_result, hn_items = run_hn(
            settings,
            intent.topic,
            days=runtime_days,
            limit=runtime_limit,
        )
        results["hn"] = hn_result
        merged_items.extend(hn_items)

    if "youtube" in implemented_selected:
        youtube_result, youtube_items = run_youtube(
            settings,
            intent.topic,
            days=runtime_days,
            limit=runtime_limit,
        )
        results["youtube"] = youtube_result
        merged_items.extend(youtube_items)

    if "x" in implemented_selected:
        x_result, x_items = run_x(
            settings,
            intent.topic,
            days=runtime_days,
            limit=runtime_limit,
        )
        results["x"] = x_result
        merged_items.extend(x_items)

    if "instagram" in implemented_selected:
        instagram_result, instagram_items = run_instagram(
            settings,
            intent.topic,
            days=runtime_days,
            limit=runtime_limit,
        )
        results["instagram"] = instagram_result
        merged_items.extend(instagram_items)

    if "tiktok" in implemented_selected:
        tiktok_result, tiktok_items = run_tiktok(
            settings,
            intent.topic,
            days=runtime_days,
            limit=runtime_limit,
        )
        results["tiktok"] = tiktok_result
        merged_items.extend(tiktok_items)

    if "facebook" in implemented_selected:
        facebook_result, facebook_items = run_facebook(
            settings,
            intent.topic,
            days=runtime_days,
            limit=runtime_limit,
        )
        results["facebook"] = facebook_result
        merged_items.extend(facebook_items)

    if filters:
        keywords = [kw.lower() for kw in filters]
        merged_items = [
            item for item in merged_items
            if all(kw in (item.title + " " + item.text).lower() for kw in keywords)
        ]

    merged_items = sorted(merged_items, key=lambda item: item.score, reverse=True)
    merged_serialized = serialize_items(merged_items)

    any_error = any(result["status"] == "error" for result in results.values())
    status = "partial" if any_error else "ok"

    synthesis = synthesize(
        merged_items,
        intent=intent,
        results=results,
    )

    return {
        "status": status,
        "message": "Reddit, HN, YouTube, X, Instagram, TikTok, and Facebook live fetch are implemented, with first-pass synthesis.",
        "intent": intent.model_dump(mode="json"),
        "runtime": {
            "days": runtime_days,
            "depth": depth,
            "limit_per_source": runtime_limit,
            "selected_sources": selected_sources,
            "implemented_selected_sources": implemented_selected,
            "skipped_sources": skipped_sources,
            "output_dir": str(settings.app.output_dir),
            "cache_dir": str(settings.app.cache_dir),
            "x_enabled": settings.x.enable,
            "x_configured": settings.x.configured,
            "instagram_enabled": settings.instagram.enable,
            "instagram_authenticated": settings.instagram.authenticated,
            "tiktok_enabled": settings.tiktok.enable,
        },
        "results": results,
        "merged": {
            "count": len(merged_serialized),
            "items": merged_serialized,
        },
        "synthesis": synthesis,
    }


def build_payload(args: argparse.Namespace, settings: Settings) -> dict[str, Any]:
    raw_query = normalize_spaces(" ".join(args.query))
    return build_payload_for_query(
        raw_query=raw_query,
        settings=settings,
        days=args.days,
        tool=args.tool,
        sources=args.source,
        filters=args.filters,
        per_source_limit=args.per_source_limit,
        quick=args.quick,
        deep=args.deep,
        literal=getattr(args, "literal", False),
    )


def save_payload_artifacts(
    *,
    settings: Settings,
    payload: dict[str, Any],
    raw_query: str,
    argv_list: list[str],
) -> dict[str, Any]:
    run_dir = create_run_dir(settings.app.output_dir, payload["intent"]["topic"])
    artifacts = write_run_outputs(
        run_dir=run_dir,
        payload=payload,
        raw_query=raw_query,
        argv=argv_list,
    )
    payload["artifacts"] = artifacts

    manifest = read_manifest(Path(artifacts["manifest_path"]))
    if manifest is not None:
        payload["index_entry"] = update_run_index(settings.app.output_dir, manifest)
        payload["index_path"] = str(index_path(settings.app.output_dir))

    return payload


def run_watchlist_entries(settings: Settings, entries: list[dict[str, Any]], *, output_dir: Path) -> list[dict[str, Any]]:
    results = []

    for entry in entries:
        depth = str(entry.get("depth", "balanced") or "balanced")
        quick = depth == "quick"
        deep = depth == "deep"

        raw_query = str(entry.get("query", "") or "").strip()
        payload = build_payload_for_query(
            raw_query=raw_query,
            settings=settings,
            days=int(entry.get("days", settings.app.default_days) or settings.app.default_days),
            tool=str(entry.get("target_tool", "unknown") or "unknown"),
            sources=list(entry.get("sources", []) or []),
            quick=quick,
            deep=deep,
        )

        payload = save_payload_artifacts(
            settings=settings,
            payload=payload,
            raw_query=raw_query,
            argv_list=["watchlist", "run", str(entry.get("id", ""))],
        )

        artifacts = payload.get("artifacts", {})
        results.append(
            {
                "id": entry.get("id"),
                "query": raw_query,
                "status": payload.get("status"),
                "merged_items": payload.get("merged", {}).get("count", 0),
                "run_id": payload.get("index_entry", {}).get("run_id", ""),
                "run_dir": artifacts.get("run_dir", ""),
                "report_path": artifacts.get("report_path", ""),
                "selected_sources": payload.get("runtime", {}).get("selected_sources", []),
            }
        )

    return results


def render_pretty(payload: dict[str, Any], *, results_limit: int = 0) -> None:
    console = Console()

    console.print(
        Panel.fit(
            "[bold green]last30free[/bold green]\n"
            "Live fetch and first-pass synthesis are working.\n"
            "Saved report artifacts are available with --save.",
            title="Runtime status",
        )
    )

    intent = payload["intent"]
    runtime = payload["runtime"]

    summary_table = Table(show_header=False, box=None, pad_edge=False)
    summary_table.add_row("TOPIC", str(intent["topic"]))
    summary_table.add_row("TARGET_TOOL", str(intent["target_tool"]))
    summary_table.add_row("QUERY_TYPE", str(intent["query_type"]))
    summary_table.add_row("DAYS", str(runtime["days"]))
    summary_table.add_row("DEPTH", str(runtime["depth"]))
    summary_table.add_row("LIMIT PER SOURCE", str(runtime["limit_per_source"]))
    summary_table.add_row("SELECTED SOURCES", ", ".join(runtime["selected_sources"]) or "(none)")
    summary_table.add_row(
        "IMPLEMENTED NOW",
        ", ".join(runtime["implemented_selected_sources"]) or "(none)",
    )
    if runtime["skipped_sources"]:
        summary_table.add_row("SKIPPED SOURCES", ", ".join(runtime["skipped_sources"]))
    summary_table.add_row("X ENABLED", str(runtime["x_enabled"]))
    summary_table.add_row("X CONFIGURED", str(runtime["x_configured"]))
    summary_table.add_row("INSTAGRAM AUTHENTICATED", str(runtime.get("instagram_authenticated", False)))
    console.print(summary_table)
    console.print()

    source_table = Table(title="Source execution")
    source_table.add_column("Source")
    source_table.add_column("Status")
    source_table.add_column("Count", justify="right")
    source_table.add_column("Error")

    for source_name in ("reddit", "hn", "youtube", "x", "instagram", "tiktok", "facebook"):
        result = payload["results"].get(source_name)
        if result is None:
            continue
        source_table.add_row(
            source_name,
            result["status"],
            str(result["count"]),
            result["error"] or "",
        )

    console.print(source_table)
    console.print()

    synthesis = payload["synthesis"]
    console.print(Panel.fit(synthesis["headline"], title="What I learned"))

    summary_points = synthesis.get("summary_points", [])
    if summary_points:
        console.print()
        console.print("[bold]Key takeaways[/bold]")
        for point in summary_points:
            console.print(f"• {point}")

    patterns = synthesis.get("patterns", [])
    if patterns:
        console.print()
        pattern_table = Table(title="Recurring patterns")
        pattern_table.add_column("Keyword")
        pattern_table.add_column("Mentions", justify="right")
        pattern_table.add_column("Sources", justify="right")
        pattern_table.add_column("Examples")

        for pattern in patterns:
            pattern_table.add_row(
                pattern["keyword"],
                str(pattern["mentions"]),
                str(pattern["source_count"]),
                " | ".join(pattern["examples"][:2]),
            )

        console.print(pattern_table)

    source_stats = synthesis.get("source_stats", [])
    if source_stats:
        console.print()
        stats_table = Table(title="Source stats")
        stats_table.add_column("Source")
        stats_table.add_column("Items", justify="right")
        stats_table.add_column("Metric 1")
        stats_table.add_column("Metric 2")
        stats_table.add_column("Metric 3")

        for row in source_stats:
            metric_1 = f"{row['label_1']}: {row['total_1']}"
            metric_2 = f"{row['label_2']}: {row['total_2']}"
            metric_3 = ""
            if "label_3" in row:
                metric_3 = f"{row['label_3']}: {row['total_3']}"

            stats_table.add_row(
                row["source"],
                str(row["count"]),
                metric_1,
                metric_2,
                metric_3,
            )

        console.print(stats_table)

    console.print()

    merged = payload["merged"]
    items = merged["items"]

    if not items:
        console.print("[yellow]No merged results found in the requested time window.[/yellow]")
        return

    merged_table = Table(title="Merged top discussions")
    merged_table.add_column("#", justify="right")
    merged_table.add_column("Source")
    merged_table.add_column("Community")
    merged_table.add_column("Signal")
    merged_table.add_column("Score", justify="right")
    merged_table.add_column("Title")

    for idx, item in enumerate(items if results_limit == 0 else items[:results_limit], start=1):
        created_at = item.get("created_at", "")
        date_str = created_at[:10] if created_at else ""
        url = item.get("url", "")
        meta_line = f"[dim]{date_str}  {url}[/dim]" if date_str or url else ""
        title_cell = item["title"] + (f"\n{meta_line}" if meta_line else "")
        merged_table.add_row(
            str(idx),
            item["source"],
            summarize_item_community(item),
            summarize_item_signal(item),
            f"{item['score']:.2f}",
            title_cell,
        )

    console.print(merged_table)

    # Print full URLs in plain text so they are never truncated by the table renderer
    urls_with_index = [
        (i, item.get("url", ""))
        for i, item in enumerate(items if results_limit == 0 else items[:results_limit], start=1)
        if item.get("url")
    ]
    if urls_with_index:
        console.print()
        console.print("[bold]Full URLs[/bold]")
        for idx, url in urls_with_index:
            console.print(f"  {idx:>3}. {url}")

    top_with_quote = next((item for item in items if item.get("quotes")), None)
    if top_with_quote:
        quote = top_with_quote["quotes"][0]
        console.print()
        console.print(
            Panel.fit(
                f"{quote['text']}\n\n"
                f"[bold]— {quote.get('author') or 'unknown'}[/bold] "
                f"({quote.get('source_label') or top_with_quote['source']})",
                title="Sample extracted quote",
            )
        )


def render_runs_list(entries: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not entries:
        console.print(
            Panel.fit(
                f"No saved runs found.\nIndex path: {index_path(output_dir)}",
                title="Saved runs",
            )
        )
        return

    table = Table(title="Saved runs")
    table.add_column("Run ID")
    table.add_column("Generated")
    table.add_column("Topic")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Items", justify="right")
    table.add_column("Sources")

    for entry in entries:
        sources = ", ".join(entry.get("selected_sources", []) or [])
        table.add_row(
            str(entry.get("run_id", "")),
            str(entry.get("generated_at_utc", "")),
            str(entry.get("topic", "")),
            str(entry.get("query_type", "")),
            str(entry.get("status", "")),
            str(entry.get("merged_items", 0)),
            sources,
        )

    console.print(table)
    console.print()
    console.print(f"Index path: {index_path(output_dir)}")


def render_latest_runs(entries: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not entries:
        console.print(
            Panel.fit(
                f"No latest runs found.\nIndex path: {index_path(output_dir)}",
                title="Latest runs by topic",
            )
        )
        return

    table = Table(title="Latest runs by topic")
    table.add_column("Topic")
    table.add_column("Run ID")
    table.add_column("Generated")
    table.add_column("Status")
    table.add_column("Items", justify="right")
    table.add_column("Sources")

    for entry in entries:
        table.add_row(
            str(entry.get("topic", "")),
            str(entry.get("run_id", "")),
            str(entry.get("generated_at_utc", "")),
            str(entry.get("status", "")),
            str(entry.get("merged_items", 0)),
            ", ".join(entry.get("selected_sources", []) or []),
        )

    console.print(table)
    console.print()
    console.print(f"Index path: {index_path(output_dir)}")


def render_saved_run(manifest: dict[str, Any]) -> None:
    console = Console()
    files = manifest.get("files", {})
    runtime = manifest.get("runtime", {})

    summary = Table(show_header=False, box=None, pad_edge=False)
    summary.add_row("RUN ID", str(manifest.get("run_id", "")))
    summary.add_row("GENERATED", str(manifest.get("generated_at_utc", "")))
    summary.add_row("TOPIC", str(manifest.get("topic", "")))
    summary.add_row("QUERY TYPE", str(manifest.get("query_type", "")))
    summary.add_row("STATUS", str(manifest.get("status", "")))
    summary.add_row("SOURCES", ", ".join(runtime.get("selected_sources", []) or []))
    summary.add_row("REPORT", str(files.get("report_path", "")))
    summary.add_row("MANIFEST", str(files.get("manifest_path", "")))

    console.print(Panel.fit(summary, title="Saved run"))
    console.print()

    report_path = Path(str(files.get("report_path", "") or ""))
    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")
        console.print(Markdown(report_text))
        return

    console.print("[yellow]Report file not found for this saved run.[/yellow]")


def render_comparison(comparison: dict[str, Any]) -> None:
    console = Console()
    summary = comparison.get("summary", {})
    earlier = comparison.get("earlier_run", {})
    later = comparison.get("later_run", {})

    header = Table(show_header=False, box=None, pad_edge=False)
    header.add_row("EARLIER", f"{earlier.get('run_id', '')} ({earlier.get('generated_at_utc', '')})")
    header.add_row("LATER", f"{later.get('run_id', '')} ({later.get('generated_at_utc', '')})")
    header.add_row("TOPIC", str(later.get("topic") or earlier.get("topic") or ""))

    console.print(Panel.fit(header, title="Run comparison"))
    console.print()
    console.print(Panel.fit(str(summary.get("headline", "")), title="Change summary"))

    bullet_points = summary.get("bullet_points", [])
    if bullet_points:
        console.print()
        console.print("[bold]Key changes[/bold]")
        for point in bullet_points:
            console.print(f"• {point}")

    source_counts = comparison.get("source_counts", [])
    if source_counts:
        console.print()
        source_table = Table(title="Source count changes")
        source_table.add_column("Source")
        source_table.add_column("Earlier", justify="right")
        source_table.add_column("Later", justify="right")
        source_table.add_column("Delta", justify="right")
        for row in source_counts:
            source_table.add_row(
                row["source"],
                str(row["earlier_count"]),
                str(row["later_count"]),
                f"{row['delta']:+d}",
            )
        console.print(source_table)

    keyword_changes = comparison.get("keyword_changes", [])
    if keyword_changes:
        console.print()
        kw_table = Table(title="Keyword changes")
        kw_table.add_column("Keyword")
        kw_table.add_column("Earlier", justify="right")
        kw_table.add_column("Later", justify="right")
        kw_table.add_column("Delta", justify="right")
        for row in keyword_changes[:10]:
            kw_table.add_row(
                row["keyword"],
                str(row["earlier_mentions"]),
                str(row["later_mentions"]),
                f"{row['delta']:+d}",
            )
        console.print(kw_table)

    added_items = comparison.get("added_items", [])
    if added_items:
        console.print()
        added_table = Table(title="New items in later run")
        added_table.add_column("Source")
        added_table.add_column("Title")
        for item in added_items:
            added_table.add_row(str(item.get("source", "")), str(item.get("title", "")))
        console.print(added_table)

    removed_items = comparison.get("removed_items", [])
    if removed_items:
        console.print()
        removed_table = Table(title="Items no longer present")
        removed_table.add_column("Source")
        removed_table.add_column("Title")
        for item in removed_items:
            removed_table.add_row(str(item.get("source", "")), str(item.get("title", "")))
        console.print(removed_table)

    score_changes = comparison.get("score_changes", [])
    if score_changes:
        console.print()
        score_table = Table(title="Biggest score changes")
        score_table.add_column("Source")
        score_table.add_column("Title")
        score_table.add_column("Earlier", justify="right")
        score_table.add_column("Later", justify="right")
        score_table.add_column("Delta", justify="right")
        for item in score_changes:
            score_table.add_row(
                str(item.get("source", "")),
                str(item.get("title", "")),
                f"{float(item.get('earlier_score', 0)):.2f}",
                f"{float(item.get('later_score', 0)):.2f}",
                f"{float(item.get('delta', 0)):+.2f}",
            )
        console.print(score_table)


def render_alert_report(report: dict[str, Any]) -> None:
    console = Console()
    comparison = report.get("comparison", {})
    earlier = comparison.get("earlier_run", {})
    later = comparison.get("later_run", {})
    summary = report.get("summary", {})

    header = Table(show_header=False, box=None, pad_edge=False)
    header.add_row("TOPIC", str(report.get("topic", "")))
    header.add_row("STATUS", str(report.get("status", "")))
    header.add_row("EARLIER", f"{earlier.get('run_id', '')} ({earlier.get('generated_at_utc', '')})")
    header.add_row("LATER", f"{later.get('run_id', '')} ({later.get('generated_at_utc', '')})")

    console.print(Panel.fit(header, title="Alert evaluation"))
    console.print()
    console.print(Panel.fit(str(summary.get("headline", "")), title="Alert summary"))

    rules = report.get("rules", [])
    if rules:
        console.print()
        table = Table(title="Alert rules")
        table.add_column("Rule")
        table.add_column("Triggered")
        table.add_column("Severity")
        table.add_column("Message")

        for rule in rules:
            table.add_row(
                str(rule.get("rule_id", "")),
                "yes" if rule.get("triggered") else "no",
                str(rule.get("severity", "")),
                str(rule.get("message", "")),
            )
        console.print(table)


def render_alert_reports_overview(reports: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not reports:
        console.print(
            Panel.fit(
                f"No alert comparisons available.\nIndex path: {index_path(output_dir)}",
                title="Alerts overview",
            )
        )
        return

    table = Table(title="Alerts overview")
    table.add_column("Topic")
    table.add_column("Status")
    table.add_column("Triggered", justify="right")
    table.add_column("Earlier")
    table.add_column("Later")
    table.add_column("Headline")

    for report in reports:
        comparison = report.get("comparison", {})
        summary = report.get("summary", {})
        table.add_row(
            str(report.get("topic", "")),
            str(report.get("status", "")),
            str(summary.get("triggered_rules", 0)),
            str(comparison.get("earlier_run", {}).get("run_id", "")),
            str(comparison.get("later_run", {}).get("run_id", "")),
            str(summary.get("headline", "")),
        )

    console.print(table)
    console.print()
    console.print(f"Index path: {index_path(output_dir)}")


def render_notification_bundle(bundle: dict[str, Any]) -> None:
    console = Console()
    summary = bundle.get("summary", {})

    header = Table(show_header=False, box=None, pad_edge=False)
    header.add_row("TOPIC", str(bundle.get("topic", "")))
    header.add_row("STATUS", str(bundle.get("status", "")))
    header.add_row("CHANNELS", ", ".join(bundle.get("channels", []) or []))
    header.add_row("TRIGGERED RULES", str(summary.get("triggered_rules", 0)))

    console.print(Panel.fit(header, title="Notification payloads"))
    console.print()
    console.print(Panel.fit(str(summary.get("headline", "")), title="Notification summary"))

    payloads = bundle.get("payloads", {})

    email_payload = payloads.get("email")
    if email_payload:
        console.print()
        email_table = Table(title="Email payload")
        email_table.add_column("Field")
        email_table.add_column("Value")
        email_table.add_row("subject", str(email_payload.get("subject", "")))
        email_table.add_row("body_text", str(email_payload.get("body_text", "")))
        console.print(email_table)

    webhook_payload = payloads.get("webhook")
    if webhook_payload:
        console.print()
        webhook_table = Table(title="Webhook payload")
        webhook_table.add_column("Field")
        webhook_table.add_column("Value")
        webhook_table.add_row("event_type", str(webhook_payload.get("event_type", "")))
        webhook_table.add_row("topic", str(webhook_payload.get("topic", "")))
        webhook_table.add_row("status", str(webhook_payload.get("status", "")))
        webhook_table.add_row("headline", str(webhook_payload.get("headline", "")))
        console.print(webhook_table)


def render_notification_overview(rows: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not rows:
        console.print(
            Panel.fit(
                f"No notification payloads available.\nIndex path: {index_path(output_dir)}",
                title="Notification overview",
            )
        )
        return

    table = Table(title="Notification payload overview")
    table.add_column("Topic")
    table.add_column("Status")
    table.add_column("Channels")
    table.add_column("Triggered", justify="right")
    table.add_column("Headline")

    for row in rows:
        summary = row.get("summary", {})
        table.add_row(
            str(row.get("topic", "")),
            str(row.get("status", "")),
            ", ".join(row.get("channels", []) or []),
            str(summary.get("triggered_rules", 0)),
            str(summary.get("headline", "")),
        )

    console.print(table)
    console.print()
    console.print(f"Index path: {index_path(output_dir)}")


def render_notification_snapshots(entries: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not entries:
        console.print(
            Panel.fit(
                f"No notification snapshots found.\nIndex path: {notification_index_path(output_dir)}",
                title="Notification history",
            )
        )
        return

    table = Table(title="Notification snapshot history")
    table.add_column("Topic")
    table.add_column("Snapshot ID")
    table.add_column("Generated")
    table.add_column("Status")
    table.add_column("Triggered", justify="right")
    table.add_column("Channels")

    for entry in entries:
        table.add_row(
            str(entry.get("topic", "")),
            str(entry.get("snapshot_id", "")),
            str(entry.get("generated_at_utc", "")),
            str(entry.get("status", "")),
            str(entry.get("triggered_rules", 0)),
            ", ".join(entry.get("channels", []) or []),
        )

    console.print(table)
    console.print()
    console.print(f"Index path: {notification_index_path(output_dir)}")


def render_saved_notification_artifacts(saved: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not saved:
        return

    table = Table(title="Saved notification snapshots")
    table.add_column("Topic")
    table.add_column("Snapshot ID")
    table.add_column("Snapshot Dir")
    table.add_column("Manifest")

    for row in saved:
        entry = row.get("index_entry", {})
        table.add_row(
            str(entry.get("topic", "")),
            str(entry.get("snapshot_id", "")),
            str(row.get("snapshot_dir", "")),
            str(row.get("manifest_path", "")),
        )

    console.print()
    console.print(table)
    console.print(f"Notification index: {notification_index_path(output_dir)}")


def render_watchlist_topics(payload: dict[str, Any]) -> None:
    console = Console()
    path = payload["watchlist_path"]
    topics = payload["topics"]

    if not topics:
        console.print(
            Panel.fit(
                f"No topics found in watchlist.\nPath: {path}",
                title="Watchlist",
            )
        )
        return

    table = Table(title="Watchlist topics")
    table.add_column("ID")
    table.add_column("Enabled")
    table.add_column("Days", justify="right")
    table.add_column("Depth")
    table.add_column("Sources")
    table.add_column("Query")

    for topic in topics:
        table.add_row(
            str(topic.get("id", "")),
            "yes" if topic.get("enabled") else "no",
            str(topic.get("days", 30)),
            str(topic.get("depth", "balanced")),
            ", ".join(topic.get("sources", []) or []),
            str(topic.get("query", "")),
        )

    console.print(table)
    console.print()
    console.print(f"Watchlist path: {path}")


def render_watchlist_payloads(payload: dict[str, Any]) -> None:
    console = Console()
    rows = payload["payloads"]

    if not rows:
        console.print(
            Panel.fit(
                f"No enabled watchlist payloads found.\nPath: {payload['watchlist_path']}",
                title="Watchlist payloads",
            )
        )
        return

    table = Table(title="Watchlist runner payloads")
    table.add_column("ID")
    table.add_column("Depth")
    table.add_column("Days", justify="right")
    table.add_column("Sources")
    table.add_column("Command")

    for row in rows:
        table.add_row(
            str(row.get("topic_id", "")),
            str(row.get("depth", "")),
            str(row.get("days", "")),
            ", ".join(row.get("sources", []) or []),
            str(row.get("command_string", "")),
        )

    console.print(table)
    console.print()
    console.print(f"Watchlist path: {payload['watchlist_path']}")


def render_watchlist_run_results(payload: dict[str, Any]) -> None:
    console = Console()
    results = payload["results"]

    if not results:
        console.print(
            Panel.fit(
                f"No watchlist topics were executed.\nPath: {payload['watchlist_path']}",
                title="Watchlist run",
            )
        )
        return

    table = Table(title="Watchlist batch run")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Items", justify="right")
    table.add_column("Run ID")
    table.add_column("Sources")
    table.add_column("Query")

    for row in results:
        table.add_row(
            str(row.get("id", "")),
            str(row.get("status", "")),
            str(row.get("merged_items", 0)),
            str(row.get("run_id", "")),
            ", ".join(row.get("selected_sources", []) or []),
            str(row.get("query", "")),
        )

    console.print(table)
    console.print()
    console.print(f"Watchlist path: {payload['watchlist_path']}")
    console.print(f"Index path: {payload['index_path']}")


def handle_runs_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_runs_parser()
    args = parser.parse_args(list(argv))
    entries = list_saved_runs(settings.app.output_dir, limit=args.limit)

    if args.json:
        print(
            json.dumps(
                {
                    "output_dir": str(settings.app.output_dir),
                    "index_path": str(index_path(settings.app.output_dir)),
                    "count": len(entries),
                    "entries": entries,
                },
                indent=2,
            )
        )
        return 0

    render_runs_list(entries, output_dir=settings.app.output_dir)
    return 0


def handle_show_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_show_parser()
    args = parser.parse_args(list(argv))

    manifest = resolve_saved_run(settings.app.output_dir, args.run_ref)
    if manifest is None:
        if args.json:
            print(
                json.dumps(
                    {
                        "error": f"No saved run found for reference: {args.run_ref}",
                        "output_dir": str(settings.app.output_dir),
                        "index_path": str(index_path(settings.app.output_dir)),
                    },
                    indent=2,
                )
            )
        else:
            console = Console()
            console.print(f"[bold red]No saved run found for reference:[/bold red] {args.run_ref}")
            console.print(f"Index path: {index_path(settings.app.output_dir)}")
        return 1

    report_path = Path(str(manifest.get("files", {}).get("report_path", "") or ""))
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""

    if args.json:
        print(
            json.dumps(
                {
                    "manifest": manifest,
                    "report_markdown": report_text,
                },
                indent=2,
            )
        )
        return 0

    render_saved_run(manifest)
    return 0


def handle_compare_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_compare_parser()
    args = parser.parse_args(list(argv))

    earlier_manifest = resolve_saved_run(settings.app.output_dir, args.earlier_ref)
    later_manifest = resolve_saved_run(settings.app.output_dir, args.later_ref)

    if earlier_manifest is None or later_manifest is None:
        missing = []
        if earlier_manifest is None:
            missing.append(f"earlier={args.earlier_ref}")
        if later_manifest is None:
            missing.append(f"later={args.later_ref}")
        message = f"Could not resolve saved run(s): {', '.join(missing)}"

        if args.json:
            print(
                json.dumps(
                    {
                        "error": message,
                        "output_dir": str(settings.app.output_dir),
                        "index_path": str(index_path(settings.app.output_dir)),
                    },
                    indent=2,
                )
            )
        else:
            console = Console()
            console.print(f"[bold red]{message}[/bold red]")
            console.print(f"Index path: {index_path(settings.app.output_dir)}")
        return 1

    earlier_payload = load_payload_from_manifest(earlier_manifest)
    later_payload = load_payload_from_manifest(later_manifest)

    if earlier_payload is None or later_payload is None:
        message = "One or both saved runs are missing readable payload files."

        if args.json:
            print(json.dumps({"error": message}, indent=2))
        else:
            console = Console()
            console.print(f"[bold red]{message}[/bold red]")
        return 1

    comparison = compare_payloads(
        earlier_payload,
        later_payload,
        earlier_manifest=earlier_manifest,
        later_manifest=later_manifest,
    )

    comparison["comparison_markdown"] = render_comparison_markdown(comparison)

    if args.json:
        print(json.dumps(comparison, indent=2))
        return 0

    render_comparison(comparison)
    return 0


def handle_latest_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_latest_parser()
    args = parser.parse_args(list(argv))

    if args.topic_ref:
        entry = latest_run_for_topic(settings.app.output_dir, args.topic_ref)
        if entry is None:
            payload = {
                "error": f"No latest run found for topic reference: {args.topic_ref}",
                "output_dir": str(settings.app.output_dir),
                "index_path": str(index_path(settings.app.output_dir)),
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{payload['error']}[/bold red]")
                console.print(f"Index path: {payload['index_path']}")
            return 1

        if args.json:
            print(
                json.dumps(
                    {
                        "output_dir": str(settings.app.output_dir),
                        "index_path": str(index_path(settings.app.output_dir)),
                        "entry": entry,
                    },
                    indent=2,
                )
            )
            return 0

        render_latest_runs([entry], output_dir=settings.app.output_dir)
        return 0

    entries = latest_runs_by_topic(settings.app.output_dir, limit=args.limit)

    if args.json:
        print(
            json.dumps(
                {
                    "output_dir": str(settings.app.output_dir),
                    "index_path": str(index_path(settings.app.output_dir)),
                    "count": len(entries),
                    "entries": entries,
                },
                indent=2,
            )
        )
        return 0

    render_latest_runs(entries, output_dir=settings.app.output_dir)
    return 0


def handle_alerts_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_alerts_parser()
    args = parser.parse_args(list(argv))

    thresholds = {
        "new_item_threshold": args.new_item_threshold,
        "source_spike_threshold": args.source_spike_threshold,
        "keyword_spike_threshold": args.keyword_spike_threshold,
    }

    if args.topic_ref:
        topic_runs = runs_for_topic(settings.app.output_dir, args.topic_ref, limit=2)
        if len(topic_runs) < 2:
            payload = {
                "error": f"Need at least two saved runs for topic reference: {args.topic_ref}",
                "output_dir": str(settings.app.output_dir),
                "index_path": str(index_path(settings.app.output_dir)),
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{payload['error']}[/bold red]")
                console.print(f"Index path: {payload['index_path']}")
            return 1

        later_manifest = read_manifest(Path(str(topic_runs[0]["manifest_path"])))
        earlier_manifest = read_manifest(Path(str(topic_runs[1]["manifest_path"])))
        if later_manifest is None or earlier_manifest is None:
            message = "One or both alert manifests could not be read."
            if args.json:
                print(json.dumps({"error": message}, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{message}[/bold red]")
            return 1

        report = build_alert_report_from_manifests(
            earlier_manifest,
            later_manifest,
            **thresholds,
        )

        if args.json:
            print(json.dumps(report, indent=2))
            return 0

        render_alert_report(report)
        return 0

    latest_entries = latest_runs_by_topic(settings.app.output_dir, limit=args.limit)
    reports = []

    for entry in latest_entries:
        topic_runs = runs_for_topic(settings.app.output_dir, str(entry.get("topic", "")), limit=2)
        if len(topic_runs) < 2:
            continue

        later_manifest = read_manifest(Path(str(topic_runs[0]["manifest_path"])))
        earlier_manifest = read_manifest(Path(str(topic_runs[1]["manifest_path"])))
        if later_manifest is None or earlier_manifest is None:
            continue

        report = build_alert_report_from_manifests(
            earlier_manifest,
            later_manifest,
            **thresholds,
        )
        reports.append(report)

    if args.json:
        print(
            json.dumps(
                {
                    "output_dir": str(settings.app.output_dir),
                    "index_path": str(index_path(settings.app.output_dir)),
                    "count": len(reports),
                    "reports": reports,
                },
                indent=2,
            )
        )
        return 0

    render_alert_reports_overview(reports, output_dir=settings.app.output_dir)
    return 0


def handle_notify_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_notify_parser()
    args = parser.parse_args(list(argv))

    thresholds = {
        "new_item_threshold": args.new_item_threshold,
        "source_spike_threshold": args.source_spike_threshold,
        "keyword_spike_threshold": args.keyword_spike_threshold,
    }
    channels = list(args.channel) if args.channel else None

    if args.topic_ref:
        topic_runs = runs_for_topic(settings.app.output_dir, args.topic_ref, limit=2)
        if len(topic_runs) < 2:
            payload = {
                "error": f"Need at least two saved runs for topic reference: {args.topic_ref}",
                "output_dir": str(settings.app.output_dir),
                "index_path": str(index_path(settings.app.output_dir)),
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{payload['error']}[/bold red]")
                console.print(f"Index path: {payload['index_path']}")
            return 1

        later_manifest = read_manifest(Path(str(topic_runs[0]["manifest_path"])))
        earlier_manifest = read_manifest(Path(str(topic_runs[1]["manifest_path"])))
        if later_manifest is None or earlier_manifest is None:
            message = "One or both notification manifests could not be read."
            if args.json:
                print(json.dumps({"error": message}, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{message}[/bold red]")
            return 1

        alert_report = build_alert_report_from_manifests(
            earlier_manifest,
            later_manifest,
            **thresholds,
        )
        bundle = build_notification_bundle(alert_report, channels=channels)

        saved = []
        if args.save:
            saved.append(write_notification_bundle(settings.app.output_dir, bundle))

        if args.json:
            payload = {"bundle": bundle}
            if saved:
                payload["saved"] = saved
            print(json.dumps(payload, indent=2))
            return 0

        render_notification_bundle(bundle)
        if saved:
            render_saved_notification_artifacts(saved, output_dir=settings.app.output_dir)
        return 0

    latest_entries = latest_runs_by_topic(settings.app.output_dir, limit=args.limit)
    bundles = []

    for entry in latest_entries:
        topic_runs = runs_for_topic(settings.app.output_dir, str(entry.get("topic", "")), limit=2)
        if len(topic_runs) < 2:
            continue

        later_manifest = read_manifest(Path(str(topic_runs[0]["manifest_path"])))
        earlier_manifest = read_manifest(Path(str(topic_runs[1]["manifest_path"])))
        if later_manifest is None or earlier_manifest is None:
            continue

        alert_report = build_alert_report_from_manifests(
            earlier_manifest,
            later_manifest,
            **thresholds,
        )
        bundles.append(build_notification_bundle(alert_report, channels=channels))

    saved = []
    if args.save:
        for bundle in bundles:
            saved.append(write_notification_bundle(settings.app.output_dir, bundle))

    if args.json:
        payload = {
            "output_dir": str(settings.app.output_dir),
            "index_path": str(index_path(settings.app.output_dir)),
            "notification_index_path": str(notification_index_path(settings.app.output_dir)),
            "count": len(bundles),
            "bundles": bundles,
        }
        if saved:
            payload["saved"] = saved
        print(json.dumps(payload, indent=2))
        return 0

    render_notification_overview(bundles, output_dir=settings.app.output_dir)
    if saved:
        render_saved_notification_artifacts(saved, output_dir=settings.app.output_dir)
    return 0


def handle_notify_history_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_notify_history_parser()
    args = parser.parse_args(list(argv))

    entries = list_notification_snapshots(
        settings.app.output_dir,
        topic_ref=args.topic_ref,
        limit=args.limit,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "output_dir": str(settings.app.output_dir),
                    "notification_index_path": str(notification_index_path(settings.app.output_dir)),
                    "count": len(entries),
                    "entries": entries,
                },
                indent=2,
            )
        )
        return 0

    render_notification_snapshots(entries, output_dir=settings.app.output_dir)
    return 0


def handle_watchlist_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_watchlist_parser()
    args = parser.parse_args(list(argv))
    path = watchlist_path(settings.app.output_dir)

    if args.watchlist_command == "init":
        created_path, created = init_watchlist(settings.app.output_dir, overwrite=args.overwrite)
        payload = {
            "watchlist_path": str(created_path),
            "created": created,
            "overwrite": bool(args.overwrite),
        }

        if args.json:
            print(json.dumps(payload, indent=2))
            return 0

        console = Console()
        title = "Watchlist created" if created else "Watchlist already exists"
        console.print(
            Panel.fit(
                f"Path: {created_path}\nOverwrite requested: {bool(args.overwrite)}",
                title=title,
            )
        )
        return 0

    if args.watchlist_command == "show":
        watchlist = load_watchlist(settings.app.output_dir)
        payload = {
            "watchlist_path": str(path),
            "topics": watchlist.get("topics", []),
        }

        if args.json:
            print(json.dumps(payload, indent=2))
            return 0

        render_watchlist_topics(payload)
        return 0

    if args.watchlist_command == "payloads":
        payloads = build_watchlist_runner_payloads(
            settings.app.output_dir,
            refs=list(args.topic_refs),
            enabled_only=True,
        )
        payload = {
            "watchlist_path": str(path),
            "count": len(payloads),
            "payloads": payloads,
        }

        if args.json:
            print(json.dumps(payload, indent=2))
            return 0

        render_watchlist_payloads(payload)
        return 0

    if args.watchlist_command == "run":
        selected_topics = resolve_watch_topics(
            settings.app.output_dir,
            refs=list(args.topic_refs),
            enabled_only=True,
        )

        if not selected_topics:
            message = "No enabled watchlist topics matched."
            payload = {
                "error": message,
                "watchlist_path": str(path),
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{message}[/bold red]")
                console.print(f"Watchlist path: {path}")
            return 1

        if args.dry_run:
            payload = {
                "watchlist_path": str(path),
                "topics": selected_topics,
                "dry_run": True,
            }
            if args.json:
                print(json.dumps(payload, indent=2))
                return 0

            render_watchlist_topics(payload)
            return 0

        batch_results = run_watchlist_entries(
            settings,
            selected_topics,
            output_dir=settings.app.output_dir,
        )
        payload = {
            "watchlist_path": str(path),
            "index_path": str(index_path(settings.app.output_dir)),
            "count": len(batch_results),
            "results": batch_results,
        }

        if args.json:
            print(json.dumps(payload, indent=2))
            return 0

        render_watchlist_run_results(payload)
        return 0

    return 1


def build_generate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free generate",
        description="Generate social/video content from saved research using Claude.",
    )
    parser.add_argument(
        "--format",
        required=True,
        choices=list_formats(),
        help="Content format to generate",
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--run-id", dest="run_id", help="Run ID of a saved research run")
    source_group.add_argument("--latest", dest="latest_topic", metavar="TOPIC", nargs="?", const="", help="Use the latest saved run (optionally for a specific topic)")

    parser.add_argument("--save", action="store_true", help="Save generated content to the run directory")
    return parser


def handle_generate_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_generate_parser()
    args = parser.parse_args(list(argv))
    console = Console()

    # Resolve manifest
    manifest: dict[str, Any] | None = None
    if args.run_id:
        manifest = resolve_saved_run(settings.app.output_dir, args.run_id)
        if manifest is None:
            console.print(f"[bold red]No saved run found for run-id:[/bold red] {args.run_id}")
            return 1
    else:
        topic_ref = args.latest_topic or ""
        if topic_ref:
            entry = latest_run_for_topic(settings.app.output_dir, topic_ref)
        else:
            entries = latest_runs_by_topic(settings.app.output_dir, limit=1)
            entry = entries[0] if entries else None
        if entry is None:
            msg = f"No saved run found for topic: {topic_ref}" if topic_ref else "No saved runs found. Run a query with --save first."
            console.print(f"[bold red]{msg}[/bold red]")
            return 1
        manifest = resolve_saved_run(settings.app.output_dir, str(entry.get("run_id", "")))
        if manifest is None:
            console.print("[bold red]Could not load manifest for the latest run.[/bold red]")
            return 1

    # Load payload
    files = manifest.get("files", {})
    payload_path = Path(str(files.get("payload_path", "") or ""))
    if not payload_path.exists():
        console.print(f"[bold red]Payload file not found:[/bold red] {payload_path}")
        return 1

    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        console.print(f"[bold red]Failed to read payload:[/bold red] {exc}")
        return 1

    topic = str(manifest.get("topic", "") or "")
    run_id = str(manifest.get("run_id", "") or "")

    console.print()
    console.print(
        Panel.fit(
            f"Topic: {topic}\nRun ID: {run_id}\nFormat: {args.format}\nModel: claude-opus-4-6",
            title="Generating content",
        )
    )
    console.print()

    save_path: Path | None = None
    if args.save:
        run_dir = Path(str(files.get("run_dir", "") or ""))
        if run_dir:
            save_path = run_dir / f"generated_{args.format.replace('-', '_')}.md"

    try:
        generate(
            payload=payload,
            format_name=args.format,
            save_path=save_path,
        )
    except GeneratorError as exc:
        console.print(f"\n[bold red]Generation failed:[/bold red] {exc}")
        return 1

    if save_path:
        console.print()
        console.print(f"[green]Saved to:[/green] {save_path}")

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]

    settings = load_settings()
    settings.ensure_directories()

    if argv_list and argv_list[0] == "runs":
        return handle_runs_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "show":
        return handle_show_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "compare":
        return handle_compare_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "latest":
        return handle_latest_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "alerts":
        return handle_alerts_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "notify":
        return handle_notify_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "notify-history":
        return handle_notify_history_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "watchlist":
        return handle_watchlist_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "generate":
        return handle_generate_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "dashboard":
        import subprocess
        dashboard_path = Path(__file__).parent / "dashboard.py"
        extra = argv_list[1:]  # pass through e.g. --server.port 8502
        cmd = [sys.executable, "-m", "streamlit", "run", str(dashboard_path)] + list(extra)
        raise SystemExit(subprocess.call(cmd))

    parser = build_parser()
    args = parser.parse_args(argv_list)

    raw_query = normalize_spaces(" ".join(args.query))
    payload = build_payload(args, settings)

    if args.save:
        payload = save_payload_artifacts(
            settings=settings,
            payload=payload,
            raw_query=raw_query,
            argv_list=argv_list,
        )

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    render_pretty(payload, results_limit=args.results)

    if args.save:
        artifacts = payload["artifacts"]
        console = Console()
        console.print()
        console.print(
            Panel.fit(
                f"Run directory: {artifacts['run_dir']}\n"
                f"Report: {artifacts['report_path']}\n"
                f"Manifest: {artifacts['manifest_path']}\n"
                f"Merged items: {artifacts['merged_items_path']}\n"
                f"Payload: {artifacts['payload_path']}\n"
                f"Index: {payload.get('index_path', '')}\n"
                f"Run ID: {payload.get('index_entry', {}).get('run_id', '')}",
                title="Saved artifacts",
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
