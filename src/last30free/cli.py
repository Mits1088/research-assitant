from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Sequence

from rich.console import Console

from .alerts import build_alert_report_from_manifests
from .comparison import compare_payloads, load_payload_from_manifest, render_comparison_markdown
from .config import Settings, load_settings
from .intent import normalize_spaces
from .orchestrator import build_payload, run_watchlist_entries, save_payload_artifacts
from .parsers import (
    build_alerts_parser,
    build_compare_parser,
    build_generate_parser,
    build_latest_parser,
    build_notify_history_parser,
    build_notify_parser,
    build_parser,
    build_runs_parser,
    build_show_parser,
    build_watchlist_parser,
)
from .notification_store import (
    list_notification_snapshots,
    notification_index_path,
    write_notification_bundle,
)
from .notifications import build_notification_bundle
from .rendering import (
    render_alert_report,
    render_alert_reports_overview,
    render_comparison,
    render_latest_runs,
    render_notification_bundle,
    render_notification_overview,
    render_notification_snapshots,
    render_pretty,
    render_runs_list,
    render_saved_notification_artifacts,
    render_saved_run,
    render_watchlist_payloads,
    render_watchlist_run_results,
    render_watchlist_topics,
)
from .run_index import (
    index_path,
    latest_run_for_topic,
    latest_runs_by_topic,
    list_saved_runs,
    read_manifest,
    resolve_saved_run,
    runs_for_topic,
)
from .generator import GeneratorError, generate
from .watchlist import (
    build_watchlist_runner_payloads,
    init_watchlist,
    load_watchlist,
    resolve_watch_topics,
    watchlist_path,
)




def handle_runs_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_runs_parser()
    args = parser.parse_args(list(argv))
    entries = list_saved_runs(settings.app.output_dir, limit=args.limit)

    if args.json:
        print(
            json.dumps(
                {
                    "output_dir": str(settings.app.output_dir),
                    "index_path": str(index_path(settings.app.output_dir)),
                    "count": len(entries),
                    "entries": entries,
                },
                indent=2,
            )
        )
        return 0

    render_runs_list(entries, output_dir=settings.app.output_dir)
    return 0


def handle_show_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_show_parser()
    args = parser.parse_args(list(argv))

    manifest = resolve_saved_run(settings.app.output_dir, args.run_ref)
    if manifest is None:
        if args.json:
            print(
                json.dumps(
                    {
                        "error": f"No saved run found for reference: {args.run_ref}",
                        "output_dir": str(settings.app.output_dir),
                        "index_path": str(index_path(settings.app.output_dir)),
                    },
                    indent=2,
                )
            )
        else:
            console = Console()
            console.print(f"[bold red]No saved run found for reference:[/bold red] {args.run_ref}")
            console.print(f"Index path: {index_path(settings.app.output_dir)}")
        return 1

    report_path = Path(str(manifest.get("files", {}).get("report_path", "") or ""))
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""

    if args.json:
        print(
            json.dumps(
                {
                    "manifest": manifest,
                    "report_markdown": report_text,
                },
                indent=2,
            )
        )
        return 0

    render_saved_run(manifest)
    return 0


def handle_compare_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_compare_parser()
    args = parser.parse_args(list(argv))

    earlier_manifest = resolve_saved_run(settings.app.output_dir, args.earlier_ref)
    later_manifest = resolve_saved_run(settings.app.output_dir, args.later_ref)

    if earlier_manifest is None or later_manifest is None:
        missing = []
        if earlier_manifest is None:
            missing.append(f"earlier={args.earlier_ref}")
        if later_manifest is None:
            missing.append(f"later={args.later_ref}")
        message = f"Could not resolve saved run(s): {', '.join(missing)}"

        if args.json:
            print(
                json.dumps(
                    {
                        "error": message,
                        "output_dir": str(settings.app.output_dir),
                        "index_path": str(index_path(settings.app.output_dir)),
                    },
                    indent=2,
                )
            )
        else:
            console = Console()
            console.print(f"[bold red]{message}[/bold red]")
            console.print(f"Index path: {index_path(settings.app.output_dir)}")
        return 1

    earlier_payload = load_payload_from_manifest(earlier_manifest)
    later_payload = load_payload_from_manifest(later_manifest)

    if earlier_payload is None or later_payload is None:
        message = "One or both saved runs are missing readable payload files."

        if args.json:
            print(json.dumps({"error": message}, indent=2))
        else:
            console = Console()
            console.print(f"[bold red]{message}[/bold red]")
        return 1

    comparison = compare_payloads(
        earlier_payload,
        later_payload,
        earlier_manifest=earlier_manifest,
        later_manifest=later_manifest,
    )

    comparison["comparison_markdown"] = render_comparison_markdown(comparison)

    if args.json:
        print(json.dumps(comparison, indent=2))
        return 0

    render_comparison(comparison)
    return 0


