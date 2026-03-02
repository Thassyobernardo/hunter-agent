"""
Freelancer.com scraper via public RSS feed (no API key required).

Feed: https://www.freelancer.com/rss/jobs/all

Returns all active project listings; we filter by keyword relevance so only
automation, dev, and AI-adjacent leads are stored.
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

SOURCE = "freelancer"
FEED_URL = "https://www.freelancer.com/rss/jobs/all"

# Terms that signal the project is relevant to automation/dev work
RELEVANCE_SIGNALS = [
    "python", "automation", "backend", "api", "data", "scraping",
    "devops", "django", "fastapi", "flask", "node", "javascript",
    "workflow", "integration", "chatbot", "ai", "machine learning",
    "developer", "engineer", "programmer", "n8n", "zapier", "make.com",
    "webhook", "bot", "script", "software", "web app", "database",
    "crm", "no-code", "low-code", "airtable", "bubble",
]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _is_relevant(title: str, description: str) -> bool:
    text = (title + " " + description).lower()
    return any(sig in text for sig in RELEVANCE_SIGNALS)


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


def scrape(keywords: list[str], max_entries: int = 50) -> int:
    # Extend relevance set with caller keywords
    relevance = set(RELEVANCE_SIGNALS)
    for kw in keywords:
        relevance.update(kw.lower().split())

    try:
        feed = feedparser.parse(FEED_URL)
    except Exception as e:
        log.warning("[Freelancer] Feed fetch error: %s", e)
        return 0

    log.info("[Freelancer] Feed → %d entries", len(feed.entries))

    saved = 0
    for entry in feed.entries[:max_entries]:
        parsed = _parse_entry(entry)
        if not parsed["url"]:
            continue
        if not _is_relevant(parsed["title"], parsed["description"]):
            continue

        lead_id = upsert_lead(
            source=SOURCE,
            title=parsed["title"],
            description=parsed["description"],
            url=parsed["url"],
            author=parsed["author"],
            posted_at=parsed["posted_at"],
            keywords=", ".join(keywords[:5]),
        )

        if lead_id:
            try:
                analysis, proposal = process_lead(
                    lead_id, SOURCE, parsed["title"], parsed["description"]
                )
                save_proposal(lead_id, analysis, proposal)
                saved += 1
                log.info("[Freelancer] Saved #%d: %s", lead_id, parsed["title"][:60])
            except Exception as e:
                log.warning("[Freelancer] Proposal error #%d: %s", lead_id, e)

        time.sleep(random.uniform(0.5, 1.5))

    return saved
