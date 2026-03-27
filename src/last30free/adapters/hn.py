from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

import httpx

from last30free.config import Settings
from last30free.models import EngagementMetrics, ResearchItem, ResearchQuote, SourceName

from .base import AdapterError, BaseAdapter


class HNAdapter(BaseAdapter):
    source_name = SourceName.HN

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        super().__init__(
            user_agent=settings.app.user_agent,
            timeout_seconds=settings.app.request_timeout_seconds,
        )
        self.settings = settings
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=settings.hn.base_url,
            headers=self.default_headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def search(self, topic: str, *, days: int, limit: int) -> list[ResearchItem]:
        effective_limit = max(1, min(limit, 100))
        cutoff = self.cutoff_datetime(days)
        cutoff_ts = int(cutoff.timestamp())

        items: list[ResearchItem] = []
        seen_ids: set[str] = set()
        page = 0
        max_pages = 4

        for _ in range(max_pages):
            remaining = effective_limit - len(items)
            if remaining <= 0:
                break

            page_limit = min(remaining, self.settings.hn.search_limit, 100)

            payload = self._get_json(
                "/search_by_date",
                params={
                    "query": topic,
                    "tags": "story",
                    "hitsPerPage": page_limit,
                    "page": page,
                    "numericFilters": f"created_at_i>{cutoff_ts}",
                },
            )

            hits = payload.get("hits", [])
            if not hits:
                break

            for hit in hits:
                source_id = str(hit.get("objectID", "")).strip()
                if not source_id or source_id in seen_ids:
                    continue

                created_at = self._parse_created_at(hit)
                if created_at < cutoff:
                    continue

                item = self._to_item(hit, created_at)
                items.append(item)
                seen_ids.add(source_id)

                if len(items) >= effective_limit:
                    break

            page += 1
            nb_pages = int(payload.get("nbPages", page) or page)
            if page >= nb_pages:
                break

        self._enrich_story_comments(items)
        return self.sort_items(items)

    def _get_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise AdapterError(f"HN request failed for {path}: {exc}") from exc
        except ValueError as exc:
            raise AdapterError(f"HN returned invalid JSON for {path}") from exc

    def _parse_created_at(self, hit: dict[str, Any]) -> datetime:
        created_at_i = hit.get("created_at_i")
        if created_at_i is not None:
            try:
                return datetime.fromtimestamp(int(created_at_i), tz=timezone.utc)
            except (TypeError, ValueError) as exc:
                raise AdapterError(f"Invalid HN created_at_i value: {created_at_i}") from exc

        created_at = str(hit.get("created_at", "")).strip()
        if not created_at:
            raise AdapterError("HN hit missing created_at and created_at_i")

        try:
            return datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AdapterError(f"Invalid HN created_at value: {created_at}") from exc

    def _to_item(self, hit: dict[str, Any], created_at: datetime) -> ResearchItem:
        source_id = str(hit.get("objectID", "")).strip()
        title = (
            str(hit.get("title", "")).strip()
            or str(hit.get("story_title", "")).strip()
            or "(untitled)"
        )
        story_text = self._clean_text(str(hit.get("story_text", "") or ""))
        author = str(hit.get("author", "")).strip() or "unknown"
        points = int(hit.get("points", 0) or 0)
        comments = int(hit.get("num_comments", 0) or 0)

        external_url = str(hit.get("url", "")).strip()
        hn_url = f"https://news.ycombinator.com/item?id={source_id}"
        display_url = external_url or hn_url

        metrics = EngagementMetrics(
            points=points,
            comments=comments,
        )

        score = self._score_item(
            points=points,
            comments=comments,
            created_at=created_at,
        )

        raw_tags = hit.get("_tags", []) or []
        normalized_tags = [
            tag for tag in raw_tags if tag in {"story", "ask_hn", "show_hn", "poll"}
        ]

        return ResearchItem(
            source=SourceName.HN,
            source_id=source_id,
            url=display_url,
            title=title,
            text=self._combine_text(title, story_text),
            author=author,
            created_at=created_at,
            score=score,
            metrics=metrics,
            quotes=[],
            tags=normalized_tags,
            raw={
                "hn_url": hn_url,
                "external_url": external_url,
                "created_at": hit.get("created_at"),
                "_tags": raw_tags,
            },
        )

    def _combine_text(self, title: str, story_text: str) -> str:
        if title and story_text:
            return f"{title}\n\n{story_text}"
        return title or story_text

    def _clean_text(self, value: str) -> str:
        value = unescape(value)
        value = re.sub(r"<[^>]+>", "", value)
        return value.strip()

    def _score_item(self, *, points: int, comments: int, created_at: datetime) -> float:
        age_days = max(
            0.0,
            (datetime.now(timezone.utc) - created_at).total_seconds() / 86400.0,
        )
        recency_boost = max(0.2, 1.0 - (age_days / 30.0))
        engagement = math.log1p(max(points, 0)) + (0.8 * math.log1p(max(comments, 0) * 2))
        return round(engagement * recency_boost, 4)

    def _enrich_story_comments(self, items: list[ResearchItem]) -> None:
        if not items:
            return

        ranked = self.sort_items(items)
        top_n = min(5, len(ranked))

        for item in ranked[:top_n]:
            quotes = self._fetch_story_comments(item.source_id)
            item.quotes.extend(quotes)

    def _fetch_story_comments(self, story_id: str) -> list[ResearchQuote]:
        payload = self._get_json(
            "/search_by_date",
            params={
                "tags": f"comment,story_{story_id}",
                "hitsPerPage": self.settings.hn.comment_limit,
            },
        )

        hits = payload.get("hits", [])
        quotes: list[ResearchQuote] = []

        for hit in hits:
            comment_text = self._clean_text(str(hit.get("comment_text", "") or ""))
            if not comment_text:
                continue

            quotes.append(
                ResearchQuote(
                    text=comment_text,
                    author=str(hit.get("author", "")).strip() or "unknown",
                    score=int(hit.get("points", 0) or 0),
                    source_label="HN",
                )
            )

            if len(quotes) >= self.settings.hn.comment_limit:
                break

        return quotes
