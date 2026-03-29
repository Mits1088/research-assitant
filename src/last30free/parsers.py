from __future__ import annotations

import argparse

from .generator import list_formats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free",
        description="Free-source last-30-days research engine scaffold.",
    )
    parser.add_argument("query", nargs="+", help="Research query, for example: best project management tools")
    parser.add_argument("--days", type=int, default=None, help="Lookback window in days")
    parser.add_argument("--tool", default=None, help="Override the target tool")
    parser.add_argument(
        "--source",
        action="append",
        choices=["reddit", "hn", "youtube", "x", "instagram", "tiktok", "facebook"],
        help="Limit runtime to one or more sources; can be passed multiple times",
    )
    parser.add_argument("--literal", action="store_true", help="Pass the query verbatim to all sources — skip intent parsing and topic cleaning")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    parser.add_argument("--save", action="store_true", help="Write report and run artifacts to the output directory")
    parser.add_argument("--results", type=int, default=0, help="Number of merged results to display (default: 0 = all)")
    parser.add_argument("--per-source-limit", type=int, default=None, dest="per_source_limit", help="Override fetch limit per source (overrides .env search limit settings)")
    parser.add_argument(
        "--filter",
        action="append",
        dest="filters",
        metavar="KEYWORD",
        help="Keep only results containing this keyword (case-insensitive); can be passed multiple times (AND logic)",
    )
    parser.add_argument("--version", action="version", version="last30free 0.1.0")

    depth_group = parser.add_mutually_exclusive_group()
    depth_group.add_argument("--quick", action="store_true", help="Use a lighter/faster runtime profile")
    depth_group.add_argument("--deep", action="store_true", help="Use a deeper/more comprehensive runtime profile")

    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Fetch full article text via Jina Reader (r.jina.ai) for top HN/Reddit/X items",
    )
    parser.add_argument(
        "--enrich-limit",
        type=int,
        default=10,
        dest="enrich_limit",
        help="Max number of items to enrich (default: 10)",
    )

    return parser


def build_runs_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free runs",
        description="List saved last30free runs from the local output index.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of runs to show")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_show_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free show",
        description="Show a saved report by run id, topic match, or manifest path.",
    )
    parser.add_argument("run_ref", help="Run id, partial topic, run directory, or manifest path")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_compare_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free compare",
        description="Compare two saved runs and generate a change summary.",
    )
    parser.add_argument("earlier_ref", help="Earlier run id, partial topic, run directory, or manifest path")
    parser.add_argument("later_ref", help="Later run id, partial topic, run directory, or manifest path")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_latest_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free latest",
        description="Show the latest saved run per topic, or the latest run for a specific topic.",
    )
    parser.add_argument("topic_ref", nargs="?", help="Optional topic or run reference")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of topics to show")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_alerts_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free alerts",
        description="Evaluate alert rules on the latest saved run changes.",
    )
    parser.add_argument("topic_ref", nargs="?", help="Optional topic or run reference")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of topics to inspect when no topic is given")
    parser.add_argument("--new-item-threshold", type=int, default=1)
    parser.add_argument("--source-spike-threshold", type=int, default=2)
    parser.add_argument("--keyword-spike-threshold", type=int, default=2)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_notify_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free notify",
        description="Generate notification payloads from alert reports without sending them.",
    )
    parser.add_argument("topic_ref", nargs="?", help="Optional topic or run reference")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of topics to inspect when no topic is given")
    parser.add_argument("--new-item-threshold", type=int, default=1)
    parser.add_argument("--source-spike-threshold", type=int, default=2)
    parser.add_argument("--keyword-spike-threshold", type=int, default=2)
    parser.add_argument("--channel", action="append", choices=["email", "webhook"], help="Notification channel to include; can be passed multiple times")
    parser.add_argument("--save", action="store_true", help="Save notification bundles to output history")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_notify_history_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free notify-history",
        description="Show saved notification snapshot history.",
    )
    parser.add_argument("topic_ref", nargs="?", help="Optional topic or snapshot reference")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of snapshots to show")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")
    return parser


def build_watchlist_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free watchlist",
        description="Manage a file-based watchlist and run saved topics manually.",
    )
    subparsers = parser.add_subparsers(dest="watchlist_command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a starter watchlist.json file")
    init_parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing watchlist file")
    init_parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")

    show_parser = subparsers.add_parser("show", help="Show watchlist topics")
    show_parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")

    payloads_parser = subparsers.add_parser("payloads", help="Build scheduler-ready payloads for enabled topics")
    payloads_parser.add_argument("topic_refs", nargs="*", help="Optional topic ids or partial matches")
    payloads_parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")

    run_parser = subparsers.add_parser("run", help="Run enabled watchlist topics and save outputs")
    run_parser.add_argument("topic_refs", nargs="*", help="Optional topic ids or partial matches to run")
    run_parser.add_argument("--dry-run", action="store_true", help="Show which topics would run without executing")
    run_parser.add_argument("--json", action="store_true", help="Emit JSON instead of rich terminal output")

    return parser


def build_enrich_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free enrich",
        description=(
            "Enrich items from a saved run with Jina article text, "
            "caption URL articles, and optional video transcripts."
        ),
    )
    parser.add_argument("run_ref", help="Run ID, partial topic, or path to run directory")
    parser.add_argument(
        "--all",
        action="store_true",
        dest="enrich_all",
        help="Enrich all items without showing the selection prompt",
    )
    parser.add_argument(
        "--items",
        default=None,
        help="Item numbers to enrich, e.g. 1,3,5 or 1-5 or 1,3-5,8",
    )
    parser.add_argument(
        "--transcript",
        action="store_true",
        help="Download and transcribe video content (TikTok, Instagram, YouTube, X)",
    )
    parser.add_argument(
        "--whisper-model",
        default="small",
        dest="whisper_model",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size for transcription (default: small)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON result instead of rich terminal output")
    return parser


def build_generate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="last30free generate",
        description="Generate social/video content from saved research using Claude.",
    )
    parser.add_argument(
        "--format",
        required=True,
        choices=list_formats(),
        help="Content format to generate",
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--run-id", dest="run_id", help="Run ID of a saved research run")
    source_group.add_argument("--latest", dest="latest_topic", metavar="TOPIC", nargs="?", const="", help="Use the latest saved run (optionally for a specific topic)")

    parser.add_argument("--save", action="store_true", help="Save generated content to the run directory")
    return parser
