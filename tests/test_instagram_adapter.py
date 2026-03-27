from __future__ import annotations

import os
from typing import Any

from last30free.adapters.instagram import InstagramAdapter
from last30free.config import load_settings


def make_raw_media(
    *,
    media_id: str = "2987654321",
    shortcode: str = "CabCdEfGhi",
    taken_at: int = 4102444800,  # year 2100 — always within window
    username: str = "techcreator",
    caption: str = "Top AI tools for productivity\nThread below",
    likes: int = 1500,
    comments: int = 80,
    views: int = 25000,
) -> dict[str, Any]:
    return {
        "id": media_id,
        "pk": media_id,
        "code": shortcode,
        "taken_at": taken_at,
        "taken_at_timestamp": taken_at,
        "user": {"username": username, "pk": "111222333"},
        "caption": {"text": caption},
        "like_count": likes,
        "comment_count": comments,
        "video_view_count": views,
    }


async def mock_fetcher_single(hashtag: str, limit: int) -> list[dict[str, Any]]:
    return [make_raw_media()]


async def mock_fetcher_empty(hashtag: str, limit: int) -> list[dict[str, Any]]:
    return []


async def mock_fetcher_old(hashtag: str, limit: int) -> list[dict[str, Any]]:
    return [make_raw_media(taken_at=0)]  # epoch — very old


def test_instagram_adapter_search_returns_items() -> None:
    settings = load_settings()
    adapter = InstagramAdapter(settings=settings, page_fetcher=mock_fetcher_single)

    items = adapter.search("ai tools", days=30, limit=10)

    assert len(items) == 1
    item = items[0]
    assert item.source_id == "2987654321"
    assert item.title == "Top AI tools for productivity"
    assert item.author == "techcreator"
    assert item.metrics.likes == 1500
    assert item.metrics.comments == 80
    assert item.metrics.views == 25000
    assert item.tags == ["#aitools"]
    assert item.url == "https://www.instagram.com/p/CabCdEfGhi/"
    assert item.score > 0


def test_instagram_adapter_disabled_returns_empty() -> None:
    os.environ["INSTAGRAM_ENABLE"] = "false"
    try:
        from last30free.config import load_settings as ls

        settings = ls()
        adapter = InstagramAdapter(settings=settings, page_fetcher=mock_fetcher_single)
        items = adapter.search("ai tools", days=30, limit=10)
        assert items == []
    finally:
        del os.environ["INSTAGRAM_ENABLE"]


def test_instagram_adapter_filters_old_content() -> None:
    settings = load_settings()
    adapter = InstagramAdapter(settings=settings, page_fetcher=mock_fetcher_old)
    items = adapter.search("aitools", days=30, limit=10)
    assert items == []


def test_instagram_adapter_empty_source_returns_empty() -> None:
    settings = load_settings()
    adapter = InstagramAdapter(settings=settings, page_fetcher=mock_fetcher_empty)
    items = adapter.search("aitools", days=30, limit=10)
    assert items == []


def test_instagram_adapter_hashtag_normalisation() -> None:
    """Topic with spaces and uppercase is normalised to a lowercase hashtag."""
    captured: list[str] = []

    async def capturing_fetcher(hashtag: str, limit: int) -> list[dict[str, Any]]:
        captured.append(hashtag)
        return []

    settings = load_settings()
    adapter = InstagramAdapter(settings=settings, page_fetcher=capturing_fetcher)
    adapter.search("Machine Learning", days=30, limit=10)

    assert captured == ["machinelearning"]


def test_instagram_adapter_deduplication() -> None:
    async def duplicates_fetcher(hashtag: str, limit: int) -> list[dict[str, Any]]:
        return [make_raw_media(media_id="dup"), make_raw_media(media_id="dup")]

    settings = load_settings()
    adapter = InstagramAdapter(settings=settings, page_fetcher=duplicates_fetcher)
    items = adapter.search("aitools", days=30, limit=10)
    assert len(items) == 1


def test_instagram_adapter_respects_limit() -> None:
    async def many_fetcher(hashtag: str, limit: int) -> list[dict[str, Any]]:
        return [make_raw_media(media_id=str(i)) for i in range(20)]

    settings = load_settings()
    adapter = InstagramAdapter(settings=settings, page_fetcher=many_fetcher)
    items = adapter.search("aitools", days=30, limit=5)
    assert len(items) <= 5


def test_instagram_adapter_score_positive() -> None:
    settings = load_settings()
    adapter = InstagramAdapter(settings=settings, page_fetcher=mock_fetcher_single)
    items = adapter.search("aitools", days=30, limit=10)
    assert all(item.score > 0 for item in items)
