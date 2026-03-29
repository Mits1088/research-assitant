from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from .notification_store import notification_index_path
from .run_index import index_path


def summarize_item_signal(item: dict[str, Any]) -> str:
    source = item["source"]
    metrics = item["metrics"]

    if source == "reddit":
        return f"{metrics['upvotes']} ups / {metrics['comments']} cmt"
    if source == "hn":
        return f"{metrics['points']} pts / {metrics['comments']} cmt"
    if source == "youtube":
        return f"{metrics['views']} views / {metrics['likes']} likes"
    if source == "x":
        return f"{metrics['likes']} likes / {metrics['reposts']} rts / {metrics['comments']} replies"
    if source == "instagram":
        return f"{metrics['likes']} likes / {metrics['comments']} cmt"
    if source == "tiktok":
        return f"{metrics['views']} views / {metrics['likes']} likes / {metrics['reposts']} shares"
    if source == "facebook":
        return f"{metrics['likes']} likes / {metrics['comments']} cmt / {metrics['reposts']} shares"
    return "-"


def summarize_item_community(item: dict[str, Any]) -> str:
    if item["source"] == "reddit":
        for tag in item.get("tags", []):
            if tag.startswith("r/"):
                return tag
        return "reddit"

    if item["source"] == "hn":
        tags = item.get("tags", [])
        if "show_hn" in tags:
            return "show_hn"
        if "ask_hn" in tags:
            return "ask_hn"
        return "HN"

    if item["source"] == "youtube":
        for tag in item.get("tags", []):
            if tag.startswith("channel:"):
                return tag.removeprefix("channel:")
        return "YouTube"

    if item["source"] == "x":
        username = str(item.get("raw", {}).get("username", "") or "").strip()
        if not username:
            url = item.get("url", "")
            m = re.match(r"https://x\.com/([^/]+)/status/", url)
            if m:
                username = m.group(1)
        return f"@{username}" if username else "X"

    if item["source"] == "instagram":
        username = str(item.get("raw", {}).get("username", "") or "").strip()
        return f"@{username}" if username else "Instagram"

    if item["source"] == "tiktok":
        username = str(item.get("raw", {}).get("username", "") or "").strip()
        return f"@{username}" if username else "TikTok"

    if item["source"] == "facebook":
        author = str(item.get("raw", {}).get("author", "") or "").strip()
        return author if author else "Facebook"

    return item["source"]


