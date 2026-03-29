# Run artifact file reference

Every `--save` run produces four files in `outputs/<timestamp>_<topic>/`:

## report.md
Human-readable synthesis in Markdown. Contains:
- Headline
- Key takeaways (bullet points)
- Recurring patterns (keyword + mention count + source count)
- Source stats (items, engagement metrics per source)
- Top merged items with URLs

## manifest.json
Run metadata. Key fields:
- `run_id` — unique identifier for this run (use in CLI refs)
- `generated_at_utc` — ISO timestamp
- `topic` — cleaned topic string
- `query_type` — GENERAL / NEWS / RECOMMENDATIONS / COMPARISON / PROMPTING
- `status` — "ok" or "partial"
- `runtime.selected_sources` — which sources ran
- `runtime.days` — lookback window
- `files.report_path` — absolute path to report.md
- `files.payload_path` — absolute path to run_payload.json
- `merged_items` — count of items across all sources

## merged_items.json
Array of all scored items sorted by score descending. Each item:
- `source` — reddit / hn / youtube / x / instagram / tiktok / facebook
- `title` — post/video/tweet title
- `url` — direct link
- `score` — float, higher = more relevant + engaging
- `created_at` — ISO timestamp
- `metrics` — engagement numbers (upvotes, comments, views, likes, etc.)
- `quotes` — array of extracted transcript quotes or top comments
- `tags` — source-specific tags (e.g. "r/MachineLearning", "channel:Fireship")
- `author` — username or channel name

## run_payload.json
Full structured payload. Contains everything in manifest + the complete synthesis object:
- `synthesis.headline`
- `synthesis.summary_points`
- `synthesis.patterns`
- `synthesis.source_stats`
- `results` — per-source status, count, and items
