from __future__ import annotations

import asyncio
import base64
import math
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from last30free.config import Settings
from last30free.models import EngagementMetrics, ResearchItem, ResearchQuote, SourceName

from .base import AdapterError, BaseAdapter

PageFetcher = Callable[[str, int], Awaitable[list[dict[str, Any]]]]

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _dig(obj: Any, *keys: Any) -> Any:
    """Safely navigate a nested dict/list without raising."""
    for key in keys:
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(key)
        elif isinstance(obj, list) and isinstance(key, int):
            obj = obj[key] if len(obj) > key else None
        else:
            return None
    return obj


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _decode_story_id(story_id: str) -> str:
    """Extract the numeric post ID from a base64-encoded Facebook story ID.

    Facebook encodes story IDs as base64 strings like:
      UzpfSTEwMDA0NzQxODIyODQ5MjpWSzo5NTUxMTk2MTM5Mzg0MDU=
    which decodes to:
      S:f100047418228492:VK:955119613938405
    We want the last colon-separated numeric segment.
    """
    try:
        decoded = base64.b64decode(story_id + "==").decode("utf-8", errors="ignore")
        numeric_parts = [p.strip() for p in decoded.split(":") if p.strip().isdigit()]
        if numeric_parts:
            # Real FB post IDs are large numbers; pick the longest (largest) segment
            return max(numeric_parts, key=len)
    except Exception:
        pass
    return story_id


