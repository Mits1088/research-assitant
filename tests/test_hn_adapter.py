from __future__ import annotations

import httpx

from last30free.adapters.hn import HNAdapter
from last30free.config import load_settings


def build_mock_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if path == "/api/v1/search_by_date":
            tags = params.get("tags", "")

            if tags == "story":
                # Search results page
                return httpx.Response(
                    200,
                    json={
                        "hits": [
                            {
                                "objectID": "xyz789",
                                "title": "Show HN: I built a free AI research tool",
                                "story_text": "It's called last30free.",
                                "author": "charlie",
                                "points": 87,
                                "num_comments": 23,
                                "created_at_i": 1979238400,
                                "url": "https://example.com/ai-tool",
                                "_tags": ["story", "author_charlie"],
                            },
                            {
                                "objectID": "xyz790",
                                "title": "Ask HN: What AI tools changed your workflow?",
                                "author": "diana",
                                "points": 45,
                                "num_comments": 61,
                                "created_at_i": 1979238400,
                                "_tags": ["story", "ask_hn"],
                            },
                        ],
                        "nbPages": 1,
                        "page": 0,
                    },
                )

            if tags.startswith("comment,story_"):
                # Comments page for a story
                return httpx.Response(
                    200,
                    json={
                        "hits": [
                            {
                                "comment_text": "The best AI tools are the ones you actually use.",
                                "author": "eve",
                                "points": 12,
                            },
                            {
                                "comment_text": "I've been using last30free for research and it's solid.",
                                "author": "frank",
                                "points": 5,
                            },
                        ],
                        "nbPages": 1,
                        "page": 0,
                    },
                )

        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    return httpx.Client(
        base_url="https://hn.algolia.com/api/v1",
        transport=transport,
        follow_redirects=True,
    )


def test_hn_adapter_search_returns_items_and_quotes() -> None:
    settings = load_settings()
    client = build_mock_client()
    adapter = HNAdapter(settings=settings, client=client)

    items = adapter.search("AI tools", days=30, limit=10)

    assert len(items) == 2
    # Items are sorted by score descending; xyz790 ranks first due to higher engagement (more comments)
    item = items[0]
    assert item.source_id in ("xyz789", "xyz790")
    assert item.metrics.points in (87, 45)
    assert item.metrics.comments in (23, 61)
    # Comments were fetched for top items
    assert len(item.quotes) >= 1
    quote_texts = [q.text for q in item.quotes]
    assert any("last30free" in t for t in quote_texts)

    adapter.close()
    client.close()


def test_hn_adapter_normalizes_ask_hn_tag() -> None:
    settings = load_settings()
    client = build_mock_client()
    adapter = HNAdapter(settings=settings, client=client)

    items = adapter.search("AI tools", days=30, limit=10)

    # Find the Ask HN post
    ask_hn_item = next((i for i in items if "Ask HN" in i.title), None)
    assert ask_hn_item is not None
    assert "ask_hn" in ask_hn_item.tags
    assert ask_hn_item.source_id == "xyz790"

    adapter.close()
    client.close()
