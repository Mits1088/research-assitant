"""
Run this to see exactly what API responses X fires.
Usage: python debug_x.py "claude code"
"""
import asyncio
import sys
import json
from urllib.parse import quote
from dotenv import load_dotenv
import os

load_dotenv()

QUERY = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "claude code"
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "").strip()
CT0 = os.getenv("CT0", "").strip()

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

async def main():
    from playwright.async_api import async_playwright

    print(f"Searching X for: {QUERY}")
    print(f"Auth token: {AUTH_TOKEN[:10]}...\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent=_DESKTOP_UA,
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )

        await context.add_cookies([
            {"name": "auth_token", "value": AUTH_TOKEN, "domain": ".x.com", "path": "/", "httpOnly": True, "secure": True},
            {"name": "ct0", "value": CT0, "domain": ".x.com", "path": "/", "httpOnly": False, "secure": True},
        ])

        page = await context.new_page()

        async def handle_response(response):
            url = response.url
            if "SearchTimeline" not in url and "search_timeline" not in url.lower():
                return

            try:
                body = await response.body()
                print(f"\n*** SearchTimeline response: {len(body)} bytes ***")
                print(f"URL: {url[:100]}")

                with open("x_search_timeline.json", "wb") as f:
                    f.write(body)
                print("Saved to x_search_timeline.json")

                data = json.loads(body)

                def print_structure(obj, indent=0, path="", max_depth=6):
                    if indent > max_depth:
                        return
                    prefix = "  " * indent
                    if isinstance(obj, dict):
                        for k, v in list(obj.items())[:8]:
                            full = f"{path}.{k}" if path else k
                            if isinstance(v, list):
                                print(f"{prefix}{k}: list[{len(v)}]")
                                if v:
                                    print_structure(v[0], indent+1, full+"[0]", max_depth)
                            elif isinstance(v, dict):
                                print(f"{prefix}{k}: dict")
                                print_structure(v, indent+1, full, max_depth)
                            else:
                                val = str(v)[:60]
                                if any(key in k.lower() for key in ["text", "count", "name", "time", "date", "id"]):
                                    print(f"{prefix}{k}: {val}  <<<")
                                else:
                                    print(f"{prefix}{k}: {val}")

                print_structure(data)
            except Exception as e:
                print(f"Error parsing response: {e}")

        page.on("response", handle_response)

        url = f"https://x.com/search?q={quote(QUERY)}&src=typed_query&f=live"
        print(f"Navigating to: {url}\n")

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            print("Page loaded. Waiting 8s for API calls...")
            await asyncio.sleep(8)
        except Exception as e:
            print(f"Navigation error: {e}")

        await browser.close()

    print("\nDone.")

asyncio.run(main())
