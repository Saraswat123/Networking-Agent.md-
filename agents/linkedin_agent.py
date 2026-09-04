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
MAX_CONNECTIONS_PER_DAY = 35   # 20 morning + 15 evening
MAX_FOLLOWS_PER_DAY = 150      # follows have no hard LinkedIn cap but keep safe
MAX_MESSAGES_PER_DAY = 5
MIN_DELAY_BETWEEN_ACTIONS = 6   # seconds
MAX_DELAY_BETWEEN_ACTIONS = 15  # seconds


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


async def search_people(keyword: str, limit: int = 10) -> list[str]:
    """
    Search LinkedIn People for a job title/keyword.
    Returns list of profile URLs to connect with.

    Example: search_people("protocol engineer ethereum", limit=10)
    """
    page, browser, pw = await _get_browser_page()
    try:
        import urllib.parse
        query = urllib.parse.quote(keyword)
        search_url = f"https://www.linkedin.com/search/results/people/?keywords={query}&origin=GLOBAL_SEARCH_HEADER"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        profile_urls = []
        import re

        # Try multiple selectors — LinkedIn changes DOM often
        selectors = [
            "a.app-aware-link",
            "a[href*='/in/']",
            ".entity-result__title-text a",
            ".search-result__result-link",
        ]
        for selector in selectors:
            try:
                links = await page.locator(selector).all()
                for link in links:
                    href = await link.get_attribute("href") or ""
                    m = re.search(r"linkedin\.com/in/([A-Za-z0-9_%-]+)", href)
                    if m:
                        clean = f"https://www.linkedin.com/in/{m.group(1)}"
                        if clean not in profile_urls:
                            profile_urls.append(clean)
                if profile_urls:
                    break
            except Exception:
                continue

        # Fallback: extract from page HTML
        if not profile_urls:
            content = await page.content()
            matches = re.findall(r'href="(https://www\.linkedin\.com/in/[A-Za-z0-9_%-]+)', content)
            for m in matches:
                clean = m.split("?")[0].rstrip("/")
                if clean not in profile_urls:
                    profile_urls.append(clean)

        import random
        random.shuffle(profile_urls)
        return profile_urls[:limit]

    except Exception as e:
        print(f"  [linkedin] search error: {e}")
        return []
    finally:
        await browser.close()
        await pw.stop()


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
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Dismiss any overlays (cookie banners, modals)
        for dismiss_sel in ["button:has-text('Accept')", "button:has-text('Dismiss')", "button[aria-label='Dismiss']"]:
            try:
                btn = page.locator(dismiss_sel).first
                if await btn.count() > 0:
                    await btn.click(timeout=2000)
                    await page.wait_for_timeout(500)
            except Exception:
                pass

        async def _js_click(locator):
            """Click via JS to bypass pointer-event interception."""
            el = await locator.element_handle(timeout=3000)
            if el:
                await page.evaluate("el => el.click()", el)
                return True
            return False

        # Strategy 1: span with text "Connect" inside profile actions
        # LinkedIn renders: <button><span>Connect</span></button>
        # button:has-text misses it — target span directly, click bubbles to button
        found_via = None
        connect_span = None

        # Profile actions area (top of page, before sidebar)
        # Try a few selectors in order of specificity
        selectors = [
            # Exact span text — most reliable
            "span:text-is('Connect')",
            # Button with aria-label containing Invite/Connect
            "button[aria-label*='Invite'], button[aria-label*='connect']",
            # Fallback: any element containing only "Connect"
            ":text-is('Connect')",
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                connect_span = loc
                found_via = f"span ({sel})"
                break

        if not connect_span:
            # Strategy 2: "More" dropdown — sometimes Connect is hidden there
            more_btn = page.locator("button:has-text('More')").first
            if await more_btn.count() > 0:
                try:
                    await _js_click(more_btn)
                except Exception:
                    await more_btn.click(force=True)
                await page.wait_for_timeout(1200)
                dropdown_connect = page.locator("span:text-is('Connect')").first
                if await dropdown_connect.count() > 0:
                    connect_span = dropdown_connect
                    found_via = "more_dropdown"

        if not connect_span:
            await page.screenshot(path="/tmp/li_no_connect.png")
            return {"status": "no_connect_button", "profile_url": profile_url}

        print(f"    [connect] found via {found_via}")
        try:
            await _js_click(connect_span)
        except Exception:
            await connect_span.click(force=True)
        await page.wait_for_timeout(1500)

        if note:
            try:
                add_note = page.locator("span:text-is('Add a note'), button[aria-label*='note']").first
                if await add_note.count() > 0:
                    try:
                        await _js_click(add_note)
                    except Exception:
                        await add_note.click(force=True)
                    await page.wait_for_timeout(800)
                    textarea = page.locator("textarea[name='message'], textarea").first
                    await textarea.fill(note[:300], timeout=5000)
                    await page.wait_for_timeout(500)
            except Exception:
                # Note UI didn't open as expected (LinkedIn sometimes restricts notes for
                # out-of-network profiles) — fall through and send without a note rather
                # than losing the connection request entirely.
                print(f"    [connect] note step failed, sending without note")

        # Send
        send_btn = page.locator(
            "span:text-is('Send without a note'), span:text-is('Send invitation'), "
            "span:text-is('Send'), span:text-is('Done')"
        ).first
        if await send_btn.count() > 0:
            try:
                await _js_click(send_btn)
            except Exception:
                await send_btn.click(force=True)
            await page.wait_for_timeout(1000)

        _log_action("connect", profile_url, note)
        print(f"  [linkedin] Connected → {profile_url}")
        return {"status": "sent", "action": "connect", "profile_url": profile_url}

    except Exception as e:
        return {"status": "error", "error": str(e)[:200], "profile_url": profile_url}
    finally:
        await browser.close()
        await pw.stop()


async def follow_profile(profile_url: str, dry_run: bool = False) -> dict:
    """
    Follow a LinkedIn profile (not a connection request).
    No limit per day — instant, no approval needed.
    Builds your follower count + visibility in their feed.
    """
    if dry_run:
        print(f"\n[DRY RUN] Follow: {profile_url}")
        return {"status": "dry_run", "profile_url": profile_url}

    page, browser, pw = await _get_browser_page()
    try:
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # LinkedIn follow button — various selectors
        follow_btn = page.locator("button:has-text('Follow')").first
        if await follow_btn.count() == 0:
            # Try alternate — "More" menu follow option
            return {"status": "no_follow_button", "profile_url": profile_url}

        await follow_btn.click()
        await page.wait_for_timeout(1000)

        _log_action("follow", profile_url)
        print(f"  [linkedin] Followed → {profile_url}")
        return {"status": "followed", "action": "follow", "profile_url": profile_url}

    except Exception as e:
        return {"status": "error", "error": str(e), "profile_url": profile_url}
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
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
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


async def batch_connect_urls(
    url_note_pairs: list[tuple[str, str]],
    dry_run: bool = False,
    limit: int = 35,
) -> dict:
    """
    One browser session: connect with a list of known LinkedIn profile URLs.
    url_note_pairs: [(profile_url, note), ...]
    Returns {"sent": n, "skipped": n}.
    """
    import random

    if dry_run:
        for url, note in url_note_pairs[:limit]:
            name = url.split("/in/")[-1].split("/")[0]
            print(f"  [DRY] Connect: {name} | {note[:60]}")
        return {"sent": 0, "skipped": 0, "dry_run": True}

    if not _check_daily_limit("connect"):
        return {"sent": 0, "skipped": 0, "limit": True}

    page, browser, pw = await _get_browser_page()
    sent = 0
    skipped = 0

    async def _js_click(locator):
        el = await locator.element_handle(timeout=3000)
        if el:
            await page.evaluate("el => el.click()", el)
            return True
        return False

    try:
        for url, note in url_note_pairs:
            if sent >= limit:
                break
            if not _check_daily_limit("connect"):
                break

            # Normalise URL — strip query params
            url = url.split("?")[0].rstrip("/")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2500)

                connect_span = None
                for sel in ["span:text-is('Connect')", "button[aria-label*='Invite']", ":text-is('Connect')"]:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        connect_span = loc
                        break

                if not connect_span:
                    more = page.locator("button:has-text('More')").first
                    if await more.count() > 0:
                        await _js_click(more)
                        await page.wait_for_timeout(1200)
                        loc = page.locator("span:text-is('Connect')").first
                        if await loc.count() > 0:
                            connect_span = loc

                if not connect_span:
                    skipped += 1
                    continue

                await _js_click(connect_span)
                await page.wait_for_timeout(1500)

                if note:
                    try:
                        add_note = page.locator(
                            "span:text-is('Add a note'), button[aria-label*='note']"
                        ).first
                        if await add_note.count() > 0:
                            await _js_click(add_note)
                            await page.wait_for_timeout(800)
                            textarea = page.locator("textarea[name='message'], textarea").first
                            await textarea.fill(note[:300], timeout=5000)
                            await page.wait_for_timeout(500)
                    except Exception:
                        pass

                send_btn = page.locator(
                    "span:text-is('Send without a note'), span:text-is('Send invitation'), "
                    "span:text-is('Send'), span:text-is('Done')"
                ).first
                if await send_btn.count() > 0:
                    await _js_click(send_btn)
                    await page.wait_for_timeout(1200)

                name = url.split("/in/")[-1].split("/")[0]
                _log_action("connect", url, note)
                print(f"  [linkedin] Connected → {name} | {note[:60]}...")
                sent += 1

                await page.wait_for_timeout(random.randint(6000, 14000))

            except Exception as e:
                skipped += 1
                name = url.split("/in/")[-1].split("/")[0]
                print(f"    [connect] error {name}: {e}")

    finally:
        await browser.close()
        await pw.stop()

    return {"sent": sent, "skipped": skipped}


