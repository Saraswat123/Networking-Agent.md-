"""Scrape article list from saraswat.vercel.app/writing for X posting."""

import re
import json
import urllib.request
from datetime import datetime
from pathlib import Path

WRITING_URL = "https://saraswat.vercel.app/writing"
CACHE_FILE = Path(__file__).parent / "output" / "articles_cache.json"

ARTICLES_FALLBACK = [
    {
        "id": "ai-zk",
        "title": "AI agents can't be trusted. ZK proofs fix that.",
        "tag": "AI × ZK Proofs",
        "hook": "Every AI agent running today is a black box. It produces outputs — but you can't verify HOW it got there.",
        "date": "Jun 2026",
        "url": "https://saraswat.vercel.app/writing/ai-zk",
    },
    {
        "id": "ebpf-ai",
        "title": "You can't secure what you can't see — eBPF for AI agent networks.",
        "tag": "eBPF × Security",
        "hook": "You can't secure what you can't see. eBPF gives you eyes inside the kernel — syscalls, network traffic, memory — without touching the application.",
        "date": "Jun 2026",
        "url": "https://saraswat.vercel.app/writing/ebpf-ai",
    },
    {
        "id": "pq-ai",
        "title": "The AI systems we build today will be broken by quantum computers.",
        "tag": "Post-Quantum",
        "hook": "Most AI infrastructure encrypts with RSA or ECDSA. Shor's algorithm breaks both — and quantum computers are coming.",
        "date": "Jun 2026",
        "url": "https://saraswat.vercel.app/writing/pq-ai",
    },
    {
        "id": "firm-learning-loop",
        "title": "Human Capital + Token Capital: The Firm in the Age of AI",
        "tag": "Essay · Strategy",
        "hook": "This transition is different than any previous platform shift. The marginal cost of intelligence is approaching zero.",
        "date": "Jun 2026",
        "url": "https://saraswat.vercel.app/writing/firm-learning-loop",
    },
    {
        "id": "on-building",
        "title": "On Building Things That Cannot Lie",
        "tag": "Philosophy",
        "hook": "Every system I build is, at its core, a statement about what I believe should be true about the world.",
        "date": "Jun 2026",
        "url": "https://saraswat.vercel.app/writing/on-building",
    },
    {
        "id": "freedom-to-speak",
        "title": "Freedom to Speak to Myself",
        "tag": "Personal · Expression",
        "hook": "There is a specific feeling that happens when a thought forms that is completely yours.",
        "date": "Jun 2026",
        "url": "https://saraswat.vercel.app/writing/freedom-to-speak",
    },
]


def fetch_articles(use_cache: bool = True) -> list[dict]:
    """Fetch articles from writing page, with cache fallback."""
    if use_cache and CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text())
            if cached.get("fetched_date") == datetime.now().strftime("%Y-%m-%d"):
                return cached["articles"]
        except Exception:
            pass

    try:
        req = urllib.request.Request(WRITING_URL, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=10).read().decode()
        chunks = re.findall(r'src="(/_next/static/chunks/[^"]+\.js)"', html)

        for c in chunks:
            url = "https://saraswat.vercel.app" + c
            try:
                r = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                js = urllib.request.urlopen(r, timeout=5).read().decode()
                if "freedom-to-speak" not in js:
                    continue

                ids = re.findall(r'\{id:"([a-z][a-z0-9-]+)"', js)
                titles = re.findall(r'title:"([^"]+)"', js)
                tags = re.findall(r'tag:"([^"]+)"', js)
                hooks = re.findall(r'hook:"((?:[^"\\]|\\.){0,300})"', js)

                articles = []
                for i, aid in enumerate(ids):
                    if aid == "writing":
                        continue
                    articles.append({
                        "id": aid,
                        "title": titles[i] if i < len(titles) else "",
                        "tag": tags[i] if i < len(tags) else "",
                        "hook": hooks[i].replace("\\n", " ").replace("\\'", "'") if i < len(hooks) else "",
                        "date": "Jun 2026",
                        "url": f"https://saraswat.vercel.app/writing/{aid}",
                    })

                if articles:
                    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    CACHE_FILE.write_text(json.dumps({
                        "fetched_date": datetime.now().strftime("%Y-%m-%d"),
                        "articles": articles,
                    }, indent=2))
                    return articles
            except Exception:
                continue

    except Exception:
        pass

    return ARTICLES_FALLBACK


def get_article_for_tweet(posted_ids: list[str] = None) -> dict:
    """Return next unposted article. Cycles back when all posted."""
    articles = fetch_articles()
    posted = set(posted_ids or [])

    # Priority: tech articles first (ZK, eBPF, post-quantum)
    priority_order = ["ai-zk", "ebpf-ai", "pq-ai", "firm-learning-loop", "on-building", "freedom-to-speak"]
    sorted_articles = sorted(
        articles,
        key=lambda a: priority_order.index(a["id"]) if a["id"] in priority_order else 99,
    )

    for a in sorted_articles:
        if a["id"] not in posted:
            return a

    # All posted → cycle from tech articles again
    return sorted_articles[0]
