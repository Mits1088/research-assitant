"""
Jina Reader enrichment layer.

Fetches full article markdown and optional screenshots from r.jina.ai
for top-scored items. Enrichment is opt-in — pass --enrich on the CLI.

Only HN, Reddit, and X items are enriched. YouTube, Instagram, TikTok, and
Facebook don't have outbound article links worth following and are skipped.

Set JINA_API_KEY in your .env for authenticated access (higher rate limits).
Without a key the free tier is used — works fine for up to ~50 requests/run.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

from .models import AssetCandidate, Evidence, ResearchItem

# Sources where URL enrichment via Jina Reader is useful.
# HN: item.url is the linked external article (or HN discussion for Ask/Show HN)
# Reddit: reddit.com thread page — Jina reads it and returns post + top comments
# X: post page — Jina reads tweet text and thread context
# TikTok: tiktok.com/@user/video/id — publicly accessible, Jina reads description + stats
# Instagram / Facebook: login-walled — Jina returns login page, not useful
ENRICH_SOURCES = {"hn", "reddit", "x", "tiktok"}

JINA_BASE = "https://r.jina.ai"
_MAX_WORKERS = 5

_CLAIM_TRIGGERS = re.compile(
    r"\b(better than|replaces|outperforms|best|faster|cheaper|beats|vs\.?|"
    r"alternative to|open.?source|game.?changer|kills)\b",
    re.IGNORECASE,
)
_TOOL_PATTERN = re.compile(r"\b[A-Z][a-zA-Z0-9\-\.]{2,}\b")
_COMMON_WORDS = frozenset(
    {
        "The", "This", "That", "These", "Those", "They", "Their", "There",
        "With", "From", "Into", "About", "After", "When", "What", "Which",
        "However", "Although", "Because", "Since", "While", "Also", "Even",
        "Here", "Where", "Each", "Both", "More", "Many", "Much", "Such",
        "Some", "Very", "Just", "Only", "Then", "Than", "Have", "Been",
        "Will", "Would", "Could", "Should", "Does", "Makes", "Using",
        "New", "Now", "One", "Two", "Its", "Our", "For", "But", "And",
        "You", "Your", "All", "Any", "Can", "Get", "Has", "Not", "Are",
        "Was", "Had", "But", "How", "Who", "Why", "See", "Use", "May",
    }
)


# ── Jina HTTP helpers ─────────────────────────────────────────────────────────

def _fetch_markdown(url: str, client: httpx.Client, api_key: str) -> str:
    headers: dict[str, str] = {"Accept": "text/markdown, text/plain"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = client.get(f"{JINA_BASE}/{url}", headers=headers, timeout=20.0)
        if resp.status_code == 200:
            return resp.text
    except (httpx.RequestError, httpx.TimeoutException, httpx.HTTPStatusError):
        pass
    return ""


def _fetch_screenshot_url(url: str, client: httpx.Client, api_key: str) -> str:
    headers: dict[str, str] = {"x-respond-with": "screenshot"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = client.get(f"{JINA_BASE}/{url}", headers=headers, timeout=30.0)
        if resp.status_code == 200:
            return resp.text.strip()
    except (httpx.RequestError, httpx.TimeoutException, httpx.HTTPStatusError):
        pass
    return ""


def _download_bytes(url: str, client: httpx.Client) -> bytes | None:
    try:
        resp = client.get(url, timeout=30.0)
        if resp.status_code == 200:
            return resp.content
    except (httpx.RequestError, httpx.TimeoutException, httpx.HTTPStatusError):
        pass
    return None


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_tools(markdown: str) -> list[str]:
    """Return likely tool/product names found 2+ times in the markdown."""
    if not markdown:
        return []
    counts: dict[str, int] = {}
    for match in _TOOL_PATTERN.finditer(markdown[:4000]):
        word = match.group()
        if word in _COMMON_WORDS or len(word) < 3:
            continue
        counts[word] = counts.get(word, 0) + 1
    return [w for w, c in sorted(counts.items(), key=lambda x: -x[1]) if c >= 2][:10]


def _extract_claims(markdown: str) -> list[str]:
    """Return sentences containing comparative or claim-like language."""
    if not markdown:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", markdown[:5000])
    claims: list[str] = []
    for sentence in sentences:
        if _CLAIM_TRIGGERS.search(sentence):
            cleaned = sentence.strip()
            if 20 < len(cleaned) < 300:
                claims.append(cleaned)
        if len(claims) >= 5:
            break
    return claims


# ── Single-item enrichment ────────────────────────────────────────────────────

def _enrich_one_text(
    item: ResearchItem,
    *,
    client: httpx.Client,
    api_key: str,
) -> Evidence:
    url = item.url
    if not url or not url.startswith("http"):
        return Evidence(
            source_id=item.source_id,
            url=url,
            enrich_status="skipped",
            enrich_error="No valid URL",
        )

    markdown = _fetch_markdown(url, client, api_key)
    return Evidence(
        source_id=item.source_id,
        url=url,
        markdown=markdown[:3000] if markdown else "",
        extracted_tools=_extract_tools(markdown),
        extracted_claims=_extract_claims(markdown),
        enrich_status="ok" if markdown else "empty",
        enrich_error=None if markdown else "Jina returned no content",
    )


def _add_screenshot(
    evidence: Evidence,
    *,
    client: httpx.Client,
    run_dir: Path,
    api_key: str,
) -> None:
    """Fetch and save a screenshot for an already text-enriched Evidence item (mutates in place)."""
    if not evidence.url or not evidence.url.startswith("http"):
        return

    screenshot_url = _fetch_screenshot_url(evidence.url, client, api_key)
    if not screenshot_url.startswith("http"):
        return

    img_bytes = _download_bytes(screenshot_url, client)
    if not img_bytes:
        return

    safe_id = re.sub(r"[^a-z0-9]", "_", evidence.source_id.lower())[:40]
    screenshot_file = run_dir / f"screenshot_{safe_id}.png"
    screenshot_file.write_bytes(img_bytes)
    evidence.screenshot_path = str(screenshot_file)


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_items(
    items: list[ResearchItem],
    *,
    limit: int = 10,
    jina_api_key: str = "",
) -> tuple[list[Evidence], list[AssetCandidate]]:
    """
    Text-enrich the top-scored items from HN, Reddit, and X using Jina Reader.

    Fetches full article markdown for each item URL and extracts tool names
    and claim sentences. Returns (evidence_list, asset_candidates).
    Screenshots are not taken here — call enrich_add_screenshots() separately
    once you have a run directory (i.e. after --save creates it).
    """
    enrichable = [item for item in items if item.source.value in ENRICH_SOURCES][:limit]
    if not enrichable:
        return [], []

    evidence_list: list[Evidence] = []

    with httpx.Client(follow_redirects=True, timeout=25.0) as client:
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            future_map = {
                pool.submit(_enrich_one_text, item, client=client, api_key=jina_api_key): item
                for item in enrichable
            }
            for future in as_completed(future_map):
                try:
                    evidence_list.append(future.result())
                except Exception:
                    pass

    # Sort evidence to match original item order
    id_order = {item.source_id: i for i, item in enumerate(enrichable)}
    evidence_list.sort(key=lambda e: id_order.get(e.source_id, 999))

    asset_candidates = [
        AssetCandidate(
            source_id=e.source_id,
            url=e.url,
            title=next((it.title for it in enrichable if it.source_id == e.source_id), ""),
            score=next((it.score for it in enrichable if it.source_id == e.source_id), 0.0),
            pull_quotes=e.extracted_claims[:3],
        )
        for e in evidence_list
        if e.enrich_status == "ok"
    ]

    return evidence_list, asset_candidates


def enrich_add_screenshots(
    evidence_dicts: list[dict],
    *,
    run_dir: Path,
    screenshot_limit: int = 5,
    jina_api_key: str = "",
) -> list[dict]:
    """
    Take screenshots for the top-N already text-enriched evidence items.
    Updates screenshot_path in each dict and saves PNG files to run_dir.
    Returns the updated list of dicts (same reference, mutated in place).
    """
    candidates = [e for e in evidence_dicts if e.get("enrich_status") == "ok"][:screenshot_limit]
    if not candidates:
        return evidence_dicts

    with httpx.Client(follow_redirects=True, timeout=35.0) as client:
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, screenshot_limit)) as pool:
            def _screenshot_dict(ev_dict: dict) -> None:
                ev = Evidence(**ev_dict)
                _add_screenshot(ev, client=client, run_dir=run_dir, api_key=jina_api_key)
                ev_dict["screenshot_path"] = ev.screenshot_path

            futures = [pool.submit(_screenshot_dict, ev_dict) for ev_dict in candidates]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass

    return evidence_dicts


# ── Caption URL extraction ────────────────────────────────────────────────────

_URL_RE = re.compile(r"https?://[^\s<>\"'}{|\\\^\[\]`]+")
_SELF_REFERENTIAL_DOMAINS = {
    "instagram.com", "tiktok.com", "facebook.com",
    "twitter.com", "x.com", "t.co",
    "reddit.com", "youtu.be", "youtube.com",
    "l.instagram.com",
}


def _extract_caption_urls(text: str) -> list[str]:
    """
    Extract external HTTP(S) URLs from post captions/descriptions.
    Strips trailing punctuation and filters out links back to the same platform.
    """
    urls = _URL_RE.findall(text)
    clean: list[str] = []
    for url in urls:
        url = url.rstrip(".,;:!?)")
        domain = url.split("/")[2].lower() if url.count("/") >= 2 else ""
        if not any(sd in domain for sd in _SELF_REFERENTIAL_DOMAINS):
            clean.append(url)
    return clean[:5]


# ── Post-hoc selective enrichment ────────────────────────────────────────────

def enrich_run(
    run_dir: Path,
    *,
    item_indices: list[int] | None = None,
    transcript: bool = False,
    whisper_model: str = "small",
    jina_api_key: str = "",
    instagram_session_id: str = "",
) -> dict[str, Any]:
    """
    Post-hoc enrichment of a saved run.

    Reads merged_items.json, enriches the selected items (or all if
    item_indices is None), and writes back to evidence.json and
    asset_candidates.json in the same run directory.

    Enrichment steps per item:
      1. Jina text enrichment (HN/Reddit/X/TikTok items)
      2. Caption URL extraction → Jina article enrichment (all sources)
      3. Video transcript via yt-dlp + Whisper (if transcript=True)

    Returns a summary dict with counts and any error messages.
    """
    merged_path = run_dir / "merged_items.json"
    if not merged_path.exists():
        raise FileNotFoundError(f"merged_items.json not found in {run_dir}")

    all_items_raw: list[dict[str, Any]] = json.loads(
        merged_path.read_text(encoding="utf-8")
    )

    if not all_items_raw:
        return {"enriched": 0, "transcribed": 0, "total_evidence": 0, "errors": []}

    if item_indices is None:
        selected_raw = all_items_raw
    else:
        valid_idx = [i - 1 for i in item_indices if 1 <= i <= len(all_items_raw)]
        selected_raw = [all_items_raw[i] for i in valid_idx]

    if not selected_raw:
        return {"enriched": 0, "transcribed": 0, "total_evidence": 0, "errors": ["No valid items selected"]}

    items: list[ResearchItem] = []
    for raw in selected_raw:
        try:
            items.append(ResearchItem(**raw))
        except Exception:
            pass

    # Load existing evidence so we don't wipe items not being re-enriched
    evidence_path = run_dir / "evidence.json"
    evidence_by_id: dict[str, dict[str, Any]] = {}
    if evidence_path.exists():
        try:
            for ev in json.loads(evidence_path.read_text(encoding="utf-8")):
                if isinstance(ev, dict) and ev.get("source_id"):
                    evidence_by_id[ev["source_id"]] = ev
        except Exception:
            pass

    errors: list[str] = []
    enriched_count = 0
    transcribed_count = 0

    # Step 1: Jina text enrichment for enrichable sources
    enrichable = [it for it in items if it.source.value in ENRICH_SOURCES]
    if enrichable:
        with httpx.Client(follow_redirects=True, timeout=25.0) as client:
            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                future_map = {
                    pool.submit(_enrich_one_text, it, client=client, api_key=jina_api_key): it
                    for it in enrichable
                }
                for future in as_completed(future_map):
                    item = future_map[future]
                    try:
                        ev = future.result()
                        evidence_by_id[ev.source_id] = ev.model_dump(mode="json")
                        enriched_count += 1
                    except Exception as exc:
                        errors.append(f"{item.source_id}: Jina failed — {exc}")

    # Step 2: Caption URL → article enrichment (all sources)
    with httpx.Client(follow_redirects=True, timeout=25.0) as client:
        for it in items:
            caption_urls = _extract_caption_urls(it.text)
            if not caption_urls:
                continue
            article_url = caption_urls[0]
            article_md = _fetch_markdown(article_url, client, jina_api_key)
            if not article_md:
                continue
            ev_dict = evidence_by_id.setdefault(
                it.source_id,
                _blank_evidence(it),
            )
            ev_dict["caption_article_url"] = article_url
            ev_dict["caption_article_markdown"] = article_md[:3000]
            ev_dict["enrich_status"] = "ok"

    # Step 3: Video transcript (opt-in)
    if transcript:
        from .video_fetch import VIDEO_SOURCES, VideoFetchError, fetch_transcript

        for it in items:
            if it.source.value not in VIDEO_SOURCES:
                continue
            try:
                text, source_label = fetch_transcript(
                    it.url,
                    it.source.value,
                    it.source_id,
                    run_dir=run_dir,
                    whisper_model=whisper_model,
                    instagram_session_id=instagram_session_id,
                )
                if text:
                    ev_dict = evidence_by_id.setdefault(it.source_id, _blank_evidence(it))
                    ev_dict["transcript"] = text
                    ev_dict["transcript_source"] = source_label
                    transcribed_count += 1
            except VideoFetchError as exc:
                errors.append(f"{it.source_id}: transcript failed — {exc}")
            except Exception as exc:
                errors.append(f"{it.source_id}: unexpected error — {exc}")

    # Save updated evidence.json
    evidence_list = list(evidence_by_id.values())
    evidence_path.write_text(
        json.dumps(evidence_list, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Rebuild asset_candidates.json
    item_by_id = {it.source_id: it for it in items}
    asset_candidates = [
        {
            "source_id": ev["source_id"],
            "url": ev["url"],
            "title": item_by_id[ev["source_id"]].title if ev["source_id"] in item_by_id else "",
            "score": item_by_id[ev["source_id"]].score if ev["source_id"] in item_by_id else 0.0,
            "screenshot_path": ev.get("screenshot_path", ""),
            "pull_quotes": ev.get("extracted_claims", [])[:3],
            "transcript_snippet": ev.get("transcript", "")[:200],
        }
        for ev in evidence_list
        if ev.get("enrich_status") == "ok"
    ]
    assets_path = run_dir / "asset_candidates.json"
    assets_path.write_text(
        json.dumps(asset_candidates, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "enriched": enriched_count,
        "transcribed": transcribed_count,
        "total_evidence": len(evidence_list),
        "errors": errors,
        "evidence_path": str(evidence_path),
        "asset_candidates_path": str(assets_path),
    }


def _blank_evidence(item: ResearchItem) -> dict[str, Any]:
    """Return an empty evidence dict for an item that has no Jina enrichment yet."""
    return {
        "source_id": item.source_id,
        "url": item.url,
        "markdown": "",
        "extracted_tools": [],
        "extracted_claims": [],
        "screenshot_path": "",
        "enrich_status": "ok",
        "enrich_error": None,
        "transcript": "",
        "transcript_source": "",
        "caption_article_url": "",
        "caption_article_markdown": "",
    }
