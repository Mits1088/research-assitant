# last30free

A lightweight "last 30 days" research engine built only with free-access sources:

- Reddit public JSON
- Hacker News Algolia
- YouTube via `yt-dlp`
- X/Twitter via `twscrape` with auth cookies

## Goal

Research a topic across the last 30 days and synthesize:

- what people are discussing
- which tools/products are being recommended
- what creators are saying in videos
- what developers/startups are discussing on HN
- what is trending on X

## Scope

This is a free-source fork inspired by broader multi-source recency research skills.

It is intentionally narrower than premium/paywalled versions:
- no TikTok
- no Instagram
- no Bluesky
- no Truth Social
- no Polymarket
- no paid web-search enrichment

## Architecture

```text
src/last30free/
├── adapters/
│   ├── base.py
│   ├── reddit.py
│   ├── hn.py
│   ├── youtube.py
│   └── x.py
├── alerts.py
├── cli.py
├── comparison.py
├── config.py
├── models.py
├── notifications.py
├── notification_store.py
├── reporting.py
├── run_index.py
├── synthesis.py
├── watchlist.py
└── scoring.py
```

## Installation

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Usage

### Run a research query

```bash
last30free "best AI coding tools"
last30free "latest AI coding tools" --save
last30free "cursor vs copilot" --days 14 --deep
last30free "best project management tools" --source hn --source youtube
```

### Saved run management

```bash
last30free runs                          # list all saved runs
last30free latest                        # latest run per topic
last30free latest "ai coding tools"      # latest run for a specific topic
last30free show <run_id>                 # show a saved report
last30free compare <earlier> <later>     # compare two runs
```

### Alerts

```bash
last30free alerts                        # evaluate alert rules across all topics
last30free alerts "ai coding tools"      # alerts for a specific topic
last30free alerts "ai coding tools" --new-item-threshold 2
```

### Notification payloads

```bash
last30free notify "ai coding tools"               # generate payloads (email + webhook)
last30free notify "ai coding tools" --save        # generate and save to snapshot history
last30free notify "ai coding tools" --channel email
last30free notify "ai coding tools" --channel webhook --json
last30free notify                                  # overview across all topics
```

### Notification history

```bash
last30free notify-history                          # all saved notification snapshots
last30free notify-history "ai coding tools"        # snapshots for a specific topic
last30free notify-history --json
```

### Watchlist

```bash
last30free watchlist init                 # create a starter watchlist.json
last30free watchlist show                 # list watchlist topics
last30free watchlist payloads             # scheduler-ready CLI payloads
last30free watchlist run                  # run all enabled topics and save
last30free watchlist run --dry-run        # preview without executing
```

## Output layout

```text
outputs/
├── run_index.json
├── notification_index.json
├── <timestamp>_<topic-slug>/
│   ├── manifest.json
│   ├── report.md
│   ├── merged_items.json
│   └── run_payload.json
└── notifications/
    └── <topic-slug>/
        └── <timestamp>_<topic-slug>/
            ├── manifest.json
            ├── bundle.json
            ├── email_payload.json
            ├── email_body.txt
            └── webhook_payload.json
```

## Configuration

Settings are loaded from environment variables or a `.env` file:

| Variable | Default | Description |
|---|---|---|
| `LAST30FREE_OUTPUT_DIR` | `outputs` | Where run artifacts are saved |
| `LAST30FREE_CACHE_DIR` | `cache` | HTTP response cache |
| `LAST30FREE_DEFAULT_DAYS` | `30` | Lookback window |
| `LAST30FREE_MAX_ITEMS_PER_SOURCE` | `25` | Per-source fetch limit |
| `LAST30FREE_X_ENABLE` | `false` | Enable X/Twitter adapter |

## What is not included

This project generates and saves notification payloads. It does not:

- send email
- POST to webhooks
- deliver Slack messages
- schedule or auto-run queries
- provide a web UI
