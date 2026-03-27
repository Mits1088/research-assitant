from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


_FAKE_TWEET = {
    "id_str": "123456789",
    "full_text": "These AI coding tools are getting good fast. Workflow fit matters most.",
    "created_at": "Wed Jan 01 00:00:00 +0000 2100",
    "favorite_count": 333,
    "retweet_count": 22,
    "reply_count": 11,
    "lang": "en",
    "entities": {"hashtags": [{"text": "AI"}, {"text": "Coding"}]},
    "_user": {"screen_name": "buildwithai", "name": "Build With AI"},
}


async def mock_fetcher(topic: str, limit: int) -> list[dict[str, Any]]:
    return [_FAKE_TWEET]


async def mock_fetcher_empty(topic: str, limit: int) -> list[dict[str, Any]]:
    return []


def test_x_adapter_search_returns_items_and_quotes(monkeypatch) -> None:
    from last30free.adapters.x import XAdapter
    from last30free.config import load_settings

    monkeypatch.setenv("AUTH_TOKEN", "token123")
    monkeypatch.setenv("CT0", "ct0abc")
    monkeypatch.setenv("X_ENABLE", "true")

    settings = load_settings()
    adapter = XAdapter(settings=settings, page_fetcher=mock_fetcher)

    items = adapter.search("best ai coding tools", days=30, limit=10)

    assert len(items) == 1
    item = items[0]
    assert item.source_id == "123456789"
    assert item.author == "Build With AI"
    assert item.metrics.likes == 333
    assert item.metrics.reposts == 22
    assert item.metrics.comments == 11
    assert item.raw["username"] == "buildwithai"
    assert len(item.quotes) == 1
    assert "workflow fit" in item.quotes[0].text.lower()


def test_x_adapter_disabled_returns_empty(monkeypatch) -> None:
    from last30free.adapters.x import XAdapter
    from last30free.config import load_settings

    monkeypatch.setenv("AUTH_TOKEN", "token123")
    monkeypatch.setenv("CT0", "ct0abc")
    monkeypatch.setenv("X_ENABLE", "false")

    settings = load_settings()
    adapter = XAdapter(settings=settings, page_fetcher=mock_fetcher)
    items = adapter.search("ai tools", days=30, limit=10)
    assert items == []


def test_x_adapter_not_configured_raises(monkeypatch) -> None:
    from last30free.adapters.x import XAdapter
    from last30free.config import load_settings
    from last30free.adapters.base import AdapterError

    monkeypatch.setenv("AUTH_TOKEN", "")
    monkeypatch.setenv("CT0", "")
    monkeypatch.setenv("X_ENABLE", "true")

    settings = load_settings()
    adapter = XAdapter(settings=settings, page_fetcher=mock_fetcher)

    try:
        adapter.search("ai tools", days=30, limit=10)
        assert False, "Should have raised AdapterError"
    except AdapterError:
        pass


def test_x_adapter_filters_old_content(monkeypatch) -> None:
    from last30free.adapters.x import XAdapter
    from last30free.config import load_settings

    monkeypatch.setenv("AUTH_TOKEN", "token123")
    monkeypatch.setenv("CT0", "ct0abc")
    monkeypatch.setenv("X_ENABLE", "true")

    old_tweet = {**_FAKE_TWEET, "created_at": "Mon Jan 01 00:00:00 +0000 2000"}

    async def old_fetcher(topic: str, limit: int) -> list[dict[str, Any]]:
        return [old_tweet]

    settings = load_settings()
    adapter = XAdapter(settings=settings, page_fetcher=old_fetcher)
    items = adapter.search("ai tools", days=30, limit=10)
    assert items == []


def test_x_adapter_deduplication(monkeypatch) -> None:
    from last30free.adapters.x import XAdapter
    from last30free.config import load_settings

    monkeypatch.setenv("AUTH_TOKEN", "token123")
    monkeypatch.setenv("CT0", "ct0abc")
    monkeypatch.setenv("X_ENABLE", "true")

    async def dup_fetcher(topic: str, limit: int) -> list[dict[str, Any]]:
        return [_FAKE_TWEET, _FAKE_TWEET]

    settings = load_settings()
    adapter = XAdapter(settings=settings, page_fetcher=dup_fetcher)
    items = adapter.search("ai tools", days=30, limit=10)
    assert len(items) == 1


def test_x_adapter_respects_limit(monkeypatch) -> None:
    from last30free.adapters.x import XAdapter
    from last30free.config import load_settings

    monkeypatch.setenv("AUTH_TOKEN", "token123")
    monkeypatch.setenv("CT0", "ct0abc")
    monkeypatch.setenv("X_ENABLE", "true")

    tweets = [
        {**_FAKE_TWEET, "id_str": str(i), "favorite_count": i}
        for i in range(1, 10)
    ]

    async def multi_fetcher(topic: str, limit: int) -> list[dict[str, Any]]:
        return tweets

    settings = load_settings()
    adapter = XAdapter(settings=settings, page_fetcher=multi_fetcher)
    items = adapter.search("ai tools", days=30, limit=3)
    assert len(items) <= 3
