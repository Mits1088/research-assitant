"""
Video transcript extraction for the last30free enrichment layer.

Strategy per item:
  1. yt-dlp subtitle/caption extraction — fast, no audio download needed
  2. yt-dlp audio download → Whisper transcription — slower (~1 min/video)

Whisper backend detection (tries in order):
  - faster-whisper  (pip install faster-whisper)
  - openai-whisper  (pip install openai-whisper)

Both are tried automatically — whichever is installed will be used.

Sources that support transcript extraction:
  tiktok, instagram, youtube, x (video tweets), facebook (public)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Sources where yt-dlp video/audio download is viable
VIDEO_SOURCES = {"tiktok", "instagram", "youtube", "x", "facebook"}


class VideoFetchError(Exception):
    pass


# ── VTT subtitle parser ───────────────────────────────────────────────────────

_TIMING_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}",
    re.MULTILINE,
)


def _parse_vtt(vtt_text: str) -> str:
    """Extract clean readable text from a WebVTT or SRT subtitle file."""
    lines = vtt_text.splitlines()
    text_lines: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if _TIMING_RE.match(line):
            continue
        if re.match(r"^\d+$", line):  # SRT-style cue index
            continue
        # Strip inline HTML tags (e.g. <c>, <i>, timestamps)
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line:
            text_lines.append(line)

    # Deduplicate adjacent identical lines (common in rolling auto-captions)
    deduped: list[str] = []
    prev = ""
    for line in text_lines:
        if line != prev:
            deduped.append(line)
            prev = line

    return " ".join(deduped).strip()


# ── Cookie helpers ────────────────────────────────────────────────────────────

def _write_instagram_cookies(session_id: str, run_dir: Path) -> Path:
    """Write a temporary Netscape-format cookies.txt for yt-dlp Instagram access."""
    cookies_path = run_dir / "_ig_cookies_tmp.txt"
    cookies_path.write_text(
        "# Netscape HTTP Cookie File\n"
        f".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\t{session_id}\n",
        encoding="utf-8",
    )
    return cookies_path


# ── yt-dlp helpers ────────────────────────────────────────────────────────────

def _try_subtitles(
    url: str,
    source_id: str,
    run_dir: Path,
    cookies_file: Path | None,
) -> str:
    """
    Ask yt-dlp for auto-generated subtitles without downloading the video.
    Returns extracted text, or empty string if no subtitles are available.
    """
    import yt_dlp  # already a project dependency

    safe_id = re.sub(r"[^a-z0-9]", "_", source_id.lower())[:40]
    sub_base = str(run_dir / f"_sub_{safe_id}")

    ydl_opts: dict[str, Any] = {
        "skip_download": True,
        "writeautomaticsub": True,
        "writesubtitles": True,
        "subtitleslangs": ["en", "en-US", "en-GB"],
        "subtitlesformat": "vtt",
        "outtmpl": sub_base + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
    }
    if cookies_file:
        ydl_opts["cookiefile"] = str(cookies_file)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception:
        pass

    for vtt_file in run_dir.glob(f"_sub_{safe_id}*.vtt"):
        try:
            text = _parse_vtt(vtt_file.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            text = ""
        finally:
            vtt_file.unlink(missing_ok=True)
        if text:
            return text

    return ""


def _download_audio(
    url: str,
    source_id: str,
    run_dir: Path,
    cookies_file: Path | None,
) -> Path | None:
    """
    Download audio-only track via yt-dlp. Returns path to the audio file,
    or None if the download failed.
    Requires ffmpeg to be installed for the mp3 conversion post-processor.
    Falls back to raw audio format if ffmpeg is not available.
    """
    import yt_dlp

    safe_id = re.sub(r"[^a-z0-9]", "_", source_id.lower())[:40]
    audio_base = str(run_dir / f"_audio_{safe_id}")

    ydl_opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": audio_base + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
    }
    if cookies_file:
        ydl_opts["cookiefile"] = str(cookies_file)

    # Try with ffmpeg mp3 conversion first; fall back to raw if ffmpeg missing
    for postprocessors in (
        [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "64"}],
        [],
    ):
        opts = {**ydl_opts, "postprocessors": postprocessors}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            break
        except Exception:
            continue

    for ext in ["mp3", "m4a", "opus", "webm", "ogg", "wav"]:
        candidate = Path(f"{audio_base}.{ext}")
        if candidate.exists():
            return candidate

    return None


# ── Whisper transcription ─────────────────────────────────────────────────────

def _transcribe_with_whisper(audio_path: Path, model_size: str) -> str:
    """
    Transcribe audio using whichever Whisper backend is installed.
    Tries faster-whisper first (faster, same quality), then openai-whisper.
    Raises VideoFetchError if neither is installed.
    """
    # faster-whisper (CTranslate2 backend — faster inference)
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_path), beam_size=5)
        return " ".join(seg.text.strip() for seg in segments).strip()
    except ImportError:
        pass
    except Exception as exc:
        raise VideoFetchError(f"faster-whisper transcription failed: {exc}") from exc

    # openai-whisper (original PyTorch backend)
    try:
        import whisper  # type: ignore[import-untyped]
        model = whisper.load_model(model_size)
        result = model.transcribe(str(audio_path))
        return str(result.get("text", "")).strip()
    except ImportError:
        pass
    except Exception as exc:
        raise VideoFetchError(f"openai-whisper transcription failed: {exc}") from exc

    raise VideoFetchError(
        "No Whisper installation found. Install one of:\n"
        "  pip install faster-whisper    (recommended — faster)\n"
        "  pip install openai-whisper"
    )


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_transcript(
    item_url: str,
    item_source: str,
    source_id: str,
    *,
    run_dir: Path,
    whisper_model: str = "small",
    instagram_session_id: str = "",
) -> tuple[str, str]:
    """
    Download and transcribe a video item.

    Returns (transcript_text, source_label) where source_label is one of:
      "subtitles" — extracted from auto-generated captions (fast)
      "whisper"   — transcribed from downloaded audio (slower)
      ""          — extraction silently failed (e.g. no video, geo-blocked)

    Raises VideoFetchError for hard failures (e.g. no Whisper installed).
    """
    if item_source not in VIDEO_SOURCES:
        return "", ""

    cookies_file: Path | None = None
    if item_source == "instagram" and instagram_session_id:
        cookies_file = _write_instagram_cookies(instagram_session_id, run_dir)

    try:
        # Step 1: fast path — subtitles only, no download
        sub_text = _try_subtitles(item_url, source_id, run_dir, cookies_file)
        if sub_text:
            return sub_text, "subtitles"

        # Step 2: download audio + Whisper
        audio_path = _download_audio(item_url, source_id, run_dir, cookies_file)
        if audio_path and audio_path.exists():
            try:
                transcript = _transcribe_with_whisper(audio_path, whisper_model)
                if transcript:
                    return transcript, "whisper"
            finally:
                audio_path.unlink(missing_ok=True)

    finally:
        if cookies_file and cookies_file.exists():
            cookies_file.unlink(missing_ok=True)

    return "", ""