async def batch_search_and_connect(
    keyword_notes: list[tuple[str, str]],
    dry_run: bool = False,
    limit: int = 35,
) -> dict:
    """
    One browser session: search multiple keywords → connect with note.
    Returns {"sent": n, "skipped": n}.
    keyword_notes: list of (keyword, note) tuples.
    """
    import re, urllib.parse, random

    if dry_run:
        return {"sent": 0, "skipped": 0, "dry_run": True}

    if not _check_daily_limit("connect"):
        return {"sent": 0, "skipped": 0, "limit": True}

    page, browser, pw = await _get_browser_page()
    sent = 0
    skipped = 0
    seen_urls: set[str] = set()

    async def _js_click(locator):
        el = await locator.element_handle(timeout=3000)
        if el:
            await page.evaluate("el => el.click()", el)
            return True
        return False

    try:
        for kw, note in keyword_notes:
            if sent >= limit:
                break
            if not _check_daily_limit("connect"):
                break

            query = urllib.parse.quote(kw)
            search_url = (
                f"https://www.linkedin.com/search/results/people/"
                f"?keywords={query}&origin=GLOBAL_SEARCH_HEADER"
            )
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # Collect profile URLs from search results
            profile_urls: list[str] = []
            content = await page.content()

            # Debug: screenshot + URL if no profiles found on first keyword
            if not profile_urls and kw == keyword_notes[0][0]:
                await page.screenshot(path="/tmp/li_search_debug.png")
                print(f"  [debug] URL after search: {page.url[:100]}")
                print(f"  [debug] Page title: {await page.title()}")

            matches = re.findall(r'href="(https://www\.linkedin\.com/in/[A-Za-z0-9_%-]+)', content)
            for m in matches:
                clean = m.split("?")[0].rstrip("/")
                if clean not in seen_urls:
                    profile_urls.append(clean)
                    seen_urls.add(clean)
            print(f"  [debug] {kw[:40]}: {len(profile_urls)} profiles found")
            random.shuffle(profile_urls)

            for url in profile_urls[:8]:
                if sent >= limit:
                    break
                if not _check_daily_limit("connect"):
                    break

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(2500)

                    # Find Connect button
                    connect_span = None
                    for sel in ["span:text-is('Connect')", "button[aria-label*='Invite']", ":text-is('Connect')"]:
                        loc = page.locator(sel).first
                        if await loc.count() > 0:
                            connect_span = loc
                            print(f"    [connect] found via {sel}")
                            break

                    if not connect_span:
                        # Try More dropdown
                        more = page.locator("button:has-text('More')").first
                        if await more.count() > 0:
                            await _js_click(more)
                            await page.wait_for_timeout(1200)
                            loc = page.locator("span:text-is('Connect')").first
                            if await loc.count() > 0:
                                connect_span = loc

                    if not connect_span:
                        skipped += 1
                        continue

                    await _js_click(connect_span)
                    await page.wait_for_timeout(1500)

                    if note:
                        try:
                            add_note = page.locator(
                                "span:text-is('Add a note'), button[aria-label*='note']"
                            ).first
                            if await add_note.count() > 0:
                                await _js_click(add_note)
                                await page.wait_for_timeout(800)
                                textarea = page.locator("textarea[name='message'], textarea").first
                                await textarea.fill(note[:300], timeout=5000)
                                await page.wait_for_timeout(500)
                        except Exception:
                            pass  # send without note if UI doesn't cooperate

                    send_btn = page.locator(
                        "span:text-is('Send without a note'), span:text-is('Send invitation'), "
                        "span:text-is('Send'), span:text-is('Done')"
                    ).first
                    if await send_btn.count() > 0:
                        await _js_click(send_btn)
                        await page.wait_for_timeout(1200)

                    _log_action("connect", url, note)
                    print(f"  [linkedin] Connected → {url}")
                    sent += 1

                    # Human-like delay between connections
                    await page.wait_for_timeout(random.randint(6000, 14000))

                except Exception as e:
                    skipped += 1
                    print(f"    [connect] error {url}: {e}")

    finally:
        await browser.close()
        await pw.stop()

    return {"sent": sent, "skipped": skipped}


