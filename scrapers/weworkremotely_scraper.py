"""
WeWorkRemotely scraper via public RSS feeds (no API key required).

Feeds used:
  - Programming jobs:  https://weworkremotely.com/categories/remote-programming-jobs.rss
  - DevOps / SysAdmin: https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss

Both feeds return all current listings in each category; we filter by keyword
relevance after fetching so we only store leads that match the agent's focus.
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

SOURCE = "weworkremotely"

FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
]

# Terms that signal the job is relevant to automation/dev work
RELEVANCE_SIGNALS = [
    "python", "automation", "backend", "api", "data", "scraping",
    "devops", "django", "fastapi", "flask", "node", "javascript",
    "workflow", "integration", "chatbot", "ai", "machine learning",
    "developer", "engineer", "programmer",
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

    # WWR puts "Company: Title" in the title field — split it out
    raw_title = entry.get("title", "No title")
    if ": " in raw_title:
        parts = raw_title.split(": ", 1)
        company, title = parts[0].strip(), parts[1].strip()
    else:
        company, title = None, raw_title

    return {
        "title":       title,
        "url":         entry.get("link", ""),
        "description": _strip_html(entry.get("summary", "")),
        "author":      company,
        "posted_at":   posted,
    }


def scrape(keywords: list[str], max_per_feed: int = 30) -> int:
    # Build a relevance set from caller keywords + hardcoded signals
    relevance = set(RELEVANCE_SIGNALS)
    for kw in keywords:
        relevance.update(kw.lower().split())

    saved = 0

    for i, feed_url in enumerate(FEEDS):
        if i > 0:
            time.sleep(random.uniform(2, 5))

        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            log.warning("[WWR] Feed fetch error for %s: %s", feed_url, e)
            continue

        log.info("[WWR] %s → %d entries", feed_url.split("/")[-1], len(feed.entries))

        for entry in feed.entries[:max_per_feed]:
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
                    log.info("[WWR] Saved #%d: %s", lead_id, parsed["title"][:60])
                except Exception as e:
                    log.warning("[WWR] Proposal error #%d: %s", lead_id, e)

    return saved
