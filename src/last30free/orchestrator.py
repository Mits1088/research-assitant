from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .adapters import (
    AdapterError,
    BaseAdapter,
    FacebookAdapter,
    HNAdapter,
    InstagramAdapter,
    RedditAdapter,
    TikTokAdapter,
    XAdapter,
    YouTubeAdapter,
)
from .config import Settings
from .intent import normalize_spaces, parse_user_intent
from .models import ALL_SOURCES, ResearchItem
from .reporting import create_run_dir, write_run_outputs
from .run_index import index_path, read_manifest, update_run_index
from .synthesis import synthesize

ADAPTER_MAP: dict[str, type[BaseAdapter]] = {
    "reddit": RedditAdapter,
    "hn": HNAdapter,
    "youtube": YouTubeAdapter,
    "x": XAdapter,
    "instagram": InstagramAdapter,
    "tiktok": TikTokAdapter,
    "facebook": FacebookAdapter,
}

_NOT_CONFIGURED_MESSAGES: dict[str, str] = {
    "instagram": (
        "Set INSTAGRAM_SESSION_ID env var to enable "
        "(get it from browser DevTools → Cookies → instagram.com → sessionid)"
    ),
    "facebook": (
        "Set FACEBOOK_C_USER and FACEBOOK_XS env vars to enable "
        "(get them from browser DevTools → Application → Cookies → facebook.com)"
    ),
}


def _is_configured(source_name: str, settings: Settings) -> bool:
    if source_name == "instagram":
        return settings.instagram.authenticated
    if source_name == "facebook":
        return settings.facebook.configured
    return True


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


def init_result() -> dict[str, Any]:
    return {
        "status": "not_requested",
        "count": 0,
        "items": [],
        "error": None,
    }


def run_adapter(
    source_name: str,
    settings: Settings,
    topic: str,
    *,
    days: int,
    limit: int,
) -> tuple[dict[str, Any], list[ResearchItem]]:
    adapter_cls = ADAPTER_MAP.get(source_name)
    if adapter_cls is None:
        return init_result(), []

    if not _is_configured(source_name, settings):
        return (
            {
                "status": "not_configured",
                "count": 0,
                "items": [],
                "error": _NOT_CONFIGURED_MESSAGES.get(source_name, f"{source_name} is not configured"),
            },
            [],
        )

    adapter = adapter_cls(settings)
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
    enrich: bool = False,
    enrich_limit: int = 10,
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

    implemented_selected = [s for s in selected_sources if s in ALL_SOURCES]

    results: dict[str, Any] = {source: init_result() for source in ALL_SOURCES}

    merged_items: list[ResearchItem] = []
    for source_name in implemented_selected:
        result, items = run_adapter(source_name, settings, intent.topic, days=runtime_days, limit=runtime_limit)
        results[source_name] = result
        merged_items.extend(items)

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

    # Optional enrichment pass — text only (screenshots added later in save_payload_artifacts)
    evidence_payload: dict[str, Any] = {"count": 0, "items": []}
    asset_candidates_payload: dict[str, Any] = {"count": 0, "items": []}
    if enrich and merged_items:
        from .enrichment import enrich_items
        evidence_list, asset_candidates = enrich_items(
            merged_items,
            limit=enrich_limit,
            jina_api_key=settings.app.jina_api_key,
        )
        evidence_payload = {
            "count": len(evidence_list),
            "items": [e.model_dump(mode="json") for e in evidence_list],
        }
        asset_candidates_payload = {
            "count": len(asset_candidates),
            "items": [a.model_dump(mode="json") for a in asset_candidates],
        }

    synthesis = synthesize(merged_items, intent=intent, results=results)

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
            "enrich": enrich,
            "enrich_limit": enrich_limit,
        },
        "results": results,
        "merged": {
            "count": len(merged_serialized),
            "items": merged_serialized,
        },
        "evidence": evidence_payload,
        "asset_candidates": asset_candidates_payload,
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
        enrich=getattr(args, "enrich", False),
        enrich_limit=getattr(args, "enrich_limit", 10),
    )


def save_payload_artifacts(
    *,
    settings: Settings,
    payload: dict[str, Any],
    raw_query: str,
    argv_list: list[str],
) -> dict[str, Any]:
    run_dir = create_run_dir(settings.app.output_dir, payload["intent"]["topic"])

    # Screenshot enrichment — runs after run_dir is created so PNGs have a home
    if payload.get("runtime", {}).get("enrich"):
        evidence_items = payload.get("evidence", {}).get("items", [])
        if evidence_items:
            from .enrichment import enrich_add_screenshots
            enrich_add_screenshots(
                evidence_items,
                run_dir=run_dir,
                screenshot_limit=5,
                jina_api_key=settings.app.jina_api_key,
            )
            payload["evidence"]["items"] = evidence_items

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
    run_results = []

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
        run_results.append(
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

    return run_results
