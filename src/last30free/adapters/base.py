from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Iterable

from last30free.models import ResearchItem, SourceName


class AdapterError(RuntimeError):
    """Raised when a source adapter cannot complete a request."""


class BaseAdapter(ABC):
    source_name: SourceName

    def __init__(self, *, user_agent: str, timeout_seconds: int) -> None:
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

    @staticmethod
    def cutoff_datetime(days: int) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=days)

    @staticmethod
    def sort_items(items: Iterable[ResearchItem]) -> list[ResearchItem]:
        return sorted(items, key=lambda item: item.score, reverse=True)

    @abstractmethod
    def search(self, topic: str, *, days: int, limit: int) -> list[ResearchItem]:
        raise NotImplementedError

    def close(self) -> None:
        """Optional cleanup hook for adapters that own network clients."""
        return None
