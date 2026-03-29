---
name: trend-scan
description: Run the last30free research engine for a topic and produce a saved run. Use this when the user wants to know what's trending, what people are discussing, what tools are recommended, or what's happening on social platforms in the last 30 days.
---

# trend-scan

Run the research engine for a topic and synthesize cross-platform findings into a saved run.

## When to invoke

- "What's trending with [topic]?"
- "What are people saying about [topic] on Reddit / HN / YouTube / X?"
- "Research [topic] for me"
- "What's hot in [topic] right now?"
- "Give me a last 30 days scan on [topic]"

## Steps

1. **Normalize the topic** — strip filler words, resolve any "X vs Y" into a comparison intent if needed.

2. **Run the research command:**
   ```
   python -m last30free "[topic]" --save
   ```
   Common flags:
   - `--quick` for a fast scan (10 items/source)
   - `--deep` for comprehensive coverage (40 items/source)
   - `--source reddit --source hn` to limit sources
   - `--days 7` to narrow the window
   - `--literal` to bypass intent cleaning and pass the query verbatim

3. **Inspect the output artifacts** — after `--save`, the run produces four files in `outputs/<run_id>/`:
   - `report.md` — human-readable synthesis
   - `manifest.json` — run metadata and file paths
   - `merged_items.json` — all scored items across sources
   - `run_payload.json` — full structured payload

4. **Read `report.md`** and summarize:
   - The strongest cross-platform themes (appear on 3+ sources)
   - Top 3–5 items by score with their source and URL
   - Any evidence quality gaps (e.g. X returned 0 results, YouTube had no transcripts)
   - Recommended follow-up queries if the results are thin

5. **Surface the run ID** so the user can reference it in `compare-runs`, `asset-pack`, or `social-post-brief`.

## Output to produce

- A concise summary of what the scan found (3–5 bullet points)
- The run ID for downstream use
- Any source errors or gaps worth flagging

## Reference files

- `references/output-files.md` — schema for each artifact file
