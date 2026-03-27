from __future__ import annotations

import httpx

from last30free.adapters.reddit import RedditAdapter
from last30free.config import load_settings


def build_mock_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if path == "/search.json":
            payload = {
                "data": {
                    "after": None,
                    "children": [
                        {
                            "kind": "t3",
                            "data": {
                                "id": "abc123",
                                "title": "Best AI tools this month",
                                "selftext": "People are sharing current favorites.",
                                "author": "alice",
                                "subreddit": "artificial",
                                "ups": 125,
                                "num_comments": 18,
                                "created_utc": 4102444800,  # year 2100
                                "permalink": "/r/artificial/comments/abc123/best_ai_tools_this_month/",
                                "domain": "self.artificial",
                                "over_18": False,
                            },
                        }
                    ],
                }
            }
            return httpx.Response(200, json=payload)

        if path == "/r/artificial/comments/abc123/best_ai_tools_this_month/.json":
            payload = [
                {"data": {"children": []}},
                {
                    "data": {
                        "children": [
                            {
                                "kind": "t1",
                                "data": {
                                    "body": "The strongest picks are the ones with real workflow fit.",
                                    "author": "bob",
                                    "ups": 44,
                                },
                            }
                        ]
                    }
                },
            ]
            return httpx.Response(200, json=payload)

        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    return httpx.Client(
        base_url="https://www.reddit.com",
        transport=transport,
        follow_redirects=True,
    )


def test_reddit_adapter_search_returns_items_and_quotes() -> None:
    settings = load_settings()
    client = build_mock_client()
    adapter = RedditAdapter(settings=settings, client=client)

    items = adapter.search("best ai tools", days=30, limit=10)

    assert len(items) == 1
    item = items[0]
    assert item.source_id == "abc123"
    assert item.title == "Best AI tools this month"
    assert item.metrics.upvotes == 125
    assert item.metrics.comments == 18
    assert item.tags == ["r/artificial"]
    assert len(item.quotes) == 1
    assert item.quotes[0].author == "bob"
    assert "workflow fit" in item.quotes[0].text

    adapter.close()
    client.close()
