"""
Upwork scraper via public RSS feeds (no API key required).
RSS endpoint: https://www.upwork.com/ab/feed/jobs/rss?q=<keyword>&sort=recency
"""
import feedparser
import os
from datetime import datetime
from database import upsert_lead, save_proposal
from proposal_generator import process_lead

BASE_URL = "https://www.upwork.com/ab/feed/jobs/rss"
SOURCE = "upwork"


def _parse_entry(entry) -> dict:
    posted = None
    if hasattr(entry, "published"):
        try:
            posted = datetime(*entry.published_parsed[:6]).isoformat()
        except Exception:
            posted = entry.published

    description = getattr(entry, "summary", "") or ""
    # Strip HTML tags lightly
    import re
    description = re.sub(r"<[^>]+>", " ", description).strip()

    return {
        "title": entry.get("title", "No title"),
        "url": entry.get("link", ""),
        "description": description,
        "author": entry.get("author", None),
        "posted_at": posted,
    }


def scrape(keywords: list[str], max_per_keyword: int = 10) -> int:
    saved = 0
    for kw in keywords:
        feed_url = f"{BASE_URL}?q={kw.replace(' ', '+')}&sort=recency&paging=0%3B{max_per_keyword}"
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"[Upwork] Failed to fetch feed for '{kw}': {e}")
            continue

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
                    print(f"[Upwork] Saved lead #{lead_id}: {parsed['title'][:60]}")
                except Exception as e:
                    print(f"[Upwork] Proposal error for #{lead_id}: {e}")

    return saved
