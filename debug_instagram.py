"""
Run this to see exactly what API responses Instagram fires.
Usage: python debug_instagram.py chatgpt
"""
import asyncio
import sys
import json
from urllib.parse import unquote
from dotenv import load_dotenv
import os

load_dotenv()

HASHTAG = sys.argv[1] if len(sys.argv) > 1 else "chatgpt"
SESSION_ID = unquote(os.getenv("INSTAGRAM_SESSION_ID", "").strip())

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)

async def main():
    from playwright.async_api import async_playwright

    print(f"Loading Instagram hashtag page for: #{HASHTAG}")
    print("Watch for API responses below...\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent=_MOBILE_UA,
            viewport={"width": 390, "height": 844},
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        if SESSION_ID:
            print(f"Using session cookie: {SESSION_ID[:20]}...\n")
            await context.add_cookies([{
                "name": "sessionid",
                "value": SESSION_ID,
                "domain": ".instagram.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            }])
        else:
            print("No session cookie found (INSTAGRAM_SESSION_ID not set)\n")
        page = await context.new_page()

        async def handle_response(response):
            url = response.url
            # Skip static assets
            if any(ext in url for ext in [".js", ".css", ".png", ".jpg", ".svg", ".ico", ".woff"]):
                return
            if "fbcdn" in url or "cdninstagram" in url:
                return

            # Save the fbsearch response to a file for inspection
            if "fbsearch" in url or "top_serp" in url:
                try:
                    body = await response.body()
                    with open("instagram_fbsearch.json", "wb") as f:
                        f.write(body)
                    print(f"\n*** SAVED fbsearch response ({len(body)} bytes) to instagram_fbsearch.json ***\n")
                    data = json.loads(body)
                    def print_structure(obj, indent=0, path=""):
                        prefix = "  " * indent
                        if isinstance(obj, dict):
                            for k, v in list(obj.items())[:10]:
                                full = f"{path}.{k}" if path else k
                                if isinstance(v, list):
                                    print(f"{prefix}{k}: list[{len(v)}]")
                                    if v and isinstance(v[0], dict):
                                        print_structure(v[0], indent+1, full+"[0]")
                                elif isinstance(v, dict):
                                    print(f"{prefix}{k}: dict")
                                    print_structure(v, indent+1, full)
                                else:
                                    print(f"{prefix}{k}: {str(v)[:60]}")
                        elif isinstance(obj, list) and obj:
                            print_structure(obj[0], indent, path+"[0]")
                    print("fbsearch structure:")
                    print_structure(data)
                except Exception as e:
                    print(f"Could not parse fbsearch: {e}")
                return

            status = response.status
            try:
                body = await response.body()
                size = len(body)
            except Exception:
                size = 0
                body = b""

            print(f"[{status}] {size:>8} bytes  {url[:120]}")

            # Try to parse JSON and show structure
            if size > 0 and size < 500_000:
                try:
                    data = json.loads(body)
                    if isinstance(data, dict):
                        keys = list(data.keys())
                        print(f"           JSON keys: {keys}")
                        # Recursively search for useful keys
                        def find_keys(obj, depth=0, path=""):
                            if depth > 5:
                                return
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    full = f"{path}.{k}" if path else k
                                    if k in ("hashtag", "itemList", "sections", "edges", "media",
                                             "taken_at", "like_count", "shortcode", "id",
                                             "edge_hashtag_to_top_posts", "edge_hashtag_to_media"):
                                        if isinstance(v, list):
                                            print(f"           *** FOUND {full}: list of {len(v)}")
                                        elif isinstance(v, dict):
                                            print(f"           *** FOUND {full}: dict keys={list(v.keys())[:8]}")
                                        else:
                                            print(f"           *** FOUND {full}: {str(v)[:80]}")
                                    find_keys(v, depth+1, full)
                            elif isinstance(obj, list) and obj:
                                find_keys(obj[0], depth+1, f"{path}[0]")
                        find_keys(data)
                except Exception:
                    snippet = body[:200].decode("utf-8", errors="replace").replace("\n", " ")
                    print(f"           Non-JSON: {snippet}")

        page.on("response", handle_response)

        try:
            url = f"https://www.instagram.com/explore/search/keyword/?q=%23{HASHTAG}"
            print(f"Navigating to {url}\n")
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,
            )
            print(f"\nPage loaded. Final URL: {page.url}")
            print("Waiting 10s for API calls...\n")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"Navigation error: {e}")

        await browser.close()

    print("\nDone.")

asyncio.run(main())
