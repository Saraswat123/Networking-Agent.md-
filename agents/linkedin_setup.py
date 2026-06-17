"""
One-time LinkedIn session setup.

Run this ONCE to save LinkedIn cookies. After that, linkedin_agent.py
uses saved session — no login needed, no security challenges.

Usage:
  python3 agents/linkedin_setup.py

What it does:
  1. Opens VISIBLE Chrome browser (not headless)
  2. Navigates to linkedin.com/login
  3. You log in manually (handles 2FA, CAPTCHA, etc.)
  4. Press ENTER in terminal when fully logged in
  5. Saves session to linkedin_session.json
  6. All future linkedin_agent calls skip login and use saved session
"""

import asyncio
import sys
from pathlib import Path

SESSION_PATH = Path(__file__).parent.parent / "linkedin_session.json"


async def setup():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Run: pip3 install playwright && playwright install chromium")
        sys.exit(1)

    print("\n[linkedin] Opening browser — log in manually then press ENTER here.\n")

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
    )
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page = await context.new_page()
    await page.goto("https://www.linkedin.com/login")

    print("Browser opened. Log in to LinkedIn (handle any 2FA/CAPTCHA).")
    print("Once you see your LinkedIn feed, press ENTER here to save session.")
    input()

    url = page.url
    if "feed" not in url and "mynetwork" not in url:
        print(f"[linkedin] Warning: URL is {url} — may not be logged in yet.")
        print("Are you on the feed page? Save anyway? (y/n)")
        if input().strip().lower() != "y":
            await browser.close()
            await pw.stop()
            print("Cancelled.")
            return

    await context.storage_state(path=str(SESSION_PATH))
    await browser.close()
    await pw.stop()

    print(f"\n[linkedin] Session saved → {SESSION_PATH}")
    print("linkedin_agent.py will now use this session automatically.")


if __name__ == "__main__":
    asyncio.run(setup())
