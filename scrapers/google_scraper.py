"""
DDG scraper with site-specific queries targeting companies HIRING automation
services on Upwork, Freelancer, and Fiverr — not job seekers.

Queries example for keyword "zapier automation":
  site:upwork.com/jobs "zapier automation"
  site:freelancer.com/projects "zapier automation"
  site:fiverr.com/requests "zapier automation"
"""
import time
import random
import logging

import requests
from bs4 import BeautifulSoup

from database import upsert_lead, save_proposal
from proposal_generator import process_lead

log = logging.getLogger(__name__)

SOURCE = "google"
DDG_URL = "https://html.duckduckgo.com/html/"

# Each keyword is substituted into every template
QUERY_TEMPLATES = [
    'site:upwork.com/jobs "{keyword}"',
    'site:freelancer.com/projects "{keyword}"',
]

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]


def _search_ddg(query: str, max_results: int = 5) -> list[dict]:
    headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
    }
    try:
        resp = requests.post(
            DDG_URL,
            data={"q": query, "b": "", "kl": "us-en"},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        log.warning("[Google] DDG request failed for %r: %s", query, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    anchors = soup.select("a.result__a")
    snippets = soup.select(".result__snippet")

    results = []
    for i, a in enumerate(anchors[:max_results]):
        url = a.get("href", "").strip()
        title = a.get_text(strip=True)
        description = snippets[i].get_text(strip=True) if i < len(snippets) else title
        if url and title:
            results.append({"title": title, "url": url, "description": description})

    return results


def scrape(keywords: list[str], max_per_query: int = 5) -> int:
    saved = 0
    request_count = 0

    for keyword in keywords:
        for template in QUERY_TEMPLATES:
            query = template.format(keyword=keyword)

            if request_count > 0:
                time.sleep(random.uniform(3, 5))
            request_count += 1

            results = _search_ddg(query, max_results=max_per_query)
            if not results:
                log.debug("[Google] No results for: %s", query)
                continue

            log.info("[Google] %r → %d results", query, len(results))

            for r in results:
                lead_id = upsert_lead(
                    source=SOURCE,
                    title=r["title"],
                    description=r["description"],
                    url=r["url"],
                    author=None,
                    posted_at=None,
                    keywords=keyword,
                )
                if lead_id:
                    try:
                        analysis, proposal = process_lead(
                            lead_id, SOURCE, r["title"], r["description"]
                        )
                        save_proposal(lead_id, analysis, proposal)
                        saved += 1
                        log.info("[Google] Saved #%d: %s", lead_id, r["title"][:60])
                    except Exception as e:
                        log.warning("[Google] Proposal error #%d: %s", lead_id, e)

    return saved
