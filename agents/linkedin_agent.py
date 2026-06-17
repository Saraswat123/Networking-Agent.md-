"""
LinkedIn Agent — profile research + message sending via Playwright browser automation.

LinkedIn has no public API for messaging. Two approaches:
  A) Playwright (browser automation) — free, reliable, needs Chrome
  B) LinkedIn official API — restricted, needs approval, no DMs on free tier

This uses Playwright approach:
  - Logs into LinkedIn with your credentials
  - Navigates to profile
  - Sends connection request or InMail message
  - Saves to sent log

Setup:
  pip install playwright
  playwright install chromium

Add to .env:
  LINKEDIN_EMAIL=saraswatdas94@gmail.com
  LINKEDIN_PASSWORD=your_password

IMPORTANT: Use slowly. LinkedIn bans accounts that automate too aggressively.
Limits: max 20 connection requests/day, 5 messages/day. Built-in delays enforced.
"""

import json
import os
import time
import random
from pathlib import Path
from typing import Optional

OUTPUT_DIR = Path(__file__).parent / "output" / "linkedin"
SESSION_PATH = Path(__file__).parent.parent / "linkedin_session.json"
SENT_LOG = OUTPUT_DIR / "sent.jsonl"

# Hard rate limits — DO NOT exceed or risk ban
MAX_CONNECTIONS_PER_DAY = 20
MAX_MESSAGES_PER_DAY = 5
MIN_DELAY_BETWEEN_ACTIONS = 8   # seconds
MAX_DELAY_BETWEEN_ACTIONS = 20  # seconds


def _check_daily_limit(action: str) -> bool:
    """Check if daily limit reached for connections or messages."""
    from datetime import datetime, date
    if not SENT_LOG.exists():
        return True
    today = date.today().isoformat()
    count = 0
    with open(SENT_LOG) as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("date") == today and entry.get("action") == action:
                    count += 1
            except Exception:
                pass
    limit = MAX_CONNECTIONS_PER_DAY if action == "connect" else MAX_MESSAGES_PER_DAY
    if count >= limit:
        print(f"  [linkedin] Daily {action} limit reached ({limit}/day). Try tomorrow.")
        return False
    return True


def _random_delay():
    """Human-like delay between actions."""
    delay = random.uniform(MIN_DELAY_BETWEEN_ACTIONS, MAX_DELAY_BETWEEN_ACTIONS)
    time.sleep(delay)


