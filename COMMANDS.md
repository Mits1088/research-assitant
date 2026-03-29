# last30free — Command Reference

## Setup (do this once)

### 1. Navigate to the project
```bash
cd "D:\Research-Assitant - Copy\last30free"
```

### 2. Copy the env file and fill in credentials
```bash
cp .env.example .env
```

Open `.env` and fill in what you have. **Minimum to get started (no credentials needed):**
Reddit, HN, and YouTube work out of the box — no keys required.

**Optional credentials for more sources:**

| Source | What to set | Where to get it |
|--------|-------------|-----------------|
| X/Twitter | `AUTH_TOKEN` + `CT0` | Browser → x.com → DevTools (F12) → Application → Cookies |
| Instagram | `INSTAGRAM_SESSION_ID` | Browser → instagram.com → DevTools → Application → Cookies → sessionid |
| Facebook | `FACEBOOK_C_USER` + `FACEBOOK_XS` | Browser → facebook.com → DevTools → Application → Cookies |
| TikTok | Nothing — works automatically | — |

### 3. Install dependencies
```bash
pip install -e .
playwright install chromium
```

---

## Running a search

### Basic search (Reddit + HN + YouTube)
```bash
python -m last30free "AI coding tools"
```

### Save results to disk
```bash
python -m last30free "AI coding tools" --save
```
Creates `outputs/<timestamp>_ai-coding-tools/` with four files:
- `report.md` — human-readable synthesis
- `manifest.json` — run metadata and file paths
- `merged_items.json` — all scored items across sources
- `run_payload.json` — full structured payload

### Control depth
```bash
python -m last30free "AI coding tools" --quick    # 10 items/source, fast
python -m last30free "AI coding tools"             # 25 items/source, balanced (default)
python -m last30free "AI coding tools" --deep      # 40 items/source, thorough
```

### Limit to specific sources
```bash
python -m last30free "AI coding tools" --source reddit
python -m last30free "AI coding tools" --source reddit --source hn
python -m last30free "AI coding tools" --source youtube --source x
```

### Change the time window
```bash
python -m last30free "AI coding tools" --days 7     # last 7 days
python -m last30free "AI coding tools" --days 90    # last 90 days
```

### Filter results to keywords (AND logic)
```bash
python -m last30free "AI coding tools" --filter cursor --filter vscode
```

### Skip intent parsing (pass query verbatim)
```bash
python -m last30free "prompts for Midjourney" --literal
```

### JSON output instead of terminal table
```bash
python -m last30free "AI coding tools" --json
```

### Override items per source
```bash
python -m last30free "AI coding tools" --per-source-limit 5
```

---

## Viewing saved runs

### List all saved runs
```bash
python -m last30free runs
python -m last30free runs --limit 50
```

### Show a specific run (by run ID, partial topic, or path)
```bash
python -m last30free show abc123
python -m last30free show "ai coding"
```

### Show the latest run per topic
```bash
python -m last30free latest
python -m last30free latest "ai coding"
```

---

## Comparing runs

```bash
python -m last30free compare abc123 def456
python -m last30free compare "ai coding" "ai coding tools"
```
Shows: new items, removed items, score changes, keyword shifts, source count changes.

---

## Alerts

```bash
python -m last30free alerts                       # all topics with 2+ runs
python -m last30free alerts "ai coding"           # specific topic
python -m last30free alerts --new-item-threshold 3 --keyword-spike-threshold 5
```

---

## Notifications

```bash
python -m last30free notify
python -m last30free notify "ai coding" --channel email --channel webhook
python -m last30free notify --save
python -m last30free notify-history
```

---

## Watchlist (ongoing monitoring)

```bash
python -m last30free watchlist init               # create starter watchlist.json
python -m last30free watchlist show               # view current topics
python -m last30free watchlist run                # run all enabled topics and save
python -m last30free watchlist run --dry-run      # preview without executing
python -m last30free watchlist run "ai coding"    # specific topic only
python -m last30free watchlist payloads           # show CLI payloads for scheduling
```

Edit `outputs/watchlist.json` directly to add or disable topics.

---

## Content generation (requires Anthropic API key)

```bash
python -m last30free generate --format facebook_post --latest
python -m last30free generate --format instagram_carousel --run-id abc123
python -m last30free generate --format instagram_reel --latest "ai coding"
python -m last30free generate --format youtube_script --latest --save
```

**Available formats:** `facebook_post`, `instagram_carousel`, `instagram_reel`, `youtube_script`

---

## Streamlit dashboard (visual UI)

```bash
streamlit run src/last30free/dashboard.py
```

---

## Recommended first-run flow

```bash
# 1. First search — no credentials needed
python -m last30free "your topic here" --quick --save

# 2. Read the report
cat outputs/<run_dir>/report.md

# 3. Run again later and compare
python -m last30free "your topic here" --quick --save
python -m last30free compare "your topic" "your topic"

# 4. Check for alerts
python -m last30free alerts "your topic"

# 5. Generate content from the research
python -m last30free generate --format instagram_carousel --latest "your topic"
```
