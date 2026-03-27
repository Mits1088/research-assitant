from __future__ import annotations

import asyncio
import json as _json
import math
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from last30free.config import Settings
from last30free.models import EngagementMetrics, ResearchItem, SourceName

from .base import AdapterError, BaseAdapter

PageFetcher = Callable[[str, int], Awaitable[list[dict[str, Any]]]]

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Matches TikTok's server-rendered JSON data block in page HTML
_REHYDRATION_RE = re.compile(
    r'<script[^>]+id=["\']__UNIVERSAL_DATA_FOR_REHYDRATION__["\'][^>]*>(.*?)</script>',
    re.DOTALL,
)


class TikTokAdapter(BaseAdapter):
    source_name = SourceName.TIKTOK

    def __init__(self, settings: Settings, page_fetcher: PageFetcher | None = None) -> None:
        super().__init__(
            user_agent=_DESKTOP_UA,
            timeout_seconds=settings.app.request_timeout_seconds,
        )
        self.settings = settings
        self._page_fetcher = page_fetcher

    def search(self, topic: str, *, days: int, limit: int) -> list[ResearchItem]:
        if not self.settings.tiktok.enable:
            return []

        hashtag = re.sub(r"[^a-z0-9]", "", topic.lower().replace(" ", ""))
        if not hashtag:
            return []

        effective_limit = max(1, min(limit, self.settings.tiktok.search_limit))
        cutoff = self.cutoff_datetime(days)

        try:
            fetcher = self._page_fetcher or self._auto_fetch
            raw_items = asyncio.run(fetcher(hashtag, effective_limit))
        except AdapterError:
            raise
        except RuntimeError as exc:
            raise AdapterError(f"TikTok adapter runtime failure: {exc}") from exc
        except Exception as exc:
            raise AdapterError(f"TikTok search failed: {exc}") from exc

        items: list[ResearchItem] = []
        seen_ids: set[str] = set()

        for raw in raw_items:
            source_id = str(raw.get("id", "")).strip()
            if not source_id or source_id in seen_ids:
                continue

            created_at = self._parse_created_at(raw.get("createTime"))
            if created_at is None or created_at < cutoff:
                continue

            item = self._to_item(raw, created_at, hashtag)
            items.append(item)
            seen_ids.add(source_id)

            if len(items) >= effective_limit:
                break

        return self.sort_items(items)

    async def _auto_fetch(self, hashtag: str, limit: int) -> list[dict[str, Any]]:
        """Try curl_cffi (bypasses CloudFlare TLS detection) then fall back to Playwright."""
        try:
            items = await self._curl_fetch(hashtag, limit)
            if items:
                return items
        except AdapterError:
            raise
        except Exception:
            pass
        return await self._playwright_fetch(hashtag, limit)

    async def _curl_fetch(self, hashtag: str, limit: int) -> list[dict[str, Any]]:
        """
        Fetch TikTok page HTML via curl_cffi, which impersonates Chrome's TLS fingerprint
        and bypasses CloudFlare bot detection without needing a real browser.
        """
        try:
            from curl_cffi.requests import AsyncSession
        except ImportError as exc:
            raise AdapterError(
                "TikTok HTTP fetch requires curl_cffi: pip install curl_cffi"
            ) from exc

        urls_and_keys = [
            (f"https://www.tiktok.com/tag/{hashtag}", "webapp.hashtag-detail"),
            (f"https://www.tiktok.com/search/video?q={hashtag}", "webapp.search-result-page"),
        ]

        async with AsyncSession(impersonate="chrome120") as session:
            for url, scope_key in urls_and_keys:
                try:
                    resp = await session.get(
                        url,
                        headers={
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            "Accept-Language": "en-US,en;q=0.9",
                            "Referer": "https://www.tiktok.com/",
                        },
                        timeout=self.timeout_seconds,
                    )
                    items = self._parse_rehydration(resp.text, scope_key)
                    if items:
                        return items
                except Exception:
                    continue

        return []

    async def _playwright_fetch(self, hashtag: str, limit: int) -> list[dict[str, Any]]:
        """
        Visible (non-headless) Chromium browser.

        TikTok's bot detection blocks headless Chromium at the response level — the
        challenge/item_list API returns 200 with an empty body for any headless
        browser.  A non-headless browser presents a genuine fingerprint and receives
        real data.  A small browser window will appear briefly while TikTok is scraped.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AdapterError(
                "TikTok adapter requires playwright: "
                "pip install playwright && playwright install chromium"
            ) from exc

        raw_items: list[dict[str, Any]] = []

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
            page = await context.new_page()

            async def handle_route(route: Any) -> None:
                req = route.request
                if "challenge/item_list" in req.url:
                    response = await route.fetch()
                    body = await response.body()
                    if body:
                        try:
                            import json as _j
                            data = _j.loads(body)
                            for video in data.get("itemList", []):
                                raw_items.append(video)
                        except Exception:
                            pass
                    await route.fulfill(response=response)
                else:
                    await route.continue_()

            await context.route("**/*", handle_route)

            try:
                await page.goto(
                    f"https://www.tiktok.com/tag/{hashtag}",
                    wait_until="domcontentloaded",
                    timeout=self.timeout_seconds * 1000,
                )
                await asyncio.sleep(4)
                prev_count = 0
                for _ in range(10):
                    if len(raw_items) >= limit:
                        break
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)
                    if len(raw_items) == prev_count:
                        break
                    prev_count = len(raw_items)
            except Exception:
                pass

            await browser.close()

        return raw_items

    def _parse_rehydration(self, html: str, scope_key: str) -> list[dict[str, Any]]:
        """Extract video items from TikTok's __UNIVERSAL_DATA_FOR_REHYDRATION__ script tag."""
        match = _REHYDRATION_RE.search(html)
        if not match:
            return []
        try:
            data = _json.loads(match.group(1))
        except Exception:
            return []

        scope = data.get("__DEFAULT_SCOPE__", {})
        section = scope.get(scope_key, {})

        # Hashtag page: videos are in itemList directly
        videos = list(section.get("itemList", []))

        # Search page: videos are wrapped in data[].item
        if not videos:
            for wrapper in section.get("data", []):
                video = wrapper.get("item", wrapper)
                if isinstance(video, dict) and video.get("id"):
                    videos.append(video)

        return videos

    def _parse_created_at(self, value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError):
            return None

    def _to_item(self, raw: dict[str, Any], created_at: datetime, hashtag: str) -> ResearchItem:
        source_id = str(raw.get("id", "")).strip()
        author_obj = raw.get("author", {})
        author = str(author_obj.get("uniqueId", "")).strip() or str(author_obj.get("nickname", "")).strip()

        desc = str(raw.get("desc", "")).strip()
        title = desc[:100] if len(desc) > 100 else desc

        stats = raw.get("stats", {})
        likes = int(stats.get("diggCount", 0) or 0)
        comments = int(stats.get("commentCount", 0) or 0)
        shares = int(stats.get("shareCount", 0) or 0)
        views = int(stats.get("playCount", 0) or 0)

        url = (
            f"https://www.tiktok.com/@{author}/video/{source_id}"
            if author
            else f"https://www.tiktok.com/tag/{hashtag}"
        )

        metrics = EngagementMetrics(likes=likes, comments=comments, reposts=shares, views=views)
        score = self._score_item(likes=likes, comments=comments, shares=shares, views=views, created_at=created_at)

        return ResearchItem(
            source=SourceName.TIKTOK,
            source_id=source_id,
            url=url,
            title=title,
            text=desc,
            author=author,
            created_at=created_at,
            score=score,
            metrics=metrics,
            quotes=[],
            tags=[f"#{hashtag}"] if hashtag else [],
            raw={"hashtag": hashtag, "username": author, "shares": shares},
        )

    def _score_item(
        self, *, likes: int, comments: int, shares: int, views: int, created_at: datetime
    ) -> float:
        age_days = max(
            0.0,
            (datetime.now(timezone.utc) - created_at).total_seconds() / 86400.0,
        )
        recency_boost = max(0.2, 1.0 - (age_days / 30.0))
        engagement = (
            math.log1p(max(likes, 0))
            + 0.8 * math.log1p(max(comments, 0) * 2)
            + 0.6 * math.log1p(max(shares, 0))
        )
        return round(engagement * recency_boost, 4)
