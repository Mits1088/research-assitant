from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import quote

from last30free.config import Settings
from last30free.models import EngagementMetrics, ResearchItem, ResearchQuote, SourceName

from .base import AdapterError, BaseAdapter

PageFetcher = Callable[[str, int], Any]

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _find_user_legacy(obj: Any, _depth: int = 0) -> dict[str, Any]:
    """Recursively search for a user legacy dict containing screen_name."""
    if _depth > 8:
        return {}
    if isinstance(obj, dict):
        if obj.get("screen_name"):
            return obj
        for v in obj.values():
            found = _find_user_legacy(v, _depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_user_legacy(item, _depth + 1)
            if found:
                return found
    return {}


class XAdapter(BaseAdapter):
    source_name = SourceName.X

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
        if not self.settings.x.enable:
            return []

        if not self.settings.x.configured:
            raise AdapterError("X is enabled but AUTH_TOKEN/CT0 are not configured")

        effective_limit = max(1, min(limit, self.settings.x.search_limit))
        cutoff = self.cutoff_datetime(days)

        try:
            fetcher = self._page_fetcher or self._playwright_fetch
            raw_tweets = asyncio.run(fetcher(topic, effective_limit))
        except AdapterError:
            raise
        except RuntimeError as exc:
            raise AdapterError(f"X adapter runtime failure: {exc}") from exc
        except Exception as exc:
            raise AdapterError(f"X search failed: {exc}") from exc

        items: list[ResearchItem] = []
        seen_ids: set[str] = set()

        for raw in raw_tweets:
            source_id = str(raw.get("id_str", "")).strip()
            if not source_id or source_id in seen_ids:
                continue

            created_at = self._parse_created_at(raw.get("created_at"))
            if created_at is None or created_at < cutoff:
                continue

            item = self._to_item(raw, created_at)
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
                "X adapter requires playwright: pip install playwright && playwright install chromium"
            ) from exc

        auth_token = self.settings.x.auth_token.strip()
        ct0 = self.settings.x.ct0.strip()
        raw_tweets: list[dict[str, Any]] = []

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
            await context.add_cookies([
                {"name": "auth_token", "value": auth_token, "domain": ".x.com", "path": "/", "httpOnly": True, "secure": True},
                {"name": "ct0", "value": ct0, "domain": ".x.com", "path": "/", "httpOnly": False, "secure": True},
            ])

            page = await context.new_page()

            async def handle_response(response: Any) -> None:
                if "SearchTimeline" not in response.url:
                    return
                try:
                    import json as _j
                    body = await response.body()
                    data = _j.loads(body)
                    instructions = (
                        data.get("data", {})
                        .get("search_by_raw_query", {})
                        .get("search_timeline", {})
                        .get("timeline", {})
                        .get("instructions", [])
                    )
                    for instruction in instructions:
                        for entry in instruction.get("entries", []):
                            item_content = entry.get("content", {}).get("itemContent", {})
                            result = item_content.get("tweet_results", {}).get("result", {})
                            if not result:
                                continue
                            # Unwrap TweetWithVisibilityResults
                            if result.get("__typename") == "TweetWithVisibilityResults":
                                result = result.get("tweet", result)
                            legacy = result.get("legacy", {})
                            if not legacy.get("id_str"):
                                continue
                            # Attach user info directly onto the legacy dict
                            user_legacy = (
                                result.get("core", {})
                                .get("user_results", {})
                                .get("result", {})
                                .get("legacy", {})
                            )
                            # Fallback: search recursively for screen_name anywhere in result
                            if not user_legacy.get("screen_name"):
                                user_legacy = _find_user_legacy(result)
                            legacy["_user"] = user_legacy
                            raw_tweets.append(legacy)
                except Exception:
                    pass

            page.on("response", handle_response)

            try:
                url = f"https://x.com/search?q={quote(topic)}&src=typed_query&f=top"
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_seconds * 1000)
                await asyncio.sleep(4)
                prev_count = 0
                for _ in range(10):
                    if len(raw_tweets) >= limit:
                        break
                    await page.evaluate("""
                        const col = document.querySelector('[data-testid="primaryColumn"]');
                        if (col) col.scrollTo(0, col.scrollHeight);
                        else window.scrollTo(0, document.body.scrollHeight);
                    """)
                    await page.keyboard.press("End")
                    await asyncio.sleep(3)
                    if len(raw_tweets) == prev_count:
                        break
                    prev_count = len(raw_tweets)
            except Exception:
                pass

            await browser.close()

        return raw_tweets

    def _parse_created_at(self, value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            # X format: "Fri Mar 27 00:09:54 +0000 2026"
            return parsedate_to_datetime(str(value)).astimezone(timezone.utc)
        except Exception:
            pass
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None

    def _to_item(self, raw: dict[str, Any], created_at: datetime) -> ResearchItem:
        source_id = str(raw.get("id_str", "")).strip()
        full_text = str(raw.get("full_text", "")).strip()

        user = raw.get("_user", {})
        username = str(user.get("screen_name", "")).strip()
        display_name = str(user.get("name", username or "unknown")).strip()

        url = (
            f"https://x.com/{username}/status/{source_id}"
            if username and source_id
            else f"https://x.com/search?q={source_id}"
        )

        likes = int(raw.get("favorite_count", 0) or 0)
        reposts = int(raw.get("retweet_count", 0) or 0)
        replies = int(raw.get("reply_count", 0) or 0)

        hashtags = [h.get("text", "") for h in raw.get("entities", {}).get("hashtags", [])]

        metrics = EngagementMetrics(likes=likes, reposts=reposts, comments=replies)
        score = self._score_item(likes=likes, reposts=reposts, replies=replies, created_at=created_at)
        title = self._title_from_text(full_text)

        quotes = []
        if full_text:
            quotes.append(ResearchQuote(
                text=full_text,
                author=f"@{username}" if username else display_name,
                score=likes,
                source_label=f"@{username} on X" if username else "X",
            ))

        return ResearchItem(
            source=SourceName.X,
            source_id=source_id,
            url=url,
            title=title,
            text=full_text,
            author=display_name,
            created_at=created_at,
            score=score,
            metrics=metrics,
            quotes=quotes,
            tags=[f"#{h}" for h in hashtags if h],
            raw={"username": username, "display_name": display_name, "lang": raw.get("lang")},
        )

    def _title_from_text(self, text: str) -> str:
        normalized = " ".join(text.split()).strip()
        if not normalized:
            return "(untitled post)"
        return normalized[:97].rstrip() + "..." if len(normalized) > 100 else normalized

    def _score_item(self, *, likes: int, reposts: int, replies: int, created_at: datetime) -> float:
        age_days = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds() / 86400.0)
        recency_boost = max(0.2, 1.0 - (age_days / 30.0))
        engagement = (
            math.log1p(max(likes, 0))
            + 0.9 * math.log1p(max(reposts, 0) * 2)
            + 0.7 * math.log1p(max(replies, 0) * 2)
        )
        return round(engagement * recency_boost, 4)