def render_pretty(payload: dict[str, Any], *, results_limit: int = 0) -> None:
    console = Console()

    console.print(
        Panel.fit(
            "[bold green]last30free[/bold green]\n"
            "Live fetch and first-pass synthesis are working.\n"
            "Saved report artifacts are available with --save.",
            title="Runtime status",
        )
    )

    intent = payload["intent"]
    runtime = payload["runtime"]

    summary_table = Table(show_header=False, box=None, pad_edge=False)
    summary_table.add_row("TOPIC", str(intent["topic"]))
    summary_table.add_row("TARGET_TOOL", str(intent["target_tool"]))
    summary_table.add_row("QUERY_TYPE", str(intent["query_type"]))
    summary_table.add_row("DAYS", str(runtime["days"]))
    summary_table.add_row("DEPTH", str(runtime["depth"]))
    summary_table.add_row("LIMIT PER SOURCE", str(runtime["limit_per_source"]))
    summary_table.add_row("SELECTED SOURCES", ", ".join(runtime["selected_sources"]) or "(none)")
    summary_table.add_row(
        "IMPLEMENTED NOW",
        ", ".join(runtime["implemented_selected_sources"]) or "(none)",
    )
    if runtime["skipped_sources"]:
        summary_table.add_row("SKIPPED SOURCES", ", ".join(runtime["skipped_sources"]))
    summary_table.add_row("X ENABLED", str(runtime["x_enabled"]))
    summary_table.add_row("X CONFIGURED", str(runtime["x_configured"]))
    summary_table.add_row("INSTAGRAM AUTHENTICATED", str(runtime.get("instagram_authenticated", False)))
    console.print(summary_table)
    console.print()

    source_table = Table(title="Source execution")
    source_table.add_column("Source")
    source_table.add_column("Status")
    source_table.add_column("Count", justify="right")
    source_table.add_column("Error")

    for source_name in ("reddit", "hn", "youtube", "x", "instagram", "tiktok", "facebook"):
        result = payload["results"].get(source_name)
        if result is None:
            continue
        source_table.add_row(
            source_name,
            result["status"],
            str(result["count"]),
            result["error"] or "",
        )

    console.print(source_table)
    console.print()

    synthesis = payload["synthesis"]
    console.print(Panel.fit(synthesis["headline"], title="What I learned"))

    summary_points = synthesis.get("summary_points", [])
    if summary_points:
        console.print()
        console.print("[bold]Key takeaways[/bold]")
        for point in summary_points:
            console.print(f"• {point}")

    patterns = synthesis.get("patterns", [])
    if patterns:
        console.print()
        pattern_table = Table(title="Recurring patterns")
        pattern_table.add_column("Keyword")
        pattern_table.add_column("Mentions", justify="right")
        pattern_table.add_column("Sources", justify="right")
        pattern_table.add_column("Examples")

        for pattern in patterns:
            pattern_table.add_row(
                pattern["keyword"],
                str(pattern["mentions"]),
                str(pattern["source_count"]),
                " | ".join(pattern["examples"][:2]),
            )

        console.print(pattern_table)

    source_stats = synthesis.get("source_stats", [])
    if source_stats:
        console.print()
        stats_table = Table(title="Source stats")
        stats_table.add_column("Source")
        stats_table.add_column("Items", justify="right")
        stats_table.add_column("Metric 1")
        stats_table.add_column("Metric 2")
        stats_table.add_column("Metric 3")

        for row in source_stats:
            metric_1 = f"{row['label_1']}: {row['total_1']}"
            metric_2 = f"{row['label_2']}: {row['total_2']}"
            metric_3 = ""
            if "label_3" in row:
                metric_3 = f"{row['label_3']}: {row['total_3']}"

            stats_table.add_row(
                row["source"],
                str(row["count"]),
                metric_1,
                metric_2,
                metric_3,
            )

        console.print(stats_table)

    console.print()

    merged = payload["merged"]
    items = merged["items"]

    if not items:
        console.print("[yellow]No merged results found in the requested time window.[/yellow]")
        return

    merged_table = Table(title="Merged top discussions")
    merged_table.add_column("#", justify="right")
    merged_table.add_column("Source")
    merged_table.add_column("Community")
    merged_table.add_column("Signal")
    merged_table.add_column("Score", justify="right")
    merged_table.add_column("Title")

    for idx, item in enumerate(items if results_limit == 0 else items[:results_limit], start=1):
        created_at = item.get("created_at", "")
        date_str = created_at[:10] if created_at else ""
        url = item.get("url", "")
        meta_line = f"[dim]{date_str}  {url}[/dim]" if date_str or url else ""
        title_cell = item["title"] + (f"\n{meta_line}" if meta_line else "")
        merged_table.add_row(
            str(idx),
            item["source"],
            summarize_item_community(item),
            summarize_item_signal(item),
            f"{item['score']:.2f}",
            title_cell,
        )

    console.print(merged_table)

    urls_with_index = [
        (i, item.get("url", ""))
        for i, item in enumerate(items if results_limit == 0 else items[:results_limit], start=1)
        if item.get("url")
    ]
    if urls_with_index:
        console.print()
        console.print("[bold]Full URLs[/bold]")
        for idx, url in urls_with_index:
            console.print(f"  {idx:>3}. {url}")

    top_with_quote = next((item for item in items if item.get("quotes")), None)
    if top_with_quote:
        quote = top_with_quote["quotes"][0]
        console.print()
        console.print(
            Panel.fit(
                f"{quote['text']}\n\n"
                f"[bold]— {quote.get('author') or 'unknown'}[/bold] "
                f"({quote.get('source_label') or top_with_quote['source']})",
                title="Sample extracted quote",
            )
        )


