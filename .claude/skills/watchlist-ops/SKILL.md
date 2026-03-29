---
name: watchlist-ops
description: Manage the last30free watchlist — view topics, run scans, inspect diffs, and decide whether an alert warrants content creation. Use this when the user wants to manage ongoing topic monitoring.
---

# watchlist-ops

Manage the file-based watchlist and act on monitoring results.

## When to invoke

- "Run my watchlist"
- "What topics am I tracking?"
- "Add [topic] to my watchlist"
- "Did anything alert today?"
- "Check if there are any spikes in my watchlist"
- "Run a batch scan on all my topics"

## Watchlist file location

`outputs/watchlist.json` — created by `python -m last30free watchlist init`

## Common operations

### View current topics
```
python -m last30free watchlist show
```

### Run all enabled topics and save results
```
python -m last30free watchlist run
```
Add `--dry-run` to preview what would execute without running.

### Run specific topics only
```
python -m last30free watchlist run [topic_id_or_partial_match]
```

### Check alerts after a batch run
```
python -m last30free alerts
```
This evaluates alert rules (new items, source spikes, keyword spikes) across all topics that have at least two saved runs.

### View per-topic alert detail
```
python -m last30free alerts [topic_ref]
```

## Editing the watchlist

The watchlist is a JSON file at `outputs/watchlist.json`. Each topic entry has:
- `id` — unique slug
- `query` — the research query
- `enabled` — true/false
- `days` — lookback window
- `depth` — "quick", "balanced", or "deep"
- `sources` — list of sources, or empty for all available

To add a topic: edit `watchlist.json` directly and add an entry following the existing schema.
To disable a topic without deleting it: set `"enabled": false`.

## Alert triage

After running `alerts`, assess each triggered alert:

| Alert type | What it means | Recommended action |
|---|---|---|
| `new_item` | Fresh content appeared this run | Check score — if high, run `social-post-brief` |
| `source_spike` | One source added significantly more items | Check which source and why |
| `keyword_spike` | A keyword jumped in frequency | New angle emerging — consider `trend-scan` with that keyword |

### Escalation decision

Escalate to content creation if:
- A `new_item` alert fires with a score above 5.0
- A `keyword_spike` alert fires on a keyword not previously in the top patterns
- Two or more alert types fire on the same topic in the same run

Otherwise, log and wait for the next scheduled run.

## Output to produce

- List of topics currently tracked (enabled/disabled)
- Summary of last batch run results (items per topic, any errors)
- Alert triage: which alerts fired, severity, recommended action
- Next step recommendation: escalate to content, re-scan with narrower query, or wait
