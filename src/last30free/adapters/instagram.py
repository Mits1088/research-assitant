from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from last30free.config import Settings
from last30free.models import EngagementMetrics, ResearchItem, SourceName

from .base import AdapterError, BaseAdapter

PageFetcher = Callable[[str, int], Awaitable[list[dict[str, Any]]]]

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)


def _graphql_node_to_media(node: dict[str, Any]) -> dict[str, Any]:
    """Normalise a GraphQL hashtag edge node into our flat media dict."""
    caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
    caption_text = caption_edges[0].get("node", {}).get("text", "") if caption_edges else ""
    owner = node.get("owner", {})
    return {
        "id": node.get("id", ""),
        "pk": node.get("id", ""),
        "code": node.get("shortcode", ""),
        "taken_at": node.get("taken_at_timestamp"),
        "taken_at_timestamp": node.get("taken_at_timestamp"),
        "user": {
            "username": owner.get("username", ""),
            "pk": owner.get("id", ""),
        },
        "caption": {"text": caption_text},
        "like_count": node.get("edge_liked_by", {}).get("count", 0),
        "comment_count": node.get("edge_media_to_comment", {}).get("count", 0),
        "video_view_count": node.get("video_view_count", 0),
    }


class InstagramAdapter(BaseAdapter):
    source_name = SourceName.INSTAGRAM

    def __init__(self, settings: Settings, page_fetcher: PageFetcher | None = None) -> None:
        super().__init__(
            user_agent=_MOBILE_UA,
            timeout_seconds=settings.app.request_timeout_seconds,
        )
        self.settings = settings
        self._page_fetcher = page_fetcher

    def close(self) -> None:
        pass

    def search(self, topic: str, *, days: int, limit: int) -> list[ResearchItem]:
        if not self.settings.instagram.enable:
            return []
        if not self._page_fetcher and not self.settings.instagram.authenticated:
            return []

        hashtag = re.sub(r"[^a-z0-9]", "", topic.lower().replace(" ", ""))
        if not hashtag:
            return []

        effective_limit = max(1, min(limit, self.settings.instagram.search_limit))
        cutoff = self.cutoff_datetime(days)

        try:
            fetcher = self._page_fetcher or self._playwright_fetch
            raw_medias = asyncio.run(fetcher(hashtag, effective_limit))
        except AdapterError:
            raise
        except RuntimeError as exc:
            raise AdapterError(f"Instagram adapter runtime failure: {exc}") from exc
        except Exception as exc:
            raise AdapterError(f"Instagram search failed: {exc}") from exc

        items: list[ResearchItem] = []
        seen_ids: set[str] = set()

        for raw in raw_medias:
            source_id = str(raw.get("id") or raw.get("pk", "")).strip()
            if not source_id or source_id in seen_ids:
                continue

            taken_at = raw.get("taken_at") or raw.get("taken_at_timestamp")
            created_at = self._parse_created_at(taken_at)
            if created_at is None or created_at < cutoff:
                continue

            item = self._to_item(raw, created_at, hashtag)
            items.append(item)
            seen_ids.add(source_id)

            if len(items) >= effective_limit:
                break

        return self.sort_items(items)

    async def _playwright_fetch(self, hashtag: str, limit: int) -> list[dict[str, Any]]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AdapterError(
                "Instagram adapter requires playwright: "
                "pip install playwright && playwright install chromium"
            ) from exc

        raw_medias: list[dict[str, Any]] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await browser.new_context(
                user_agent=_MOBILE_UA,
                viewport={"width": 390, "height": 844},
                locale="en-US",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            # Inject session cookie if available so Instagram serves content instead of the login wall
            if self.settings.instagram.authenticated:
                from urllib.parse import unquote
                session_id = unquote(self.settings.instagram.session_id.strip())
                await context.add_cookies([
                    {
                        "name": "sessionid",
                        "value": session_id,
                        "domain": ".instagram.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                    }
                ])
            page = await context.new_page()

            async def handle_response(response: Any) -> None:
                url = response.url
                if "fbsearch" in url or "top_serp" in url:
                    try:
                        import json as _json
                        body = await response.body()
                        data = _json.loads(body)
                        for section in data.get("media_grid", {}).get("sections", []):
                            for wrapper in section.get("layout_content", {}).get("medias", []):
                                media = wrapper.get("media", wrapper)
                                if isinstance(media, dict) and media.get("pk"):
                                    raw_medias.append(media)
                    except Exception:
                        pass

            page.on("response", handle_response)

            try:
                await page.goto(
                    f"https://www.instagram.com/explore/search/keyword/?q=%23{hashtag}",
                    wait_until="domcontentloaded",
                    timeout=self.timeout_seconds * 1000,
                )
                await asyncio.sleep(6)
                prev_count = 0
                for _ in range(10):
                    if len(raw_medias) >= limit:
                        break
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(3)
                    if len(raw_medias) == prev_count:
                        break
                    prev_count = len(raw_medias)
            except Exception:
                pass

            await browser.close()

        return raw_medias

    def _parse_created_at(self, value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError):
            return None

    def _to_item(self, media: dict[str, Any], created_at: datetime, hashtag: str) -> ResearchItem:
        source_id = str(media.get("id") or media.get("pk", "")).strip()
        shortcode = str(media.get("code") or media.get("shortcode", "")).strip()
        url = (
            f"https://www.instagram.com/p/{shortcode}/"
            if shortcode
            else f"https://www.instagram.com/explore/tags/{hashtag}/"
        )

        user = media.get("user", {})
        author = str(user.get("username", "")).strip() or str(user.get("pk", "")).strip()

        caption_raw = media.get("caption") or {}
        caption_text = str(caption_raw.get("text", "")).strip() if isinstance(caption_raw, dict) else ""

        title = caption_text.splitlines()[0][:100] if caption_text else ""

        likes = int(media.get("like_count", 0) or 0)
        comments = int(media.get("comment_count", 0) or 0)
        views = int(media.get("video_view_count", 0) or media.get("view_count", 0) or 0)

        metrics = EngagementMetrics(likes=likes, comments=comments, views=views)
        score = self._score_item(likes=likes, comments=comments, views=views, created_at=created_at)

        return ResearchItem(
            source=SourceName.INSTAGRAM,
            source_id=source_id,
            url=url,
            title=title,
            text=caption_text,
            author=author,
            created_at=created_at,
            score=score,
            metrics=metrics,
            quotes=[],
            tags=[f"#{hashtag}"] if hashtag else [],
            raw={
                "shortcode": shortcode,
                "hashtag": hashtag,
                "username": author,
            },
        )

    def _score_item(self, *, likes: int, comments: int, views: int, created_at: datetime) -> float:
        age_days = max(
            0.0,
            (datetime.now(timezone.utc) - created_at).total_seconds() / 86400.0,
        )
        recency_boost = max(0.2, 1.0 - (age_days / 30.0))
        engagement = math.log1p(max(likes, 0)) + 0.8 * math.log1p(max(comments, 0) * 2)
        return round(engagement * recency_boost, 4)
