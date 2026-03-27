from __future__ import annotations

import subprocess
from pathlib import Path

from last30free.adapters.youtube import YouTubeAdapter
from last30free.config import load_settings


def build_runner():
    def runner(cmd: list[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
        if "--dump-single-json" in cmd:
            stdout = """
            {
              "_type": "playlist",
              "entries": [
                {
                  "id": "yt001",
                  "title": "Best AI coding tools this month",
                  "description": "Current recommendations and comparisons.",
                  "channel": "BuildWithAI",
                  "webpage_url": "https://www.youtube.com/watch?v=yt001",
                  "view_count": 12345,
                  "like_count": 678,
                  "timestamp": 4102444800
                }
              ]
            }
            """
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

        output_template = cmd[cmd.index("-o") + 1]
        subtitle_path = Path(output_template.replace("%(id)s", "yt001").replace("%(ext)s", "en.vtt"))
        subtitle_path.write_text(
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.000\n"
            "These tools are getting adopted fast.\n\n"
            "00:00:02.000 --> 00:00:05.000\n"
            "The biggest differentiator is workflow fit.\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return runner


def test_youtube_adapter_search_returns_items_and_quotes() -> None:
    settings = load_settings()
    adapter = YouTubeAdapter(settings=settings, runner=build_runner())

    items = adapter.search("best ai coding tools", days=30, limit=10)

    assert len(items) == 1
    item = items[0]
    assert item.source_id == "yt001"
    assert item.title == "Best AI coding tools this month"
    assert item.metrics.views == 12345
    assert item.metrics.likes == 678
    assert item.author == "BuildWithAI"
    assert item.tags == ["channel:BuildWithAI"]
    assert len(item.quotes) >= 1
    assert "workflow fit" in " ".join(quote.text for quote in item.quotes)
