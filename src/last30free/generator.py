"""
Content generation pipeline — turns saved research payloads into social/video content
using the Claude Agent SDK (reuses your existing Claude Code authentication).
"""
from __future__ import annotations

import anyio
import queue
import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any

_SKILLS_DIR = Path(__file__).parent / "skills"

FORMATS: dict[str, str] = {
    "facebook-post": "facebook_post.md",
    "instagram-carousel": "instagram_carousel.md",
    "instagram-reel": "instagram_reel.md",
    "youtube-script": "youtube_script.md",
}


class GeneratorError(Exception):
    pass


def list_formats() -> list[str]:
    return list(FORMATS.keys())


def _load_skill(format_name: str) -> str:
    filename = FORMATS.get(format_name)
    if filename is None:
        available = ", ".join(FORMATS.keys())
        raise GeneratorError(f"Unknown format '{format_name}'. Available: {available}")
    skill_path = _SKILLS_DIR / filename
    if not skill_path.exists():
        raise GeneratorError(f"Skill file not found: {skill_path}")
    return skill_path.read_text(encoding="utf-8").strip()


def _build_research_context(payload: dict[str, Any]) -> str:
    """Distil a research payload into a structured text block for Claude."""
    intent = payload.get("intent", {})
    synthesis = payload.get("synthesis", {})
    merged = payload.get("merged", {})
    runtime = payload.get("runtime", {})

    lines: list[str] = []

    topic = str(intent.get("topic") or "")
    query_type = str(intent.get("query_type") or "")
    days = runtime.get("days", 30)
    sources = ", ".join(runtime.get("selected_sources", []))

    lines.append("# Research brief")
    lines.append(f"**Topic:** {topic}")
    lines.append(f"**Query type:** {query_type}")
    lines.append(f"**Time window:** last {days} days")
    lines.append(f"**Sources searched:** {sources}")
    lines.append("")

    headline = str(synthesis.get("headline") or "")
    if headline:
        lines.append("## Synthesis headline")
        lines.append(headline)
        lines.append("")

    summary_points = synthesis.get("summary_points", [])
    if summary_points:
        lines.append("## Key takeaways")
        for point in summary_points:
            lines.append(f"- {point}")
        lines.append("")

    patterns = synthesis.get("patterns", [])
    if patterns:
        lines.append("## Recurring patterns")
        for p in patterns[:5]:
            kw = p.get("keyword", "")
            mentions = p.get("mentions", 0)
            sources_count = p.get("source_count", 0)
            examples = "; ".join(p.get("examples", [])[:2])
            lines.append(
                f"- **{kw}** — {mentions} mentions across {sources_count} sources. "
                f"Examples: {examples}"
            )
        lines.append("")

    items = merged.get("items", [])
    if items:
        lines.append(f"## Top {min(len(items), 15)} items (by engagement score)")
        for i, item in enumerate(items[:15], start=1):
            source = item.get("source", "")
            title = item.get("title", "")
            score = item.get("score", 0)
            url = item.get("url", "")
            created_at = str(item.get("created_at") or "")[:10]
            metrics = item.get("metrics", {})
            text = str(item.get("text") or "").strip()
            quotes = item.get("quotes", [])

            lines.append(f"### {i}. [{source}] {title}")
            lines.append(f"Score: {score:.2f} | Date: {created_at} | URL: {url}")

            metric_parts = [f"{k}: {v}" for k, v in metrics.items() if v and v != 0]
            if metric_parts:
                lines.append("Metrics: " + " | ".join(metric_parts))

            if text and text != title:
                truncated = text[:500] + ("..." if len(text) > 500 else "")
                lines.append(f"Content: {truncated}")

            if quotes:
                q = quotes[0]
                lines.append(
                    f'Quote: "{q.get("text", "")[:300]}" — {q.get("author", "")}'
                )

            lines.append("")

    return "\n".join(lines)


def _build_prompt(format_name: str, payload: dict[str, Any]) -> str:
    skill_prompt = _load_skill(format_name)
    research_context = _build_research_context(payload)
    return (
        f"{skill_prompt}\n\n"
        "---\n\n"
        "Here is the research data. Use it to produce the requested content format.\n\n"
        + research_context
    )


# ── CLI generation (stdout streaming) ────────────────────────────────────────

async def _run_generation(prompt: str) -> str:
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        from claude_agent_sdk import AssistantMessage, TextBlock  # type: ignore[attr-defined]
    except ImportError as exc:
        raise GeneratorError(
            "claude-agent-sdk is required: pip install claude-agent-sdk"
        ) from exc

    options = ClaudeAgentOptions(allowed_tools=[], model="claude-opus-4-6")
    full_text = ""
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text, end="", flush=True)
                        full_text += block.text
    print()
    return full_text


def generate(
    *,
    payload: dict[str, Any],
    format_name: str,
    save_path: Path | None = None,
) -> str:
    """Generate content, stream to stdout, return full text."""
    full_prompt = _build_prompt(format_name, payload)
    try:
        full_text = anyio.run(_run_generation, full_prompt)
    except GeneratorError:
        raise
    except Exception as exc:
        raise GeneratorError(f"Generation failed: {exc}") from exc

    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(full_text, encoding="utf-8")

    return full_text


# ── Dashboard streaming (synchronous generator for st.write_stream) ───────────

def stream_generate(
    *,
    payload: dict[str, Any],
    format_name: str,
) -> Generator[str, None, None]:
    """
    Synchronous generator that yields text chunks from Claude.
    Designed for use with Streamlit's st.write_stream().
    Runs the async Agent SDK in a background thread and feeds chunks via a queue.
    """
    full_prompt = _build_prompt(format_name, payload)

    chunk_q: queue.Queue[str | None] = queue.Queue()
    error_holder: list[Exception] = []

    async def _run() -> None:
        try:
            from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
            from claude_agent_sdk import AssistantMessage, TextBlock  # type: ignore[attr-defined]
        except ImportError as exc:
            error_holder.append(
                GeneratorError("claude-agent-sdk is required: pip install claude-agent-sdk")
            )
            return

        try:
            options = ClaudeAgentOptions(allowed_tools=[], model="claude-opus-4-6")
            async with ClaudeSDKClient(options=options) as client:
                await client.query(full_prompt)
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                chunk_q.put(block.text)
        except Exception as exc:
            error_holder.append(exc)
        finally:
            chunk_q.put(None)

    t = threading.Thread(target=lambda: anyio.run(_run), daemon=True)
    t.start()

    while True:
        chunk = chunk_q.get()
        if chunk is None:
            break
        yield chunk

    t.join()

    if error_holder:
        raise GeneratorError(str(error_holder[0])) from error_holder[0]
