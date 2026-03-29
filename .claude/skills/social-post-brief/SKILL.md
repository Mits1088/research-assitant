---
name: social-post-brief
description: Convert a saved last30free run into creator-ready content outputs — hooks, talking points, carousel structure, short-form script angle, and asset list. Use this when the user wants to turn research into content.
---

# social-post-brief

Turn a saved research run into a structured content brief with source-backed claims only.

## When to invoke

- "Turn this research into a post"
- "Give me hooks for [topic]"
- "Write a carousel outline from this run"
- "What's my content angle here?"
- "Build a brief from the [topic] scan"
- "Script this for a reel"

## Steps

1. **Identify the source run** — ask for a run ID or topic if not given, then:
   ```
   python -m last30free show [run_ref]
   ```
   or read `outputs/<run_id>/report.md` and `merged_items.json` directly.

2. **Extract the strongest evidence** from `merged_items.json`:
   - Top 5 items by score across all sources
   - Items with quotes (transcript excerpts, top comments)
   - Items with high engagement metrics relative to their source norms

3. **Produce the content brief:**

   ### Hook options (3 variations)
   - Contrarian hook: challenges a common assumption found in the data
   - Data hook: leads with a specific number or stat from the results
   - Story hook: opens with the most surprising single item found

   ### Talking points (5 max)
   - Each point must be backed by at least one item from the run
   - Include the source name and URL for every claim
   - Order by: strongest evidence first

   ### Format-specific outputs
   - **Carousel**: slide-by-slide outline (cover + 5–7 content slides + CTA)
   - **Short-form reel script**: hook (0–3s) / setup (3–8s) / payoff (8–25s) / CTA (25–30s)
   - **Long-form YouTube angle**: title options, thumbnail concept, 5-point outline

4. **Asset list** — what the user needs to gather before posting:
   - Screenshots to capture (specific URLs)
   - Video timestamps to clip (if YouTube items are in the run)
   - Graphics or data visualisations needed

5. **Provenance check** — every claim in the brief must trace back to an item in `merged_items.json`. Flag any talking point that lacks a source.

## Output to produce

- 3 hook options
- 5 talking points with citations
- Carousel outline OR reel script (based on user's preferred format)
- Asset list
- Provenance summary: X claims, all sourced

## Reference files

- `templates/post-brief-template.md` — blank template to fill
