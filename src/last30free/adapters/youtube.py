from __future__ import annotations

import math
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import orjson

from last30free.config import Settings
from last30free.models import EngagementMetrics, ResearchItem, ResearchQuote, SourceName

from .base import AdapterError, BaseAdapter

CommandRunner = Callable[[list[str], Path | None], subprocess.CompletedProcess[str]]


class YouTubeAdapter(BaseAdapter):
    source_name = SourceName.YOUTUBE

    def __init__(
        self,
        settings: Settings,
        runner: CommandRunner | None = None,
    ) -> None:
        super().__init__(
            user_agent=settings.app.user_agent,
            timeout_seconds=settings.app.request_timeout_seconds,
        )
        self.settings = settings
        self.runner = runner or self._run_command
        self.work_dir = settings.app.cache_dir / "youtube"
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def search(self, topic: str, *, days: int, limit: int) -> list[ResearchItem]:
        effective_limit = max(1, min(limit, self.settings.youtube.search_limit))
        payload = self._search_payload(topic, effective_limit)
        entries = payload.get("entries", []) or []
        cutoff = self.cutoff_datetime(days)

        items: list[ResearchItem] = []
        seen_ids: set[str] = set()

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            source_id = str(entry.get("id", "")).strip()
            if not source_id or source_id in seen_ids:
                continue

            created_at = self._extract_created_at(entry)
            if created_at is None:
                continue
            if created_at < cutoff:
                continue

            item = self._to_item(entry, created_at)
            items.append(item)
            seen_ids.add(source_id)

            if len(items) >= effective_limit:
                break

        self._enrich_transcripts(items)
        return self.sort_items(items)

    def _run_command(
        self,
        cmd: list[str],
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        # Invoke yt-dlp via sys.executable to ensure it is found on Windows
        # where the Scripts directory may not be on PATH for bash shells.
        patched = [sys.executable, "-m", "yt_dlp", *cmd[1:]]
        return subprocess.run(
            patched,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
        )

    def _search_payload(self, topic: str, limit: int) -> dict[str, Any]:
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--dump-single-json",
            "--no-warnings",
            f"ytsearch{limit}:{topic}",
        ]
        result = self.runner(cmd, None)

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "yt-dlp search failed"
            raise AdapterError(f"YouTube search failed: {message}")

        stdout = result.stdout.strip()
        if not stdout:
            raise AdapterError("YouTube search returned empty output")

        try:
            payload = orjson.loads(stdout)
        except orjson.JSONDecodeError as exc:
            raise AdapterError("YouTube search returned invalid JSON") from exc

        if isinstance(payload, dict):
            return payload

        raise AdapterError("YouTube search payload had unexpected shape")

    def _extract_created_at(self, entry: dict[str, Any]) -> datetime | None:
        for field in ("timestamp", "release_timestamp"):
            value = entry.get(field)
            if value is None:
                continue
            try:
                return datetime.fromtimestamp(int(value), tz=timezone.utc)
            except (TypeError, ValueError):
                continue

        upload_date = str(entry.get("upload_date", "")).strip()
        if upload_date and re.fullmatch(r"\d{8}", upload_date):
            try:
                return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
            except ValueError:
                return None

        return None

    def _to_item(self, entry: dict[str, Any], created_at: datetime) -> ResearchItem:
        source_id = str(entry.get("id", "")).strip()
        title = str(entry.get("title", "")).strip() or "(untitled)"
        description = str(entry.get("description", "") or "").strip()
        channel = (
            str(entry.get("channel", "")).strip()
            or str(entry.get("uploader", "")).strip()
            or "unknown"
        )
        url = str(entry.get("webpage_url", "")).strip() or f"https://www.youtube.com/watch?v={source_id}"

        views = int(entry.get("view_count", 0) or 0)
        likes = int(entry.get("like_count", 0) or 0)

        metrics = EngagementMetrics(
            views=views,
            likes=likes,
        )

        score = self._score_item(
            views=views,
            likes=likes,
            created_at=created_at,
        )

        return ResearchItem(
            source=SourceName.YOUTUBE,
            source_id=source_id,
            url=url,
            title=title,
            text=self._combine_text(title, description),
            author=channel,
            created_at=created_at,
            score=score,
            metrics=metrics,
            quotes=[],
            tags=[f"channel:{channel}"] if channel else [],
            raw={
                "channel": channel,
                "duration": entry.get("duration"),
                "thumbnail": entry.get("thumbnail"),
                "uploader_id": entry.get("uploader_id"),
            },
        )

    def _combine_text(self, title: str, description: str) -> str:
        if title and description:
            return f"{title}\n\n{description}"
        return title or description

    def _score_item(self, *, views: int, likes: int, created_at: datetime) -> float:
        age_days = max(
            0.0,
            (datetime.now(timezone.utc) - created_at).total_seconds() / 86400.0,
        )
        recency_boost = max(0.2, 1.0 - (age_days / 30.0))
        engagement = math.log1p(max(views, 0) / 100.0) + (0.8 * math.log1p(max(likes, 0) * 2))
        return round(engagement * recency_boost, 4)

    def _enrich_transcripts(self, items: list[ResearchItem]) -> None:
        if not items:
            return

        ranked = self.sort_items(items)
        top_n = min(5, len(ranked))

        for item in ranked[:top_n]:
            quotes = self._fetch_transcript_quotes(
                video_id=item.source_id,
                video_url=item.url,
                channel=str(item.raw.get("channel", "")).strip() or item.author or "YouTube",
            )
            item.quotes.extend(quotes)

    def _fetch_transcript_quotes(
        self,
        *,
        video_id: str,
        video_url: str,
        channel: str,
    ) -> list[ResearchQuote]:
        with tempfile.TemporaryDirectory(dir=self.work_dir) as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            output_template = str(tmpdir / "%(id)s.%(ext)s")

            cmd = [
                "yt-dlp",
                "--skip-download",
                "--no-warnings",
            ]

            if self.settings.youtube.write_subs:
                cmd.append("--write-subs")
            if self.settings.youtube.write_auto_subs:
                cmd.append("--write-auto-subs")

            cmd.extend(
                [
                    "--sub-langs",
                    self.settings.youtube.sub_langs,
                    "--sub-format",
                    "vtt/srt/best",
                    "-o",
                    output_template,
                    video_url,
                ]
            )

            result = self.runner(cmd, tmpdir)
            if result.returncode != 0:
                return []

            transcript_text = self._load_best_subtitle_text(tmpdir, video_id)
            if not transcript_text:
                return []

            return self._transcript_to_quotes(transcript_text, channel)

    def _load_best_subtitle_text(self, tmpdir: Path, video_id: str) -> str:
        candidates = sorted(tmpdir.glob(f"{video_id}*"))
        if not candidates:
            return ""

        preferred_suffixes = [".vtt", ".srt"]

        for suffix in preferred_suffixes:
            for path in candidates:
                if path.suffix.lower() == suffix:
                    text = self._read_subtitle_file(path)
                    if text:
                        return text

        return ""

    def _read_subtitle_file(self, path: Path) -> str:
        try:
            raw_text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

        suffix = path.suffix.lower()
        if suffix == ".vtt":
            return self._clean_vtt(raw_text)
        if suffix == ".srt":
            return self._clean_srt(raw_text)
        return ""

    def _clean_vtt(self, raw_text: str) -> str:
        lines = raw_text.splitlines()
        cleaned: list[str] = []

        for line in lines:
            value = line.strip()
            if not value:
                continue
            if value == "WEBVTT":
                continue
            if value.startswith("NOTE"):
                continue
            if "-->" in value:
                continue
            if value.isdigit():
                continue

            value = re.sub(r"<[^>]+>", "", value)
            value = value.replace("&nbsp;", " ").strip()
            if not value:
                continue

            if not cleaned or cleaned[-1] != value:
                cleaned.append(value)

        return " ".join(cleaned).strip()

    def _clean_srt(self, raw_text: str) -> str:
        lines = raw_text.splitlines()
        cleaned: list[str] = []

        for line in lines:
            value = line.strip()
            if not value:
                continue
            if value.isdigit():
                continue
            if "-->" in value:
                continue

            value = re.sub(r"<[^>]+>", "", value).strip()
            if not value:
                continue

            if not cleaned or cleaned[-1] != value:
                cleaned.append(value)

        return " ".join(cleaned).strip()

    def _transcript_to_quotes(self, transcript_text: str, channel: str) -> list[ResearchQuote]:
        normalized = re.sub(r"\s+", " ", transcript_text).strip()
        if not normalized:
            return []

        sentences = re.split(r"(?<=[.!?])\s+", normalized)
        chunks: list[str] = []
        current = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if not current:
                current = sentence
                continue

            proposed = f"{current} {sentence}".strip()
            if len(proposed) <= 240:
                current = proposed
            else:
                chunks.append(current)
                current = sentence

            if len(chunks) >= 3:
                break

        if current and len(chunks) < 3:
            chunks.append(current)

        return [
            ResearchQuote(
                text=chunk,
                author=channel,
                score=None,
                source_label=f"{channel} on YouTube",
            )
            for chunk in chunks[:3]
            if chunk
        ]
