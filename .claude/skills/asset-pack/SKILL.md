---
name: asset-pack
description: Extract supporting assets from a saved research run — screenshot targets, video clip timestamps, transcript quotes, and an asset bundle for a post or reel. Use this when the user needs to gather evidence assets before creating content.
---

# asset-pack

Bridge between research results and the assets needed to produce content.

## When to invoke

- "What screenshots do I need for this post?"
- "Find me the best video clips from this research"
- "Pull the strongest quotes from this run"
- "Build an asset list for [topic]"
- "What should I screenshot before I post?"

## Steps

1. **Identify the source run** — ask for a run ID or topic if not given:
   ```
   python -m last30free show [run_ref]
   ```

2. **Scan `merged_items.json`** for asset-worthy content by type:

   ### Screenshots
   - Reddit threads with 100+ upvotes or 50+ comments → screenshot the thread header and top comment
   - X posts with high engagement → screenshot the post (and any notable replies)
   - HN threads scoring 100+ points → screenshot the submission
   - Any item with a striking title that validates your content angle

   ### Video clips (YouTube items)
   - Items with `quotes` populated → those are transcript excerpts with timestamps
   - Extract: video URL, quote text, approximate timestamp
   - Flag videos where the quote directly supports a talking point

   ### Pull quotes (for text overlay or caption)
   - From `quotes` fields across all items
   - Rank by: relevance to topic angle + author credibility + quote length (under 280 chars preferred)
   - Select top 3–5 quotes with attribution (author, source, URL)

3. **Produce the asset bundle:**

   ```
   ## Asset pack — [topic] — [run_id]

   ### Screenshots to capture
   1. [URL] — [why: what to capture]
   2. ...

   ### Video timestamps to note
   1. [YouTube URL] — [timestamp range] — [quote text]
   2. ...

   ### Pull quotes
   1. "[quote text]" — [author], [source] — [URL]
   2. ...

   ### Graphics needed
   - [Any data points worth visualising]
   ```

4. **Prioritise by content format:**
   - Carousel → needs 5–7 screenshots or data points
   - Reel → needs 1–3 video clips or striking screenshot sequences
   - Single post → needs 1 hero screenshot or 1 pull quote

## Note on retrieval capabilities

The current system retrieves metadata, titles, scores, and transcript quotes via adapters. Direct screenshot capture and video downloading are not yet automated — this skill produces the *plan* for what to capture manually. When screenshot and clip extraction are added to the retrieval plane, this skill will be updated to execute the captures directly.

## Output to produce

- Prioritised screenshot list with URLs and capture instructions
- Video clip list with timestamps and quote text
- Top 3–5 pull quotes with attribution
- Format-specific asset priority (carousel vs reel vs single post)
