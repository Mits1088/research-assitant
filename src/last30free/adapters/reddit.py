from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import httpx

from last30free.config import Settings
from last30free.models import EngagementMetrics, ResearchItem, ResearchQuote, SourceName

from .base import AdapterError, BaseAdapter


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BROWSER_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.reddit.com/",
}


class RedditAdapter(BaseAdapter):
    source_name = SourceName.REDDIT

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        super().__init__(
            user_agent=_BROWSER_UA,
            timeout_seconds=settings.app.request_timeout_seconds,
        )
        self.settings = settings
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=settings.reddit.base_url,
            headers=_BROWSER_HEADERS,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def search(self, topic: str, *, days: int, limit: int) -> list[ResearchItem]:
        effective_limit = max(1, min(limit, 100))
        cutoff = self.cutoff_datetime(days)

        # Wrap multi-word topics in quotes so Reddit matches the exact phrase
        # rather than any post containing the words separately.
        search_q = f'"{topic}"' if len(topic.split()) > 1 else topic

        items: list[ResearchItem] = []
        seen_ids: set[str] = set()

        after: str | None = None
        count = 0
        max_pages = 4

        for _ in range(max_pages):
            remaining = effective_limit - len(items)
            if remaining <= 0:
                break

            page_limit = min(remaining, self.settings.reddit.search_limit, 100)

            payload = self._get_json(
                "/search.json",
                params={
                    "q": search_q,
                    "sort": "top",
                    "t": "month",
                    "type": "link",
                    "Limit": page_limit,
                    "raw_json": 1,
                    "count": count,
                    **({"after": after} if after else {}),
                },
            )

            listing = payload.get("data", {})
            children = listing.get("children", [])

            if not children:
                break

            for child in children:
                if child.get("kind") != "t3":
                    continue

                post = child.get("data", {})
                source_id = str(post.get("id", "")).strip()
                if not source_id or source_id in seen_ids:
                    continue

                created_at = self._parse_created_at(post.get("created_utc"))
                if created_at < cutoff:
                    continue

                item = self._to_item(post, created_at)
                items.append(item)
                seen_ids.add(source_id)
                count += 1

                if len(items) >= effective_limit:
                    break

            after = listing.get("after")
            if not after:
                break

        self._enrich_top_comments(items)
        return self.sort_items(items)

    def _get_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise AdapterError(f"Reddit request failed for {path}: {exc}") from exc
        except ValueError as exc:
            raise AdapterError(f"Reddit returned invalid JSON for {path}") from exc

    def _parse_created_at(self, value: Any) -> datetime:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError) as exc:
            raise AdapterError(f"Invalid Reddit created_utc value: {value}") from exc

    def _to_item(self, post: dict[str, Any], created_at: datetime) -> ResearchItem:
        source_id = str(post.get("id", ""))
        permalink = str(post.get("permalink", ""))
        subreddit = str(post.get("subreddit", "")).strip()
        title = str(post.get("title", "")).strip()
        selftext = str(post.get("selftext", "")).strip()
        author = str(post.get("author", "")).strip() or "[deleted]"

        upvotes = int(post.get("ups", 0) or 0)
        comments = int(post.get("num_comments", 0) or 0)

        thread_url = f"{self.settings.reddit.base_url.rstrip('/')}{permalink}"
        text = self._combine_text(title, selftext)

        metrics = EngagementMetrics(
            upvotes=upvotes,
            comments=comments,
        )

        score = self._score_item(
            upvotes=upvotes,
            comments=comments,
            created_at=created_at,
        )

        return ResearchItem(
            source=SourceName.REDDIT,
            source_id=source_id,
            url=thread_url,
            title=title,
            text=text,
            author=author,
            created_at=created_at,
            score=score,
            metrics=metrics,
            quotes=[],
            tags=[f"r/{subreddit}"] if subreddit else [],
            raw={
                "subreddit": subreddit,
                "permalink": permalink,
                "domain": post.get("domain"),
                "over_18": bool(post.get("over_18", False)),
            },
        )

    def _combine_text(self, title: str, selftext: str) -> str:
        if title and selftext:
            return f"{title}\n\n{selftext}"
        return title or selftext

    def _score_item(self, *, upvotes: int, comments: int, created_at: datetime) -> float:
        age_days = max(
            0.0,
            (datetime.now(timezone.utc) - created_at).total_seconds() / 86400.0,
        )
        recency_boost = max(0.2, 1.0 - (age_days / 30.0))
        engagement = math.log1p(max(upvotes, 0)) + (0.8 * math.log1p(max(comments, 0) * 2))
        return round(engagement * recency_boost, 4)

    def _enrich_top_comments(self, items: list[ResearchItem]) -> None:
        if not items:
            return

        ranked = self.sort_items(items)
        top_n = min(5, len(ranked))

        for item in ranked[:top_n]:
            permalink = str(item.raw.get("permalink", "")).strip()
            subreddit = str(item.raw.get("subreddit", "")).strip()
            if not permalink:
                continue

            try:
                quotes = self._fetch_top_comments(permalink=permalink, subreddit=subreddit)
                item.quotes.extend(quotes)
            except AdapterError:
                # Comment fetch blocked or rate-limited; keep the item, skip quotes.
                pass

    def _fetch_top_comments(self, *, permalink: str, subreddit: str) -> list[ResearchQuote]:
        payload = self._get_comment_listing(permalink)

        if not isinstance(payload, list) or len(payload) < 2:
            return []

        comments_listing = payload[1].get("data", {})
        children = comments_listing.get("children", [])

        quotes: list[ResearchQuote] = []
        for child in children:
            if child.get("kind") != "t1":
                continue

            data = child.get("data", {})
            body = str(data.get("body", "")).strip()
            if not body:
                continue

            quotes.append(
                ResearchQuote(
                    text=body,
                    author=str(data.get("author", "")).strip() or "[deleted]",
                    score=int(data.get("ups", 0) or 0),
                    source_label=f"r/{subreddit}" if subreddit else "reddit",
                )
            )

            if len(quotes) >= self.settings.reddit.comment_limit:
                break

        return quotes

    def _get_comment_listing(self, permalink: str) -> list[dict[str, Any]]:
        path = f"{permalink}.json"
        try:
            response = self.client.get(
                path,
                params={
                    "limit": self.settings.reddit.comment_limit,
                    "sort": "top",
                    "raw_json": 1,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                return payload
            return []
        except httpx.HTTPError as exc:
            raise AdapterError(f"Reddit comments request failed for {permalink}: {exc}") from exc
        except ValueError as exc:
            raise AdapterError(f"Reddit returned invalid comment JSON for {permalink}") from exc
