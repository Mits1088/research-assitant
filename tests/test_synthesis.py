from __future__ import annotations

from datetime import datetime, timezone

from last30free.models import EngagementMetrics, IntentParse, QueryType, ResearchItem, SourceName
from last30free.synthesis import synthesize


def make_item(
    *,
    source: SourceName,
    source_id: str,
    title: str,
    text: str,
    score: float,
    author: str,
    metrics: EngagementMetrics,
    tags: list[str] | None = None,
    raw: dict | None = None,
) -> ResearchItem:
    return ResearchItem(
        source=source,
        source_id=source_id,
        url=f"https://example.com/{source_id}",
        title=title,
        text=text,
        author=author,
        created_at=datetime(2100, 1, 1, tzinfo=timezone.utc),
        score=score,
        metrics=metrics,
        tags=tags or [],
        raw=raw or {},
    )


def test_synthesis_builds_headline_patterns_and_stats() -> None:
    items = [
        make_item(
            source=SourceName.REDDIT,
            source_id="r1",
            title="Workflow-first AI coding setup",
            text="People keep debating workflow fit and agent depth.",
            score=9.5,
            author="alice",
            metrics=EngagementMetrics(upvotes=120, comments=18),
            tags=["r/artificial"],
        ),
        make_item(
            source=SourceName.HN,
            source_id="h1",
            title="Show HN: workflow orchestration for coding agents",
            text="This thread focuses on workflow depth and integrations.",
            score=8.9,
            author="bob",
            metrics=EngagementMetrics(points=90, comments=25),
            tags=["show_hn"],
        ),
        make_item(
            source=SourceName.YOUTUBE,
            source_id="y1",
            title="Best workflow AI coding tools this month",
            text="A long review of workflow choices and editor integrations.",
            score=8.2,
            author="BuildWithAI",
            metrics=EngagementMetrics(views=15000, likes=700),
            tags=["channel:BuildWithAI"],
            raw={"channel": "BuildWithAI"},
        ),
        make_item(
            source=SourceName.X,
            source_id="x1",
            title="Workflow fit matters more than model hype",
            text="Workflow fit matters more than hype in AI coding tools.",
            score=7.7,
            author="Build With AI",
            metrics=EngagementMetrics(likes=320, reposts=44, comments=12),
            raw={"username": "buildwithai"},
        ),
    ]

    intent = IntentParse(
        raw_query="latest ai coding tools",
        topic="ai coding tools",
        target_tool="unknown",
        query_type=QueryType.GENERAL,
    )

    results = {
        "reddit": {"status": "ok", "count": 1, "error": None},
        "hn": {"status": "ok", "count": 1, "error": None},
        "youtube": {"status": "ok", "count": 1, "error": None},
        "x": {"status": "ok", "count": 1, "error": None},
    }

    synthesis = synthesize(items, intent=intent, results=results)

    assert "ai coding tools" in synthesis["headline"].lower()
    assert synthesis["total_items"] == 4
    assert len(synthesis["summary_points"]) >= 4
    assert len(synthesis["patterns"]) >= 1
    assert any(pattern["keyword"] == "workflow" for pattern in synthesis["patterns"])
    assert any(row["source"] == "reddit" and row["count"] == 1 for row in synthesis["source_stats"])
    assert any(row["source"] == "youtube" and row["total_1"] == 15000 for row in synthesis["source_stats"])