def render_runs_list(entries: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not entries:
        console.print(
            Panel.fit(
                f"No saved runs found.\nIndex path: {index_path(output_dir)}",
                title="Saved runs",
            )
        )
        return

    table = Table(title="Saved runs")
    table.add_column("Run ID")
    table.add_column("Generated")
    table.add_column("Topic")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Items", justify="right")
    table.add_column("Sources")

    for entry in entries:
        sources = ", ".join(entry.get("selected_sources", []) or [])
        table.add_row(
            str(entry.get("run_id", "")),
            str(entry.get("generated_at_utc", "")),
            str(entry.get("topic", "")),
            str(entry.get("query_type", "")),
            str(entry.get("status", "")),
            str(entry.get("merged_items", 0)),
            sources,
        )

    console.print(table)
    console.print()
    console.print(f"Index path: {index_path(output_dir)}")


def render_latest_runs(entries: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not entries:
        console.print(
            Panel.fit(
                f"No latest runs found.\nIndex path: {index_path(output_dir)}",
                title="Latest runs by topic",
            )
        )
        return

    table = Table(title="Latest runs by topic")
    table.add_column("Topic")
    table.add_column("Run ID")
    table.add_column("Generated")
    table.add_column("Status")
    table.add_column("Items", justify="right")
    table.add_column("Sources")

    for entry in entries:
        table.add_row(
            str(entry.get("topic", "")),
            str(entry.get("run_id", "")),
            str(entry.get("generated_at_utc", "")),
            str(entry.get("status", "")),
            str(entry.get("merged_items", 0)),
            ", ".join(entry.get("selected_sources", []) or []),
        )

    console.print(table)
    console.print()
    console.print(f"Index path: {index_path(output_dir)}")


def render_saved_run(manifest: dict[str, Any]) -> None:
    console = Console()
    files = manifest.get("files", {})
    runtime = manifest.get("runtime", {})

    summary = Table(show_header=False, box=None, pad_edge=False)
    summary.add_row("RUN ID", str(manifest.get("run_id", "")))
    summary.add_row("GENERATED", str(manifest.get("generated_at_utc", "")))
    summary.add_row("TOPIC", str(manifest.get("topic", "")))
    summary.add_row("QUERY TYPE", str(manifest.get("query_type", "")))
    summary.add_row("STATUS", str(manifest.get("status", "")))
    summary.add_row("SOURCES", ", ".join(runtime.get("selected_sources", []) or []))
    summary.add_row("REPORT", str(files.get("report_path", "")))
    summary.add_row("MANIFEST", str(files.get("manifest_path", "")))

    console.print(Panel.fit(summary, title="Saved run"))
    console.print()

    report_path = Path(str(files.get("report_path", "") or ""))
    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")
        console.print(Markdown(report_text))
        return

    console.print("[yellow]Report file not found for this saved run.[/yellow]")


def render_comparison(comparison: dict[str, Any]) -> None:
    console = Console()
    summary = comparison.get("summary", {})
    earlier = comparison.get("earlier_run", {})
    later = comparison.get("later_run", {})

    header = Table(show_header=False, box=None, pad_edge=False)
    header.add_row("EARLIER", f"{earlier.get('run_id', '')} ({earlier.get('generated_at_utc', '')})")
    header.add_row("LATER", f"{later.get('run_id', '')} ({later.get('generated_at_utc', '')})")
    header.add_row("TOPIC", str(later.get("topic") or earlier.get("topic") or ""))

    console.print(Panel.fit(header, title="Run comparison"))
    console.print()
    console.print(Panel.fit(str(summary.get("headline", "")), title="Change summary"))

    bullet_points = summary.get("bullet_points", [])
    if bullet_points:
        console.print()
        console.print("[bold]Key changes[/bold]")
        for point in bullet_points:
            console.print(f"• {point}")

    source_counts = comparison.get("source_counts", [])
    if source_counts:
        console.print()
        source_table = Table(title="Source count changes")
        source_table.add_column("Source")
        source_table.add_column("Earlier", justify="right")
        source_table.add_column("Later", justify="right")
        source_table.add_column("Delta", justify="right")
        for row in source_counts:
            source_table.add_row(
                row["source"],
                str(row["earlier_count"]),
                str(row["later_count"]),
                f"{row['delta']:+d}",
            )
        console.print(source_table)

    keyword_changes = comparison.get("keyword_changes", [])
    if keyword_changes:
        console.print()
        kw_table = Table(title="Keyword changes")
        kw_table.add_column("Keyword")
        kw_table.add_column("Earlier", justify="right")
        kw_table.add_column("Later", justify="right")
        kw_table.add_column("Delta", justify="right")
        for row in keyword_changes[:10]:
            kw_table.add_row(
                row["keyword"],
                str(row["earlier_mentions"]),
                str(row["later_mentions"]),
                f"{row['delta']:+d}",
            )
        console.print(kw_table)

    added_items = comparison.get("added_items", [])
    if added_items:
        console.print()
        added_table = Table(title="New items in later run")
        added_table.add_column("Source")
        added_table.add_column("Title")
        for item in added_items:
            added_table.add_row(str(item.get("source", "")), str(item.get("title", "")))
        console.print(added_table)

    removed_items = comparison.get("removed_items", [])
    if removed_items:
        console.print()
        removed_table = Table(title="Items no longer present")
        removed_table.add_column("Source")
        removed_table.add_column("Title")
        for item in removed_items:
            removed_table.add_row(str(item.get("source", "")), str(item.get("title", "")))
        console.print(removed_table)

    score_changes = comparison.get("score_changes", [])
    if score_changes:
        console.print()
        score_table = Table(title="Biggest score changes")
        score_table.add_column("Source")
        score_table.add_column("Title")
        score_table.add_column("Earlier", justify="right")
        score_table.add_column("Later", justify="right")
        score_table.add_column("Delta", justify="right")
        for item in score_changes:
            score_table.add_row(
                str(item.get("source", "")),
                str(item.get("title", "")),
                f"{float(item.get('earlier_score', 0)):.2f}",
                f"{float(item.get('later_score', 0)):.2f}",
                f"{float(item.get('delta', 0)):+.2f}",
            )
        console.print(score_table)


def render_alert_report(report: dict[str, Any]) -> None:
    console = Console()
    comparison = report.get("comparison", {})
    earlier = comparison.get("earlier_run", {})
    later = comparison.get("later_run", {})
    summary = report.get("summary", {})

    header = Table(show_header=False, box=None, pad_edge=False)
    header.add_row("TOPIC", str(report.get("topic", "")))
    header.add_row("STATUS", str(report.get("status", "")))
    header.add_row("EARLIER", f"{earlier.get('run_id', '')} ({earlier.get('generated_at_utc', '')})")
    header.add_row("LATER", f"{later.get('run_id', '')} ({later.get('generated_at_utc', '')})")

    console.print(Panel.fit(header, title="Alert evaluation"))
    console.print()
    console.print(Panel.fit(str(summary.get("headline", "")), title="Alert summary"))

    rules = report.get("rules", [])
    if rules:
        console.print()
        table = Table(title="Alert rules")
        table.add_column("Rule")
        table.add_column("Triggered")
        table.add_column("Severity")
        table.add_column("Message")

        for rule in rules:
            table.add_row(
                str(rule.get("rule_id", "")),
                "yes" if rule.get("triggered") else "no",
                str(rule.get("severity", "")),
                str(rule.get("message", "")),
            )
        console.print(table)


def render_alert_reports_overview(reports: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not reports:
        console.print(
            Panel.fit(
                f"No alert comparisons available.\nIndex path: {index_path(output_dir)}",
                title="Alerts overview",
            )
        )
        return

    table = Table(title="Alerts overview")
    table.add_column("Topic")
    table.add_column("Status")
    table.add_column("Triggered", justify="right")
    table.add_column("Earlier")
    table.add_column("Later")
    table.add_column("Headline")

    for report in reports:
        comparison = report.get("comparison", {})
        summary = report.get("summary", {})
        table.add_row(
            str(report.get("topic", "")),
            str(report.get("status", "")),
            str(summary.get("triggered_rules", 0)),
            str(comparison.get("earlier_run", {}).get("run_id", "")),
            str(comparison.get("later_run", {}).get("run_id", "")),
            str(summary.get("headline", "")),
        )

    console.print(table)
    console.print()
    console.print(f"Index path: {index_path(output_dir)}")


def render_notification_bundle(bundle: dict[str, Any]) -> None:
    console = Console()
    summary = bundle.get("summary", {})

    header = Table(show_header=False, box=None, pad_edge=False)
    header.add_row("TOPIC", str(bundle.get("topic", "")))
    header.add_row("STATUS", str(bundle.get("status", "")))
    header.add_row("CHANNELS", ", ".join(bundle.get("channels", []) or []))
    header.add_row("TRIGGERED RULES", str(summary.get("triggered_rules", 0)))

    console.print(Panel.fit(header, title="Notification payloads"))
    console.print()
    console.print(Panel.fit(str(summary.get("headline", "")), title="Notification summary"))

    payloads = bundle.get("payloads", {})

    email_payload = payloads.get("email")
    if email_payload:
        console.print()
        email_table = Table(title="Email payload")
        email_table.add_column("Field")
        email_table.add_column("Value")
        email_table.add_row("subject", str(email_payload.get("subject", "")))
        email_table.add_row("body_text", str(email_payload.get("body_text", "")))
        console.print(email_table)

    webhook_payload = payloads.get("webhook")
    if webhook_payload:
        console.print()
        webhook_table = Table(title="Webhook payload")
        webhook_table.add_column("Field")
        webhook_table.add_column("Value")
        webhook_table.add_row("event_type", str(webhook_payload.get("event_type", "")))
        webhook_table.add_row("topic", str(webhook_payload.get("topic", "")))
        webhook_table.add_row("status", str(webhook_payload.get("status", "")))
        webhook_table.add_row("headline", str(webhook_payload.get("headline", "")))
        console.print(webhook_table)


def render_notification_overview(rows: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not rows:
        console.print(
            Panel.fit(
                f"No notification payloads available.\nIndex path: {index_path(output_dir)}",
                title="Notification overview",
            )
        )
        return

    table = Table(title="Notification payload overview")
    table.add_column("Topic")
    table.add_column("Status")
    table.add_column("Channels")
    table.add_column("Triggered", justify="right")
    table.add_column("Headline")

    for row in rows:
        summary = row.get("summary", {})
        table.add_row(
            str(row.get("topic", "")),
            str(row.get("status", "")),
            ", ".join(row.get("channels", []) or []),
            str(summary.get("triggered_rules", 0)),
            str(summary.get("headline", "")),
        )

    console.print(table)
    console.print()
    console.print(f"Index path: {index_path(output_dir)}")


def render_notification_snapshots(entries: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not entries:
        console.print(
            Panel.fit(
                f"No notification snapshots found.\nIndex path: {notification_index_path(output_dir)}",
                title="Notification history",
            )
        )
        return

    table = Table(title="Notification snapshot history")
    table.add_column("Topic")
    table.add_column("Snapshot ID")
    table.add_column("Generated")
    table.add_column("Status")
    table.add_column("Triggered", justify="right")
    table.add_column("Channels")

    for entry in entries:
        table.add_row(
            str(entry.get("topic", "")),
            str(entry.get("snapshot_id", "")),
            str(entry.get("generated_at_utc", "")),
            str(entry.get("status", "")),
            str(entry.get("triggered_rules", 0)),
            ", ".join(entry.get("channels", []) or []),
        )

    console.print(table)
    console.print()
    console.print(f"Index path: {notification_index_path(output_dir)}")


def render_saved_notification_artifacts(saved: list[dict[str, Any]], *, output_dir: Path) -> None:
    console = Console()

    if not saved:
        return

    table = Table(title="Saved notification snapshots")
    table.add_column("Topic")
    table.add_column("Snapshot ID")
    table.add_column("Snapshot Dir")
    table.add_column("Manifest")

    for row in saved:
        entry = row.get("index_entry", {})
        table.add_row(
            str(entry.get("topic", "")),
            str(entry.get("snapshot_id", "")),
            str(row.get("snapshot_dir", "")),
            str(row.get("manifest_path", "")),
        )

    console.print()
    console.print(table)
    console.print(f"Notification index: {notification_index_path(output_dir)}")


def render_watchlist_topics(payload: dict[str, Any]) -> None:
    console = Console()
    path = payload["watchlist_path"]
    topics = payload["topics"]

    if not topics:
        console.print(
            Panel.fit(
                f"No topics found in watchlist.\nPath: {path}",
                title="Watchlist",
            )
        )
        return

    table = Table(title="Watchlist topics")
    table.add_column("ID")
    table.add_column("Enabled")
    table.add_column("Days", justify="right")
    table.add_column("Depth")
    table.add_column("Sources")
    table.add_column("Query")

    for topic in topics:
        table.add_row(
            str(topic.get("id", "")),
            "yes" if topic.get("enabled") else "no",
            str(topic.get("days", 30)),
            str(topic.get("depth", "balanced")),
            ", ".join(topic.get("sources", []) or []),
            str(topic.get("query", "")),
        )

    console.print(table)
    console.print()
    console.print(f"Watchlist path: {path}")


def render_watchlist_payloads(payload: dict[str, Any]) -> None:
    console = Console()
    rows = payload["payloads"]

    if not rows:
        console.print(
            Panel.fit(
                f"No enabled watchlist payloads found.\nPath: {payload['watchlist_path']}",
                title="Watchlist payloads",
            )
        )
        return

    table = Table(title="Watchlist runner payloads")
    table.add_column("ID")
    table.add_column("Depth")
    table.add_column("Days", justify="right")
    table.add_column("Sources")
    table.add_column("Command")

    for row in rows:
        table.add_row(
            str(row.get("topic_id", "")),
            str(row.get("depth", "")),
            str(row.get("days", "")),
            ", ".join(row.get("sources", []) or []),
            str(row.get("command_string", "")),
        )

    console.print(table)
    console.print()
    console.print(f"Watchlist path: {payload['watchlist_path']}")


def render_watchlist_run_results(payload: dict[str, Any]) -> None:
    console = Console()
    results = payload["results"]

    if not results:
        console.print(
            Panel.fit(
                f"No watchlist topics were executed.\nPath: {payload['watchlist_path']}",
                title="Watchlist run",
            )
        )
        return

    table = Table(title="Watchlist batch run")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Items", justify="right")
    table.add_column("Run ID")
    table.add_column("Sources")
    table.add_column("Query")

    for row in results:
        table.add_row(
            str(row.get("id", "")),
            str(row.get("status", "")),
            str(row.get("merged_items", 0)),
            str(row.get("run_id", "")),
            ", ".join(row.get("selected_sources", []) or []),
            str(row.get("query", "")),
        )

    console.print(table)
    console.print()
    console.print(f"Watchlist path: {payload['watchlist_path']}")
    console.print(f"Index path: {payload['index_path']}")
