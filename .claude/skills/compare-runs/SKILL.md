---
name: compare-runs
description: Compare two saved last30free runs and identify trend deltas — what's new, accelerating, or cooling. Use this when the user wants to see how a topic has changed between two research runs.
---

# compare-runs

Compare two saved runs and turn the diff into actionable creator insights.

## When to invoke

- "How has [topic] changed since last week?"
- "Compare my two [topic] runs"
- "What's new since the last scan?"
- "What's gaining momentum on [topic]?"
- "Show me the trend delta"

## Steps

1. **Resolve the two runs** — the user may specify run IDs, partial topic names, or say "latest" and "previous":
   ```
   python -m last30free runs
   ```
   to list available runs and find the right IDs.

2. **Run the comparison:**
   ```
   python -m last30free compare [earlier_ref] [later_ref]
   ```
   Use run IDs, partial topic strings, or manifest paths as refs.

3. **Interpret the comparison output:**
   - **Added items** — content that appeared in the later run but not the earlier one → "what's new"
   - **Removed items** — content that dropped out → "what cooled"
   - **Score changes** — items with large positive delta → "what's accelerating"
   - **Source count changes** — if one platform spiked, that's a signal
   - **Keyword changes** — new keywords entering the top 10 indicate emerging angles

4. **Frame as creator insights:**
   - New angle worth covering (appeared fresh, high score)
   - Accelerating topic (was present before, now scoring higher)
   - Cooling topic (was prominent, now dropped)
   - Platform shift (topic moved from Reddit to X, or from HN to YouTube)

5. **Recommend next action** — run `asset-pack` on the strongest new item, or `social-post-brief` if the delta is large enough to warrant content.

## Output to produce

- A delta summary: what's new, accelerating, cooling
- Top 2–3 creator-ready insights with source evidence
- Recommended next skill to invoke if warranted
