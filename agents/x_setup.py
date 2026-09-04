"""
One-time X (Twitter) browser session setup.

Run ONCE to save X cookies. After that, track_c_social.py uses saved
session for follows, likes, retweets — no login needed.

Usage:
  python3 agents/x_setup.py
"""

import asyncio
import sys
from pathlib import Path

SESSION_PATH = Path(__file__).parent.parent / "x_session.json"


async def setup():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Run: pip3 install playwright && playwright install chromium")
        sys.exit(1)

    print("\n[X] Opening browser — log in manually then press ENTER here.\n")

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 900},
    )
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page = await context.new_page()
    await page.goto("https://x.com/login")

    print("Browser opened. Log in to X as @SaraswatDas13 (handle 2FA if prompted).")
    print("Once you see your X home feed, press ENTER here to save session.")
    input()

    url = page.url
    if "home" not in url and "login" in url:
        print(f"[X] Warning: still on login page ({url}). Logged in? (y/n)")
        if input().strip().lower() != "y":
            await browser.close()
            await pw.stop()
            print("Cancelled.")
            return

    await context.storage_state(path=str(SESSION_PATH))
    await browser.close()
    await pw.stop()

    print(f"\n[X] Session saved → {SESSION_PATH}")
    print("track_c_social.py will now use this session for follows/likes/retweets.")


if __name__ == "__main__":
    asyncio.run(setup())
