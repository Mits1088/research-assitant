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

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from .models import AssetCandidate, Evidence, ResearchItem

# Sources where URL → article enrichment is useful
ENRICH_SOURCES = {"hn", "reddit", "x"}

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
