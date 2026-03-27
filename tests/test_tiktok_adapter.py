from __future__ import annotations

import asyncio
from typing import Any

from last30free.adapters.tiktok import TikTokAdapter
from last30free.config import load_settings


def make_raw_video(
    *,
    video_id: str = "video123",
    desc: str = "Amazing AI tools you need to try",
    create_time: int = 4102444800,  # year 2100 — always within window
    likes: int = 5000,
    comments: int = 200,
    shares: int = 100,
    views: int = 500000,
    author: str = "techtips",
) -> dict[str, Any]:
    return {
        "id": video_id,
        "desc": desc,
        "createTime": create_time,
        "stats": {
            "diggCount": likes,
            "commentCount": comments,
            "shareCount": shares,
            "playCount": views,
        },
        "author": {"uniqueId": author, "nickname": "Tech Tips"},
    }


async def mock_fetcher_single(hashtag: str, limit: int) -> list[dict[str, Any]]:
    return [make_raw_video()]


async def mock_fetcher_empty(hashtag: str, limit: int) -> list[dict[str, Any]]:
    return []


async def mock_fetcher_old_video(hashtag: str, limit: int) -> list[dict[str, Any]]:
    return [make_raw_video(create_time=0)]  # epoch — very old


def test_tiktok_adapter_search_returns_items() -> None:
    settings = load_settings()
    adapter = TikTokAdapter(settings=settings, page_fetcher=mock_fetcher_single)

    items = adapter.search("ai tools", days=30, limit=10)

    assert len(items) == 1
    item = items[0]
    assert item.source_id == "video123"
    assert item.title == "Amazing AI tools you need to try"
    assert item.author == "techtips"
    assert item.metrics.likes == 5000
    assert item.metrics.comments == 200
    assert item.metrics.reposts == 100
    assert item.metrics.views == 500000
    assert item.tags == ["#aitools"]
    assert item.url == "https://www.tiktok.com/@techtips/video/video123"
    assert item.score > 0


def test_tiktok_adapter_empty_source_returns_empty() -> None:
    settings = load_settings()
    adapter = TikTokAdapter(settings=settings, page_fetcher=mock_fetcher_empty)
    items = adapter.search("ai tools", days=30, limit=10)
    assert items == []


def test_tiktok_adapter_filters_old_content() -> None:
    settings = load_settings()
    adapter = TikTokAdapter(settings=settings, page_fetcher=mock_fetcher_old_video)
    items = adapter.search("ai tools", days=30, limit=10)
    assert items == []


def test_tiktok_adapter_disabled_returns_empty() -> None:
    import os

    os.environ["TIKTOK_ENABLE"] = "false"
    try:
        from last30free.config import load_settings as ls

        settings = ls()
        adapter = TikTokAdapter(settings=settings, page_fetcher=mock_fetcher_single)
        items = adapter.search("ai tools", days=30, limit=10)
        assert items == []
    finally:
        del os.environ["TIKTOK_ENABLE"]


def test_tiktok_adapter_hashtag_normalisation() -> None:
    """Topic with spaces is normalised to a single-word hashtag tag."""
    captured: list[str] = []

    async def capturing_fetcher(hashtag: str, limit: int) -> list[dict[str, Any]]:
        captured.append(hashtag)
        return []

    settings = load_settings()
    adapter = TikTokAdapter(settings=settings, page_fetcher=capturing_fetcher)
    adapter.search("Machine Learning", days=30, limit=10)

    assert captured == ["machinelearning"]


def test_tiktok_adapter_deduplication() -> None:
    async def duplicates_fetcher(hashtag: str, limit: int) -> list[dict[str, Any]]:
        return [make_raw_video(video_id="dup"), make_raw_video(video_id="dup")]

    settings = load_settings()
    adapter = TikTokAdapter(settings=settings, page_fetcher=duplicates_fetcher)
    items = adapter.search("ai tools", days=30, limit=10)
    assert len(items) == 1


def test_tiktok_adapter_respects_limit() -> None:
    async def many_fetcher(hashtag: str, limit: int) -> list[dict[str, Any]]:
        return [make_raw_video(video_id=str(i)) for i in range(20)]

    settings = load_settings()
    adapter = TikTokAdapter(settings=settings, page_fetcher=many_fetcher)
    items = adapter.search("ai tools", days=30, limit=5)
    assert len(items) <= 5


def test_tiktok_adapter_score_positive() -> None:
    settings = load_settings()
    adapter = TikTokAdapter(settings=settings, page_fetcher=mock_fetcher_single)
    items = adapter.search("ai tools", days=30, limit=10)
    assert all(item.score > 0 for item in items)
