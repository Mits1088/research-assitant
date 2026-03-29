---
name: doctor
description: Diagnose why the research engine returned 0 results, a source errored, or credentials are missing. Use this when a scan fails, a source returns nothing, or the user reports unexpected output.
---

# doctor

Diagnose and fix issues with the research engine setup and source adapters.

## When to invoke

- "Why did X return 0 results?"
- "Reddit isn't working"
- "I'm not getting any YouTube results"
- "The scan failed"
- "Instagram says not configured"
- "Something's wrong with the output"

## Diagnostic steps

### 1. Check source status
```
python -m last30free "test query" --quick --source [source_name]
```
Look at the source execution table in the output. Status will be one of:
- `ok` — working
- `error` — adapter ran but failed (check the error message)
- `not_configured` — credentials missing
- `not_requested` — source wasn't selected

### 2. Check credential requirements by source

| Source | Required env vars | Where to get them |
|--------|------------------|-------------------|
| Reddit | None | Public API, no auth needed |
| HN | None | Public API, no auth needed |
| YouTube | None | Uses yt-dlp, no API key needed |
| X | `X_AUTH_TOKEN`, `X_CT0` | Browser DevTools → Cookies → x.com |
| Instagram | `INSTAGRAM_SESSION_ID` | Browser DevTools → Cookies → instagram.com → sessionid |
| TikTok | None (uses TLS fingerprint bypass) | — |
| Facebook | `FACEBOOK_C_USER`, `FACEBOOK_XS` | Browser DevTools → Application → Cookies → facebook.com |

### 3. Check .env file
```
cat .env.example
```
Verify your `.env` file at the project root has the required vars set.

### 4. Check yt-dlp for YouTube issues
```
python -m yt_dlp --version
```
If yt-dlp is missing: `pip install yt-dlp`
If results are stale: `pip install -U yt-dlp`

### 5. Check Playwright for browser-based sources (X, Instagram, Facebook, TikTok)
```
python -m playwright install chromium
```
Playwright must be installed for any browser-automation adapter to work.

### 6. Run with a simple known-good query
```
python -m last30free "python programming" --quick --source reddit
```
If this returns results, the engine is working and the issue is query-specific or credential-specific.

## Common failure patterns

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| X returns 0 results | Expired cookies | Re-capture `AUTH_TOKEN` + `CT0` from browser |
| Instagram `not_configured` | Missing session ID | Set `INSTAGRAM_SESSION_ID` in `.env` |
| YouTube returns 0 | yt-dlp outdated or rate-limited | `pip install -U yt-dlp`, retry |
| All sources return 0 | Query too narrow or time window too short | Try `--days 90` or broaden the query |
| Playwright timeout | Browser launch failed | `playwright install chromium`, check system resources |
| Facebook `not_configured` | Missing cookies | Set `FACEBOOK_C_USER` and `FACEBOOK_XS` in `.env` |

## Output to produce

- Diagnosis: which source(s) failed and why
- Fix instructions specific to the failure
- Verification command to confirm the fix worked