class FacebookAdapter(BaseAdapter):
    source_name = SourceName.FACEBOOK

    def __init__(self, settings: Settings, page_fetcher: PageFetcher | None = None) -> None:
        super().__init__(
            user_agent=_DESKTOP_UA,
            timeout_seconds=settings.app.request_timeout_seconds,
        )
        self.settings = settings
        self._page_fetcher = page_fetcher

    def close(self) -> None:
        pass

    def search(self, topic: str, *, days: int, limit: int) -> list[ResearchItem]:
        if not self.settings.facebook.enable:
            return []

        effective_limit = max(1, min(limit, self.settings.facebook.search_limit))
        cutoff = self.cutoff_datetime(days)

        try:
            fetcher = self._page_fetcher or self._playwright_fetch
            raw_posts = asyncio.run(fetcher(topic, effective_limit))
        except AdapterError:
            raise
        except RuntimeError as exc:
            raise AdapterError(f"Facebook adapter runtime failure: {exc}") from exc
        except Exception as exc:
            raise AdapterError(f"Facebook search failed: {exc}") from exc

        items: list[ResearchItem] = []
        seen_ids: set[str] = set()

        for raw in raw_posts:
            source_id = str(raw.get("id", "")).strip()
            if not source_id or source_id in seen_ids:
                continue

            created_at = self._parse_created_at(raw.get("created_time"))
            if created_at is None or created_at < cutoff:
                continue

            item = self._to_item(raw, created_at, topic)
            items.append(item)
            seen_ids.add(source_id)

            if len(items) >= effective_limit:
                break

        return self.sort_items(items)

    async def _playwright_fetch(self, topic: str, limit: int) -> list[dict[str, Any]]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AdapterError(
                "Facebook adapter requires playwright: pip install playwright && playwright install chromium"
            ) from exc

        c_user = self.settings.facebook.c_user.strip()
        xs = self.settings.facebook.xs.strip()
        raw_posts: list[dict[str, Any]] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await browser.new_context(
                user_agent=_DESKTOP_UA,
                viewport={"width": 1280, "height": 720},
                locale="en-US",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )

            if c_user and xs:
                cookies = [
                    {
                        "name": "c_user",
                        "value": c_user,
                        "domain": ".facebook.com",
                        "path": "/",
                        "httpOnly": False,
                        "secure": True,
                    },
                    {
                        "name": "xs",
                        "value": xs,
                        "domain": ".facebook.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                    },
                ]
                datr = self.settings.facebook.datr.strip()
                sb = self.settings.facebook.sb.strip()
                if datr:
                    cookies.append({
                        "name": "datr",
                        "value": datr,
                        "domain": ".facebook.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                    })
                if sb:
                    cookies.append({
                        "name": "sb",
                        "value": sb,
                        "domain": ".facebook.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                    })
                await context.add_cookies(cookies)

            page = await context.new_page()

            async def handle_response(response: Any) -> None:
                url = response.url
                if "graphql" not in url and "search" not in url:
                    return
                try:
                    import json as _j
                    body = await response.body()
                    for line in body.decode("utf-8", errors="ignore").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = _j.loads(line)
                        except Exception:
                            continue
                        _extract_posts(data, raw_posts)
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                encoded = topic.replace(" ", "%20")
                url = f"https://www.facebook.com/search/posts/?q={encoded}"
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_seconds * 1000)
                await asyncio.sleep(5)

                prev_count = 0
                for _ in range(12):
                    if len(raw_posts) >= limit:
                        break
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(3)
                    if len(raw_posts) == prev_count:
                        break
                    prev_count = len(raw_posts)
            except Exception:
                pass

            await browser.close()

        return raw_posts

    def _parse_created_at(self, value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError):
            pass
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None

    def _to_item(self, raw: dict[str, Any], created_at: datetime, topic: str) -> ResearchItem:
        source_id = str(raw.get("id", "")).strip()
        url = str(raw.get("url", "")).strip()
        author = str(raw.get("author", "")).strip()
        text = str(raw.get("text", "")).strip()
        title = self._title_from_text(text)

        likes = _safe_int(raw.get("likes"))
        comments = _safe_int(raw.get("comments"))
        shares = _safe_int(raw.get("shares"))
        reactions = _safe_int(raw.get("reactions"))

        metrics = EngagementMetrics(
            likes=max(likes, reactions),
            comments=comments,
            reposts=shares,
        )
        score = self._score_item(
            likes=max(likes, reactions),
            comments=comments,
            shares=shares,
            created_at=created_at,
        )

        quotes: list[ResearchQuote] = []
        if text:
            quotes.append(ResearchQuote(
                text=text,
                author=author or "Facebook user",
                score=max(likes, reactions),
                source_label=f"{author} on Facebook" if author else "Facebook",
            ))

        hashtags = re.findall(r"#(\w+)", text)

        author_url = str(raw.get("author_url", "") or "").strip()
        attached_link = str(raw.get("attached_link", "") or "").strip()

        return ResearchItem(
            source=SourceName.FACEBOOK,
            source_id=source_id,
            url=url,
            title=title,
            text=text,
            author=author,
            created_at=created_at,
            score=score,
            metrics=metrics,
            quotes=quotes,
            tags=[f"#{h}" for h in hashtags],
            raw={
                "author": author,
                "author_url": author_url,
                "topic": topic,
                "attached_link": attached_link,  # external article URL if it's a link-share post
            },
        )

    def _title_from_text(self, text: str) -> str:
        normalized = " ".join(text.split()).strip()
        if not normalized:
            return "(untitled post)"
        return normalized[:97].rstrip() + "..." if len(normalized) > 100 else normalized

    def _score_item(self, *, likes: int, comments: int, shares: int, created_at: datetime) -> float:
        age_days = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds() / 86400.0)
        recency_boost = max(0.2, 1.0 - (age_days / 30.0))
        engagement = (
            math.log1p(max(likes, 0))
            + 0.9 * math.log1p(max(shares, 0) * 2)
            + 0.7 * math.log1p(max(comments, 0) * 2)
        )
        return round(engagement * recency_boost, 4)


# ---------------------------------------------------------------------------
# GraphQL response parser
# ---------------------------------------------------------------------------

def _extract_posts(data: Any, out: list[dict[str, Any]], _depth: int = 0) -> None:
    """Walk a Facebook GraphQL response tree and collect normalised post dicts."""
    if _depth > 12:
        return
    if isinstance(data, list):
        for item in data:
            _extract_posts(item, out, _depth + 1)
        return
    if not isinstance(data, dict):
        return

    # Primary path: search results come through serpResponse.results.edges
    edges = _dig(data, "data", "serpResponse", "results", "edges")
    if isinstance(edges, list):
        for edge in edges:
            story = _dig(edge, "rendering_strategy", "view_model", "click_model", "story")
            if isinstance(story, dict):
                post = _normalise_story(story)
                if post:
                    out.append(post)
        return  # handled — don't recurse further into this response

    # Recurse into nested dicts (handles chunked / multi-object responses)
    for v in data.values():
        _extract_posts(v, out, _depth + 1)


def _normalise_story(story: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a serpResponse story node into our flat post dict.

    Key paths confirmed from live Facebook GraphQL responses:
      - id                          story.id (base64 encoded)
      - creation_time               story.comet_sections.timestamp.story.creation_time
      - text                        story.comet_sections.content.story.message.text
      - author                      story.actors[0].name
      - author profile URL          story.actors[0].url
      - group_id                    story.feedback.associated_group.id
      - reaction_count              ...comet_ufi_summary_and_actions_renderer.feedback.reaction_count.count
      - comment count               ...feedback.comment_rendering_instance.comments.total_count
      - share_count                 ...feedback.share_count.count
    """
    story_id = str(story.get("id", "")).strip()
    if not story_id:
        return None

    # Timestamp
    creation_time = (
        _dig(story, "comet_sections", "timestamp", "story", "creation_time")
        or _dig(story, "comet_sections", "context_layout", "story",
                "comet_sections", "metadata", 1, "story", "creation_time")
    )
    if not creation_time:
        return None

    # Text
    text = str(_dig(story, "comet_sections", "content", "story", "message", "text") or "").strip()

    # Author
    actors = story.get("actors") or []
    actor = actors[0] if actors else {}
    author_name = str(actor.get("name", "") or "").strip()
    author_url = str(actor.get("url", "") or "").strip()

    # Build post URL — prefer the native URL Facebook already provides in the response
    native_url = str(story.get("url") or story.get("wwwURL") or story.get("permalink_url") or "").strip()

    group_id = str(_dig(story, "feedback", "associated_group", "id") or "").strip()
    post_num_id = _decode_story_id(story_id)
    has_num_id = bool(post_num_id and post_num_id != story_id)

    if native_url:
        url = native_url
    elif group_id and has_num_id:
        url = f"https://www.facebook.com/groups/{group_id}/posts/{post_num_id}"
    elif author_url and has_num_id:
        handle = author_url.rstrip("/").split("/")[-1]
        url = f"https://www.facebook.com/{handle}/posts/{post_num_id}"
    elif has_num_id:
        url = f"https://www.facebook.com/permalink.php?story_fbid={post_num_id}"
    else:
        url = ""

    # Engagement metrics (confirmed paths from live response)
    _ufi = _dig(
        story,
        "comet_sections", "feedback", "story", "story_ufi_container",
        "story", "feedback_context", "feedback_target_with_context",
        "comet_ufi_summary_and_actions_renderer", "feedback",
    )
    reactions = _safe_int(_dig(_ufi, "reaction_count", "count"))
    shares = _safe_int(_dig(_ufi, "share_count", "count"))
    comments = _safe_int(_dig(_ufi, "comment_rendering_instance", "comments", "total_count"))

    # Check for a linked article (link-share posts attach an external URL)
    attached_link = str(
        _dig(story, "comet_sections", "content", "story", "attachments", 0, "styles", "attachment", "url") or
        _dig(story, "attachments", 0, "url") or
        ""
    ).strip()

    return {
        "id": story_id,
        "created_time": creation_time,
        "text": text,
        "author": author_name,
        "author_url": author_url,
        "url": url,
        "attached_link": attached_link,
        "likes": reactions,
        "comments": comments,
        "shares": shares,
        "reactions": reactions,
    }
