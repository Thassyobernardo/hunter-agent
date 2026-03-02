"""
Indeed job scraper using the public RSS feed.

Indeed exposes a standard RSS feed at https://www.indeed.com/rss that requires
no API key or authentication. feedparser handles the HTTP request and XML
parsing, making this the most reliable scraper in the stack.

Feed URL: https://www.indeed.com/rss?q={keyword}&sort=date&fromage=14&limit=25
  - fromage=14  → jobs posted in the last 14 days
  - sort=date   → newest first
  - limit=25    → results per query
"""
import re
import time
import random
import logging

import feedparser

from database import upsert_lead, save_proposal
from proposal_generator import process_lead

log = logging.getLogger(__name__)

SOURCE = "indeed"
BASE_URL = "https://www.indeed.com/rss"

# Automation-specific keyword variations that yield high-quality leads on Indeed
EXTRA_KEYWORDS = [
    "python automation developer",
    "web scraping developer",
    "automation engineer",
    "data extraction developer",
    "backend automation",
]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def scrape(keywords: list[str], max_per_keyword: int = 15) -> int:
    # Combine caller keywords with automation-specific extras (deduplicated)
    all_kw = list(keywords)
    seen: set[str] = set(k.lower() for k in keywords)
    for kw in EXTRA_KEYWORDS:
        if kw.lower() not in seen:
            all_kw.append(kw)
            seen.add(kw.lower())

    saved = 0

    for i, kw in enumerate(all_kw):
        if i > 0:
            time.sleep(random.uniform(2, 5))

        url = (
            f"{BASE_URL}"
            f"?q={kw.replace(' ', '+')}"
            f"&sort=date&fromage=14&limit={max_per_keyword}"
        )

        try:
            feed = feedparser.parse(url)
        except Exception as e:
            log.warning("[Indeed] Feed fetch error for '%s': %s", kw, e)
            continue

        if not feed.entries:
            log.info("[Indeed] No entries returned for keyword: %s", kw)
            continue

        log.info("[Indeed] '%s' → %d entries", kw, len(feed.entries))

        for entry in feed.entries[:max_per_keyword]:
            title   = entry.get("title", "").strip()
            link    = entry.get("link", "").strip()
            summary = _strip_html(entry.get("summary", ""))

            # Indeed appends " - Company - Location" to the title in RSS
            # Normalise: keep everything before the last " - " cluster
            if " - " in title:
                parts = title.rsplit(" - ", 2)
                title = parts[0].strip()

            if not link or not title:
                continue

            posted_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    from datetime import datetime
                    posted_at = datetime(*entry.published_parsed[:6]).isoformat()
                except Exception:
                    posted_at = entry.get("published")

            lead_id = upsert_lead(
                source=SOURCE,
                title=title,
                description=summary,
                url=link,
                author=None,
                posted_at=posted_at,
                keywords=kw,
            )

            if lead_id:
                try:
                    analysis, proposal = process_lead(lead_id, SOURCE, title, summary)
                    save_proposal(lead_id, analysis, proposal)
                    saved += 1
                    log.info("[Indeed] Saved #%d: %s", lead_id, title[:60])
                except Exception as e:
                    log.warning("[Indeed] Proposal error #%d: %s", lead_id, e)

    return saved
