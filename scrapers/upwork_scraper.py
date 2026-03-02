"""
Upwork scraper via public RSS feeds (no API key required).
RSS endpoint: https://www.upwork.com/ab/feed/jobs/rss?q=<keyword>&sort=recency

Uses a broad, hardcoded keyword list covering automation, AI, no-code, and
freelance dev niches — much wider coverage than the user-configured KEYWORDS
alone. User keywords are appended so their intent is always included too.
"""
import re
import time
import random
import logging
from datetime import datetime

import feedparser

from database import upsert_lead, save_proposal
from proposal_generator import process_lead

log = logging.getLogger(__name__)

BASE_URL = "https://www.upwork.com/ab/feed/jobs/rss"
SOURCE = "upwork"

# Broad keyword list — covers the niches most likely to need automation work
CORE_KEYWORDS = [
    # Automation & workflow
    "automation",
    "workflow automation",
    "process automation",
    "business automation",
    "n8n",
    "make.com",
    "zapier",
    # AI & chatbots
    "AI automation",
    "chatbot development",
    "ChatGPT integration",
    "AI agent",
    # No-code / low-code
    "no-code automation",
    "bubble developer",
    "airtable automation",
    # CRM & email
    "CRM automation",
    "email automation",
    "HubSpot automation",
    "ActiveCampaign",
    # Data & scraping
    "data scraping",
    "web scraping",
    "data extraction",
    "data pipeline",
    # Dev / integration
    "API integration",
    "Python developer",
    "JavaScript automation",
    "backend developer",
    "webhook integration",
]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _parse_entry(entry) -> dict:
    posted = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            posted = datetime(*entry.published_parsed[:6]).isoformat()
        except Exception:
            posted = getattr(entry, "published", None)

    return {
        "title":       entry.get("title", "No title"),
        "url":         entry.get("link", ""),
        "description": _strip_html(entry.get("summary", "")),
        "author":      entry.get("author", None),
        "posted_at":   posted,
    }


def scrape(keywords: list[str], max_per_keyword: int = 10) -> int:
    # Merge hardcoded list with caller-supplied keywords, preserving order
    seen: set[str] = set()
    all_keywords: list[str] = []
    for kw in CORE_KEYWORDS + list(keywords):
        key = kw.lower().strip()
        if key not in seen:
            seen.add(key)
            all_keywords.append(kw)

    saved = 0

    for i, kw in enumerate(all_keywords):
        if i > 0:
            time.sleep(random.uniform(1, 3))

        feed_url = (
            f"{BASE_URL}"
            f"?q={kw.replace(' ', '+')}"
            f"&sort=recency"
            f"&paging=0%3B{max_per_keyword}"
        )

        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            log.warning("[Upwork] Feed fetch error for '%s': %s", kw, e)
            continue

        if not feed.entries:
            log.debug("[Upwork] No entries for keyword: %s", kw)
            continue

        log.info("[Upwork] '%s' → %d entries", kw, len(feed.entries))

        for entry in feed.entries[:max_per_keyword]:
            parsed = _parse_entry(entry)
            if not parsed["url"]:
                continue

            lead_id = upsert_lead(
                source=SOURCE,
                title=parsed["title"],
                description=parsed["description"],
                url=parsed["url"],
                author=parsed["author"],
                posted_at=parsed["posted_at"],
                keywords=kw,
            )

            if lead_id:
                try:
                    analysis, proposal = process_lead(
                        lead_id, SOURCE, parsed["title"], parsed["description"]
                    )
                    save_proposal(lead_id, analysis, proposal)
                    saved += 1
                    log.info("[Upwork] Saved #%d: %s", lead_id, parsed["title"][:60])
                except Exception as e:
                    log.warning("[Upwork] Proposal error #%d: %s", lead_id, e)

    return saved
