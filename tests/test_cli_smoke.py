from last30free.intent import parse_user_intent
from last30free.config import load_settings
from last30free.models import QueryType


def test_parse_recommendations_query() -> None:
    intent = parse_user_intent("best project management tools")
    assert intent.query_type == QueryType.RECOMMENDATIONS
    assert intent.topic == "project management tools"
    assert intent.target_tool == "unknown"


def test_parse_prompting_query_with_tool() -> None:
    intent = parse_user_intent("UI design prompts for Midjourney")
    assert intent.query_type == QueryType.PROMPTING
    assert intent.topic.lower() == "ui design"
    assert intent.target_tool == "Midjourney"


def test_parse_comparison_query() -> None:
    intent = parse_user_intent("Claude vs Gemini")
    assert intent.query_type == QueryType.COMPARISON
    assert intent.topic_a == "Claude"
    assert intent.topic_b == "Gemini"


def test_load_settings_defaults() -> None:
    settings = load_settings()
    assert settings.app.default_days == 30
    assert settings.reddit.search_limit == 25