def _log_action(action: str, profile_url: str, text: str = ""):
    """Log sent action to file."""
    from datetime import date
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "action": action,
        "profile_url": profile_url,
        "text": text[:200],
        "date": date.today().isoformat(),
        "ts": __import__("datetime").datetime.now().isoformat(),
    }
    with open(SENT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


async def _get_browser_page():
    """Launch Playwright browser, login to LinkedIn."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError("Run: pip install playwright && playwright install chromium")

    email = os.environ.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")
    if not email or not password:
        raise ValueError("Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env")

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
    )

    ctx_kwargs = dict(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
        locale="en-US",
    )
    if SESSION_PATH.exists():
        ctx_kwargs["storage_state"] = str(SESSION_PATH)

    context = await browser.new_context(**ctx_kwargs)
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page = await context.new_page()

    if SESSION_PATH.exists():
        # Session exists — navigate directly to feed
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        if "feed" in page.url or "mynetwork" in page.url:
            return page, browser, pw
        # Session expired — fall through to login
        print("  [linkedin] Session expired, re-login needed. Run: python3 agents/linkedin_setup.py")

    # No session or expired — login with credentials
    await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)

    try:
        email_box = page.get_by_role("textbox", name="Email or phone").last
        await email_box.wait_for(state="visible", timeout=8000)
        await email_box.click()
        await email_box.type(email, delay=30)
    except Exception:
        await page.screenshot(path="/tmp/linkedin_debug.png")
        raise RuntimeError(f"LinkedIn login form not found. URL: {page.url}")

    pass_box = page.get_by_label("Password", exact=True).last
    await pass_box.click()
    await pass_box.type(password, delay=30)
    await pass_box.press("Enter")

    try:
        await page.wait_for_url("**/feed/**", timeout=20000)
    except Exception:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

    if any(x in page.url for x in ["checkpoint", "challenge", "verification", "login"]):
        raise RuntimeError(
            "LinkedIn security challenge detected.\n"
            "Fix: run  python3 agents/linkedin_setup.py  to log in manually and save session."
        )

    return page, browser, pw


async def send_connection_request(profile_url: str, note: str = "", dry_run: bool = False) -> dict:
    """
    Send LinkedIn connection request with optional note (300 char max).
    Use for Track A targets (technical companies, engineers).
    """
    if not _check_daily_limit("connect"):
        return {"status": "limit_reached"}

    if dry_run:
        print(f"\n[DRY RUN] Connect: {profile_url}\nNote: {note[:100]}\n")
        return {"status": "dry_run", "profile_url": profile_url}

    page, browser, pw = await _get_browser_page()
    try:
        await page.goto(profile_url)
        await page.wait_for_load_state("networkidle")
        _random_delay()

        # Click Connect button
        connect_btn = page.locator("button:has-text('Connect')")
        if await connect_btn.count() == 0:
            return {"status": "no_connect_button", "profile_url": profile_url}

        await connect_btn.first.click()
        _random_delay()

        if note:
            # Click "Add a note"
            add_note = page.locator("button:has-text('Add a note')")
            if await add_note.count() > 0:
                await add_note.click()
                await page.fill("textarea[name='message']", note[:300])
                _random_delay()

        # Send
        send_btn = page.locator("button:has-text('Send')")
        if await send_btn.count() > 0:
            await send_btn.click()

        _log_action("connect", profile_url, note)
        print(f"  [linkedin] Connected → {profile_url}")
        return {"status": "sent", "action": "connect", "profile_url": profile_url}

    finally:
        await browser.close()
        await pw.stop()


async def send_message(profile_url: str, message: str, dry_run: bool = False) -> dict:
    """
    Send LinkedIn message to an existing connection.
    Use after connection is accepted (wait 2-3 days).
    """
    if not _check_daily_limit("message"):
        return {"status": "limit_reached"}

    if dry_run:
        print(f"\n[DRY RUN] Message: {profile_url}\n{message[:200]}\n")
        return {"status": "dry_run", "profile_url": profile_url}

    page, browser, pw = await _get_browser_page()
    try:
        await page.goto(profile_url)
        await page.wait_for_load_state("networkidle")
        _random_delay()

        msg_btn = page.locator("button:has-text('Message')")
        if await msg_btn.count() == 0:
            return {"status": "no_message_button", "profile_url": profile_url}

        await msg_btn.first.click()
        _random_delay()

        msg_box = page.locator(".msg-form__contenteditable")
        await msg_box.fill(message)
        _random_delay()

        send_btn = page.locator("button.msg-form__send-button")
        await send_btn.click()

        _log_action("message", profile_url, message)
        print(f"  [linkedin] Messaged → {profile_url}")
        return {"status": "sent", "action": "message", "profile_url": profile_url}

    finally:
        await browser.close()
        await pw.stop()


def get_sent_stats() -> dict:
    """How many connections + messages sent today."""
    from datetime import date
    today = date.today().isoformat()
    connects = messages = 0
    if SENT_LOG.exists():
        with open(SENT_LOG) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get("date") == today:
                        if e.get("action") == "connect":
                            connects += 1
                        elif e.get("action") == "message":
                            messages += 1
                except Exception:
                    pass
    return {
        "today": today,
        "connections_sent": connects,
        "connections_remaining": max(0, MAX_CONNECTIONS_PER_DAY - connects),
        "messages_sent": messages,
        "messages_remaining": max(0, MAX_MESSAGES_PER_DAY - messages),
    }