def handle_latest_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_latest_parser()
    args = parser.parse_args(list(argv))

    if args.topic_ref:
        entry = latest_run_for_topic(settings.app.output_dir, args.topic_ref)
        if entry is None:
            payload = {
                "error": f"No latest run found for topic reference: {args.topic_ref}",
                "output_dir": str(settings.app.output_dir),
                "index_path": str(index_path(settings.app.output_dir)),
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{payload['error']}[/bold red]")
                console.print(f"Index path: {payload['index_path']}")
            return 1

        if args.json:
            print(
                json.dumps(
                    {
                        "output_dir": str(settings.app.output_dir),
                        "index_path": str(index_path(settings.app.output_dir)),
                        "entry": entry,
                    },
                    indent=2,
                )
            )
            return 0

        render_latest_runs([entry], output_dir=settings.app.output_dir)
        return 0

    entries = latest_runs_by_topic(settings.app.output_dir, limit=args.limit)

    if args.json:
        print(
            json.dumps(
                {
                    "output_dir": str(settings.app.output_dir),
                    "index_path": str(index_path(settings.app.output_dir)),
                    "count": len(entries),
                    "entries": entries,
                },
                indent=2,
            )
        )
        return 0

    render_latest_runs(entries, output_dir=settings.app.output_dir)
    return 0


def handle_alerts_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_alerts_parser()
    args = parser.parse_args(list(argv))

    thresholds = {
        "new_item_threshold": args.new_item_threshold,
        "source_spike_threshold": args.source_spike_threshold,
        "keyword_spike_threshold": args.keyword_spike_threshold,
    }

    if args.topic_ref:
        topic_runs = runs_for_topic(settings.app.output_dir, args.topic_ref, limit=2)
        if len(topic_runs) < 2:
            payload = {
                "error": f"Need at least two saved runs for topic reference: {args.topic_ref}",
                "output_dir": str(settings.app.output_dir),
                "index_path": str(index_path(settings.app.output_dir)),
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{payload['error']}[/bold red]")
                console.print(f"Index path: {payload['index_path']}")
            return 1

        later_manifest = read_manifest(Path(str(topic_runs[0]["manifest_path"])))
        earlier_manifest = read_manifest(Path(str(topic_runs[1]["manifest_path"])))
        if later_manifest is None or earlier_manifest is None:
            message = "One or both alert manifests could not be read."
            if args.json:
                print(json.dumps({"error": message}, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{message}[/bold red]")
            return 1

        report = build_alert_report_from_manifests(
            earlier_manifest,
            later_manifest,
            **thresholds,
        )

        if args.json:
            print(json.dumps(report, indent=2))
            return 0

        render_alert_report(report)
        return 0

    latest_entries = latest_runs_by_topic(settings.app.output_dir, limit=args.limit)
    reports = []

    for entry in latest_entries:
        topic_runs = runs_for_topic(settings.app.output_dir, str(entry.get("topic", "")), limit=2)
        if len(topic_runs) < 2:
            continue

        later_manifest = read_manifest(Path(str(topic_runs[0]["manifest_path"])))
        earlier_manifest = read_manifest(Path(str(topic_runs[1]["manifest_path"])))
        if later_manifest is None or earlier_manifest is None:
            continue

        report = build_alert_report_from_manifests(
            earlier_manifest,
            later_manifest,
            **thresholds,
        )
        reports.append(report)

    if args.json:
        print(
            json.dumps(
                {
                    "output_dir": str(settings.app.output_dir),
                    "index_path": str(index_path(settings.app.output_dir)),
                    "count": len(reports),
                    "reports": reports,
                },
                indent=2,
            )
        )
        return 0

    render_alert_reports_overview(reports, output_dir=settings.app.output_dir)
    return 0


def handle_notify_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_notify_parser()
    args = parser.parse_args(list(argv))

    thresholds = {
        "new_item_threshold": args.new_item_threshold,
        "source_spike_threshold": args.source_spike_threshold,
        "keyword_spike_threshold": args.keyword_spike_threshold,
    }
    channels = list(args.channel) if args.channel else None

    if args.topic_ref:
        topic_runs = runs_for_topic(settings.app.output_dir, args.topic_ref, limit=2)
        if len(topic_runs) < 2:
            payload = {
                "error": f"Need at least two saved runs for topic reference: {args.topic_ref}",
                "output_dir": str(settings.app.output_dir),
                "index_path": str(index_path(settings.app.output_dir)),
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{payload['error']}[/bold red]")
                console.print(f"Index path: {payload['index_path']}")
            return 1

        later_manifest = read_manifest(Path(str(topic_runs[0]["manifest_path"])))
        earlier_manifest = read_manifest(Path(str(topic_runs[1]["manifest_path"])))
        if later_manifest is None or earlier_manifest is None:
            message = "One or both notification manifests could not be read."
            if args.json:
                print(json.dumps({"error": message}, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{message}[/bold red]")
            return 1

        alert_report = build_alert_report_from_manifests(
            earlier_manifest,
            later_manifest,
            **thresholds,
        )
        bundle = build_notification_bundle(alert_report, channels=channels)

        saved = []
        if args.save:
            saved.append(write_notification_bundle(settings.app.output_dir, bundle))

        if args.json:
            payload = {"bundle": bundle}
            if saved:
                payload["saved"] = saved
            print(json.dumps(payload, indent=2))
            return 0

        render_notification_bundle(bundle)
        if saved:
            render_saved_notification_artifacts(saved, output_dir=settings.app.output_dir)
        return 0

    latest_entries = latest_runs_by_topic(settings.app.output_dir, limit=args.limit)
    bundles = []

    for entry in latest_entries:
        topic_runs = runs_for_topic(settings.app.output_dir, str(entry.get("topic", "")), limit=2)
        if len(topic_runs) < 2:
            continue

        later_manifest = read_manifest(Path(str(topic_runs[0]["manifest_path"])))
        earlier_manifest = read_manifest(Path(str(topic_runs[1]["manifest_path"])))
        if later_manifest is None or earlier_manifest is None:
            continue

        alert_report = build_alert_report_from_manifests(
            earlier_manifest,
            later_manifest,
            **thresholds,
        )
        bundles.append(build_notification_bundle(alert_report, channels=channels))

    saved = []
    if args.save:
        for bundle in bundles:
            saved.append(write_notification_bundle(settings.app.output_dir, bundle))

    if args.json:
        payload = {
            "output_dir": str(settings.app.output_dir),
            "index_path": str(index_path(settings.app.output_dir)),
            "notification_index_path": str(notification_index_path(settings.app.output_dir)),
            "count": len(bundles),
            "bundles": bundles,
        }
        if saved:
            payload["saved"] = saved
        print(json.dumps(payload, indent=2))
        return 0

    render_notification_overview(bundles, output_dir=settings.app.output_dir)
    if saved:
        render_saved_notification_artifacts(saved, output_dir=settings.app.output_dir)
    return 0


def handle_notify_history_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_notify_history_parser()
    args = parser.parse_args(list(argv))

    entries = list_notification_snapshots(
        settings.app.output_dir,
        topic_ref=args.topic_ref,
        limit=args.limit,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "output_dir": str(settings.app.output_dir),
                    "notification_index_path": str(notification_index_path(settings.app.output_dir)),
                    "count": len(entries),
                    "entries": entries,
                },
                indent=2,
            )
        )
        return 0

    render_notification_snapshots(entries, output_dir=settings.app.output_dir)
    return 0


def handle_watchlist_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_watchlist_parser()
    args = parser.parse_args(list(argv))
    path = watchlist_path(settings.app.output_dir)

    if args.watchlist_command == "init":
        created_path, created = init_watchlist(settings.app.output_dir, overwrite=args.overwrite)
        payload = {
            "watchlist_path": str(created_path),
            "created": created,
            "overwrite": bool(args.overwrite),
        }

        if args.json:
            print(json.dumps(payload, indent=2))
            return 0

        console = Console()
        title = "Watchlist created" if created else "Watchlist already exists"
        console.print(
            Panel.fit(
                f"Path: {created_path}\nOverwrite requested: {bool(args.overwrite)}",
                title=title,
            )
        )
        return 0

    if args.watchlist_command == "show":
        watchlist = load_watchlist(settings.app.output_dir)
        payload = {
            "watchlist_path": str(path),
            "topics": watchlist.get("topics", []),
        }

        if args.json:
            print(json.dumps(payload, indent=2))
            return 0

        render_watchlist_topics(payload)
        return 0

    if args.watchlist_command == "payloads":
        payloads = build_watchlist_runner_payloads(
            settings.app.output_dir,
            refs=list(args.topic_refs),
            enabled_only=True,
        )
        payload = {
            "watchlist_path": str(path),
            "count": len(payloads),
            "payloads": payloads,
        }

        if args.json:
            print(json.dumps(payload, indent=2))
            return 0

        render_watchlist_payloads(payload)
        return 0

    if args.watchlist_command == "run":
        selected_topics = resolve_watch_topics(
            settings.app.output_dir,
            refs=list(args.topic_refs),
            enabled_only=True,
        )

        if not selected_topics:
            message = "No enabled watchlist topics matched."
            payload = {
                "error": message,
                "watchlist_path": str(path),
            }
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                console = Console()
                console.print(f"[bold red]{message}[/bold red]")
                console.print(f"Watchlist path: {path}")
            return 1

        if args.dry_run:
            payload = {
                "watchlist_path": str(path),
                "topics": selected_topics,
                "dry_run": True,
            }
            if args.json:
                print(json.dumps(payload, indent=2))
                return 0

            render_watchlist_topics(payload)
            return 0

        batch_results = run_watchlist_entries(
            settings,
            selected_topics,
            output_dir=settings.app.output_dir,
        )
        payload = {
            "watchlist_path": str(path),
            "index_path": str(index_path(settings.app.output_dir)),
            "count": len(batch_results),
            "results": batch_results,
        }

        if args.json:
            print(json.dumps(payload, indent=2))
            return 0

        render_watchlist_run_results(payload)
        return 0

    return 1



def handle_generate_command(argv: Sequence[str], settings: Settings) -> int:
    parser = build_generate_parser()
    args = parser.parse_args(list(argv))
    console = Console()

    # Resolve manifest
    manifest: dict[str, Any] | None = None
    if args.run_id:
        manifest = resolve_saved_run(settings.app.output_dir, args.run_id)
        if manifest is None:
            console.print(f"[bold red]No saved run found for run-id:[/bold red] {args.run_id}")
            return 1
    else:
        topic_ref = args.latest_topic or ""
        if topic_ref:
            entry = latest_run_for_topic(settings.app.output_dir, topic_ref)
        else:
            entries = latest_runs_by_topic(settings.app.output_dir, limit=1)
            entry = entries[0] if entries else None
        if entry is None:
            msg = f"No saved run found for topic: {topic_ref}" if topic_ref else "No saved runs found. Run a query with --save first."
            console.print(f"[bold red]{msg}[/bold red]")
            return 1
        manifest = resolve_saved_run(settings.app.output_dir, str(entry.get("run_id", "")))
        if manifest is None:
            console.print("[bold red]Could not load manifest for the latest run.[/bold red]")
            return 1

    # Load payload
    files = manifest.get("files", {})
    payload_path = Path(str(files.get("payload_path", "") or ""))
    if not payload_path.exists():
        console.print(f"[bold red]Payload file not found:[/bold red] {payload_path}")
        return 1

    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        console.print(f"[bold red]Failed to read payload:[/bold red] {exc}")
        return 1

    topic = str(manifest.get("topic", "") or "")
    run_id = str(manifest.get("run_id", "") or "")

    console.print()
    console.print(
        Panel.fit(
            f"Topic: {topic}\nRun ID: {run_id}\nFormat: {args.format}\nModel: claude-opus-4-6",
            title="Generating content",
        )
    )
    console.print()

    save_path: Path | None = None
    if args.save:
        run_dir = Path(str(files.get("run_dir", "") or ""))
        if run_dir:
            save_path = run_dir / f"generated_{args.format.replace('-', '_')}.md"

    try:
        generate(
            payload=payload,
            format_name=args.format,
            save_path=save_path,
        )
    except GeneratorError as exc:
        console.print(f"\n[bold red]Generation failed:[/bold red] {exc}")
        return 1

    if save_path:
        console.print()
        console.print(f"[green]Saved to:[/green] {save_path}")

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]

    settings = load_settings()
    settings.ensure_directories()

    if argv_list and argv_list[0] == "runs":
        return handle_runs_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "show":
        return handle_show_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "compare":
        return handle_compare_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "latest":
        return handle_latest_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "alerts":
        return handle_alerts_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "notify":
        return handle_notify_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "notify-history":
        return handle_notify_history_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "watchlist":
        return handle_watchlist_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "generate":
        return handle_generate_command(argv_list[1:], settings)

    if argv_list and argv_list[0] == "dashboard":
        import subprocess
        dashboard_path = Path(__file__).parent / "dashboard.py"
        extra = argv_list[1:]  # pass through e.g. --server.port 8502
        cmd = [sys.executable, "-m", "streamlit", "run", str(dashboard_path)] + list(extra)
        raise SystemExit(subprocess.call(cmd))

    parser = build_parser()
    args = parser.parse_args(argv_list)

    raw_query = normalize_spaces(" ".join(args.query))
    payload = build_payload(args, settings)

    if args.save:
        payload = save_payload_artifacts(
            settings=settings,
            payload=payload,
            raw_query=raw_query,
            argv_list=argv_list,
        )

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    render_pretty(payload, results_limit=args.results)

    if args.save:
        artifacts = payload["artifacts"]
        console = Console()
        console.print()
        console.print(
            Panel.fit(
                f"Run directory: {artifacts['run_dir']}\n"
                f"Report: {artifacts['report_path']}\n"
                f"Manifest: {artifacts['manifest_path']}\n"
                f"Merged items: {artifacts['merged_items_path']}\n"
                f"Payload: {artifacts['payload_path']}\n"
                f"Index: {payload.get('index_path', '')}\n"
                f"Run ID: {payload.get('index_entry', {}).get('run_id', '')}",
                title="Saved artifacts",
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
