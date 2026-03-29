from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    PROMPTING = "PROMPTING"
    RECOMMENDATIONS = "RECOMMENDATIONS"
    NEWS = "NEWS"
    COMPARISON = "COMPARISON"
    GENERAL = "GENERAL"


class SourceName(str, Enum):
    REDDIT = "reddit"
    HN = "hn"
    YOUTUBE = "youtube"
    X = "x"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    FACEBOOK = "facebook"


ALL_SOURCES: set[str] = {s.value for s in SourceName}
SOURCE_ORDER: list[str] = [s.value for s in SourceName]


class IntentParse(BaseModel):
    raw_query: str
    topic: str
    target_tool: str = "unknown"
    query_type: QueryType
    topic_a: str | None = None
    topic_b: str | None = None


class EngagementMetrics(BaseModel):
    upvotes: int = 0
    comments: int = 0
    likes: int = 0
    reposts: int = 0
    views: int = 0
    points: int = 0


class ResearchQuote(BaseModel):
    text: str
    author: str | None = None
    score: int | None = None
    source_label: str | None = None


class ResearchItem(BaseModel):
    source: SourceName
    source_id: str
    url: str
    title: str = ""
    text: str = ""
    author: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    score: float = 0.0
    metrics: EngagementMetrics = Field(default_factory=EngagementMetrics)
    quotes: list[ResearchQuote] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class ResearchRun(BaseModel):
    query: str
    days: int = 30
    sources: list[SourceName] = Field(default_factory=list)
    items: list[ResearchItem] = Field(default_factory=list)


class Evidence(BaseModel):
    source_id: str
    url: str
    markdown: str = ""
    extracted_tools: list[str] = Field(default_factory=list)
    extracted_claims: list[str] = Field(default_factory=list)
    screenshot_path: str = ""
    enrich_status: str = "ok"
    enrich_error: str | None = None
    transcript: str = ""               # speech-to-text from video (yt-dlp subs or Whisper)
    transcript_source: str = ""        # "subtitles" / "whisper" / ""
    caption_article_url: str = ""      # URL extracted from post caption/description
    caption_article_markdown: str = "" # Jina markdown of that linked article


class AssetCandidate(BaseModel):
    source_id: str
    url: str
    title: str
    score: float = 0.0
    screenshot_path: str = ""
    pull_quotes: list[str] = Field(default_factory=list)
