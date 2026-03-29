from __future__ import annotations

import re

from .models import IntentParse, QueryType

PROMPTING_HINTS = (
    "prompt",
    "prompts",
    "prompting",
    "mockup",
    "mockups",
    "ui",
    "design",
    "image",
    "images",
    "video",
    "videos",
    "thumbnail",
    "thumbnails",
)


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def detect_query_type(raw_query: str) -> QueryType:
    lowered = raw_query.lower().strip()

    if re.search(r"\s+(vs|versus)\s+", lowered):
        return QueryType.COMPARISON

    if any(
        phrase in lowered
        for phrase in (
            "best ",
            "top ",
            "recommended ",
            "recommend ",
            "what should i use",
            "what are the best",
            "most popular ",
        )
    ):
        return QueryType.RECOMMENDATIONS

    if any(
        phrase in lowered
        for phrase in (
            "what's happening",
            "whats happening",
            "what is happening",
            "latest on",
            "latest ",
            " news",
            "update",
            "updates",
            "announcement",
            "announcements",
        )
    ):
        return QueryType.NEWS

    if any(hint in lowered for hint in PROMPTING_HINTS):
        return QueryType.PROMPTING

    return QueryType.GENERAL


def clean_topic_text(text: str, query_type: QueryType) -> str:
    value = normalize_spaces(text)

    if query_type == QueryType.RECOMMENDATIONS:
        value = re.sub(
            r"^(what (are|is) the )?(best|top|recommended)\s+",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"^most popular\s+", "", value, flags=re.IGNORECASE)
        value = re.sub(r"^recommend\s+", "", value, flags=re.IGNORECASE)

    elif query_type == QueryType.NEWS:
        value = re.sub(
            r"^(what('s| is)? happening (with|on)\s+|latest on\s+|latest\s+|news on\s+)",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"\s+news$", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+updates?$", "", value, flags=re.IGNORECASE)

    elif query_type == QueryType.PROMPTING:
        value = re.sub(r"^(prompting for|prompts? for)\s+", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+prompts?$", "", value, flags=re.IGNORECASE)

    return normalize_spaces(value.strip(" -"))


def extract_topic_and_tool(
    raw_query: str,
    query_type: QueryType,
    tool_override: str | None,
) -> tuple[str, str]:
    if tool_override:
        return clean_topic_text(raw_query, query_type), normalize_spaces(tool_override)

    if query_type == QueryType.COMPARISON:
        return normalize_spaces(raw_query), "unknown"

    if " for " in raw_query.lower():
        left, right = re.split(r"\bfor\b", raw_query, maxsplit=1, flags=re.IGNORECASE)
        left = normalize_spaces(left)
        right = normalize_spaces(right)

        if query_type == QueryType.PROMPTING or any(hint in left.lower() for hint in PROMPTING_HINTS):
            return clean_topic_text(left, query_type), right or "unknown"

    return clean_topic_text(raw_query, query_type), "unknown"


def parse_user_intent(raw_query: str, tool_override: str | None = None, literal: bool = False) -> IntentParse:
    query = normalize_spaces(raw_query)

    if literal:
        return IntentParse(
            raw_query=query,
            topic=query,
            target_tool=normalize_spaces(tool_override) if tool_override else "unknown",
            query_type=QueryType.GENERAL,
        )

    query_type = detect_query_type(query)

    if query_type == QueryType.COMPARISON:
        parts = re.split(r"\s+(?:vs|versus)\s+", query, maxsplit=1, flags=re.IGNORECASE)
        topic_a = normalize_spaces(parts[0])
        topic_b = normalize_spaces(parts[1]) if len(parts) > 1 else ""
        return IntentParse(
            raw_query=query,
            topic=f"{topic_a} vs {topic_b}".strip(),
            target_tool=normalize_spaces(tool_override) if tool_override else "unknown",
            query_type=query_type,
            topic_a=topic_a or None,
            topic_b=topic_b or None,
        )

    topic, target_tool = extract_topic_and_tool(query, query_type, tool_override)

    return IntentParse(
        raw_query=query,
        topic=topic,
        target_tool=target_tool,
        query_type=query_type,
    )