async def batch_follow_profiles(
    keyword_list: list[str],
    dry_run: bool = False,
    limit: int = 150,
    urls_per_keyword: int = 20,
) -> dict:
    """
    One browser session: search multiple keywords → follow each profile.
    Dramatically faster than calling follow_profile() in a loop
    (avoids repeated browser launch + LinkedIn session load per profile).
    Returns {"followed": n, "skipped": n}.
    """
    import re, urllib.parse, random

    if dry_run:
        return {"followed": 0, "skipped": 0, "dry_run": True}

    page, browser, pw = await _get_browser_page()
    followed = 0
    skipped = 0
    seen_urls: set[str] = set()

    async def _js_click(locator):
        el = await locator.element_handle(timeout=3000)
        if el:
            await page.evaluate("el => el.click()", el)
            return True
        return False

    followed_urls: list[str] = []

    try:
        for kw in keyword_list:
            if followed >= limit:
                break

            query = urllib.parse.quote(kw)
            search_url = (
                f"https://www.linkedin.com/search/results/people/"
                f"?keywords={query}&origin=GLOBAL_SEARCH_HEADER"
            )
            # Catch network errors at keyword level — break with partial count
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2500)
            except Exception as e:
                print(f"  [linkedin] Network error on search ({kw}): {e!s:.120}")
                break  # stop keyword loop, return what we have

            # Collect profile URLs
            profile_urls: list[str] = []
            try:
                content = await page.content()
                matches = re.findall(r'href="(https://www\.linkedin\.com/in/[A-Za-z0-9_%-]+)', content)
                for m in matches:
                    clean = m.split("?")[0].rstrip("/")
                    if clean not in seen_urls:
                        profile_urls.append(clean)
                        seen_urls.add(clean)
            except Exception:
                continue

            for url in profile_urls[:urls_per_keyword]:
                if followed >= limit:
                    break
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(2000)

                    follow_btn = page.locator("button:has-text('Follow')").first
                    if await follow_btn.count() == 0:
                        more = page.locator("button:has-text('More')").first
                        if await more.count() > 0:
                            await _js_click(more)
                            await page.wait_for_timeout(1000)
                            follow_btn = page.locator("span:text-is('Follow')").first

                    if await follow_btn.count() == 0:
                        skipped += 1
                        continue

                    await _js_click(follow_btn)
                    await page.wait_for_timeout(1000)

                    _log_action("follow", url)
                    print(f"  [linkedin] Followed → {url}")
                    followed_urls.append(url)
                    followed += 1

                    await page.wait_for_timeout(random.randint(3000, 7000))

                except Exception as e:
                    err = str(e)[:80]
                    if "ERR_INTERNET_DISCONNECTED" in err or "ERR_NETWORK" in err:
                        print(f"  [linkedin] Network lost during follow — stopping")
                        break
                    skipped += 1

    finally:
        try:
            await browser.close()
            await pw.stop()
        except Exception:
            pass

    return {"followed": followed, "skipped": skipped, "urls": followed_urls}


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
