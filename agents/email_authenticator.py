"""
Authentic email finder — NEVER pattern-guesses.
Sources in order:
  1. YC company page (Our Ask / contact section)
  2. Company website /contact, /about, /team pages
  3. GitHub repo commits (company domain only, no personal gmail)
  4. Job posting pages on company site

Returns: {"email": str, "source": str, "confidence": "confirmed"|"none"}
If no confirmed email found → returns {"email": None, "source": "not_found"}

Rule: ONLY returns emails explicitly displayed on official pages.
NO pattern guessing. NO firstname@domain inference.
"""
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

SKIP_DOMAINS = {
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com',
    'noreply.github.com', 'users.noreply.github.com', 'example.com',
    'privaterelay.appleid.com',
}

SKIP_PREFIXES = {
    'no-reply', 'noreply', 'do-not-reply', 'donotreply',
    'mailer', 'daemon', 'bounce', 'notifications',
    'security@', 'privacy@', 'legal@', 'press@', 'media@',
    'abuse@', 'postmaster@', 'webmaster@',
}


def _extract_emails_from_text(text: str, company_domain: str = "") -> list[str]:
    """Extract valid emails from raw text, filter noise."""
    found = EMAIL_RE.findall(text)
    result = []
    for e in found:
        e_lower = e.lower()
        domain = e_lower.split('@')[1] if '@' in e_lower else ''
        prefix = e_lower.split('@')[0] if '@' in e_lower else ''

        if domain in SKIP_DOMAINS:
            continue
        if any(e_lower.startswith(p) for p in SKIP_PREFIXES):
            continue
        if 'example' in domain or 'test' in domain:
            continue
        # If company_domain given, prefer exact domain match
        if company_domain and domain != company_domain:
            continue
        if e not in result:
            result.append(e)
    return result


def _fetch_page(url: str, timeout: int = 8) -> str:
    """Fetch URL, return text or ''."""
    if not HAS_REQUESTS:
        return ""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; job-searcher/1.0)'}
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""


def find_from_yc_page(yc_url: str, company_domain: str = "") -> Optional[str]:
    """Scrape YC company page for explicit email in Our Ask / contact section."""
    if not yc_url:
        return None
    text = _fetch_page(yc_url)
    if not text:
        return None

    # Look for emails in the raw HTML
    all_emails = _extract_emails_from_text(text)
    if not all_emails:
        # Try with domain filter loosened
        all_emails = EMAIL_RE.findall(text)
        all_emails = [e for e in all_emails
                      if '@' in e
                      and not any(e.lower().startswith(p) for p in SKIP_PREFIXES)
                      and e.lower().split('@')[1] not in SKIP_DOMAINS]

    # Score: prefer company domain emails
    if company_domain:
        domain_matches = [e for e in all_emails if e.lower().endswith(f'@{company_domain}')]
        if domain_matches:
            return domain_matches[0]

    # Remove generic YC / ycombinator emails
    filtered = [e for e in all_emails if 'ycombinator' not in e.lower() and 'yc.com' not in e.lower()]
    return filtered[0] if filtered else None


def find_from_website(website: str, company_domain: str = "") -> Optional[str]:
    """Check /contact, /about, /team, /careers pages for explicit email."""
    if not website:
        return None

    base = website.rstrip('/')
    pages_to_try = [
        base,
        f"{base}/contact",
        f"{base}/about",
        f"{base}/team",
        f"{base}/careers",
        f"{base}/jobs",
        f"{base}/contact-us",
        f"{base}/about-us",
    ]

    for url in pages_to_try:
        text = _fetch_page(url)
        if not text:
            continue
        emails = _extract_emails_from_text(text, company_domain)
        if emails:
            return emails[0]

    return None


def find_from_github_commits(github_org: str = "", repo_url: str = "",
                              company_domain: str = "") -> Optional[str]:
    """Clone repo (depth=30) and extract emails matching company domain from commits."""
    import tempfile, os
    if not github_org and not repo_url:
        return None

    clone_url = repo_url if repo_url else f"https://github.com/{github_org}"

    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            ['git', 'clone', '--depth=30', '--quiet', clone_url, tmp + '/repo'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None

        log = subprocess.run(
            ['git', '-C', tmp + '/repo', 'log', '--format=%ae'],
            capture_output=True, text=True
        )
        emails = log.stdout.strip().splitlines()

        for e in emails:
            e = e.strip().lower()
            if not e or 'noreply' in e or 'bot' in e or 'action' in e:
                continue
            domain = e.split('@')[1] if '@' in e else ''
            if domain in SKIP_DOMAINS:
                continue
            if company_domain and domain == company_domain:
                return e
            elif not company_domain and domain not in SKIP_DOMAINS:
                return e

    return None


def find_authentic_email(
    company: str,
    domain: str,
    yc_url: str = "",
    website: str = "",
    github_org: str = "",
) -> dict:
    """
    Master function. Tries sources in order, returns first confirmed email.
    Never pattern-guesses.
    """
    print(f"  [auth-email] {company} (domain={domain})")

    # 1. YC page
    if yc_url:
        email = find_from_yc_page(yc_url, domain)
        if email:
            print(f"    ✅ YC page: {email}")
            return {"email": email, "source": "yc_page", "confidence": "confirmed"}

    # 2. Company website
    if website:
        email = find_from_website(website, domain)
        if email:
            print(f"    ✅ website: {email}")
            return {"email": email, "source": "website", "confidence": "confirmed"}

    # 3. GitHub commits
    if github_org:
        email = find_from_github_commits(github_org=github_org, company_domain=domain)
        if email:
            print(f"    ✅ github: {email}")
            return {"email": email, "source": "github_commits", "confidence": "confirmed"}

    print(f"    ❌ no email found in any authentic source")
    return {"email": None, "source": "not_found", "confidence": "none"}


if __name__ == "__main__":
    # Test on one company
    result = find_authentic_email(
        company="Test",
        domain="tracecat.com",
        yc_url="https://www.ycombinator.com/companies/tracecat",
        website="https://tracecat.com",
        github_org="TracecatHQ/tracecat",
    )
    print(result)
