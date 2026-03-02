"""
SimplyHired job scraper using requests + BeautifulSoup.

SimplyHired renders job listings server-side so plain HTTP requests work.
We use a stack of CSS selector fallbacks to stay resilient against minor
HTML structure changes. User-agent rotation and moderate delays keep the
request rate within acceptable limits.

Search URL: https://www.simplyhired.com/search?q={keyword}&sort=dd
  - sort=dd  → newest first ("date descending")
"""
import re
import time
import random
import logging
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from database import upsert_lead, save_proposal
from proposal_generator import process_lead

log = logging.getLogger(__name__)

SOURCE = "simplyhired"
BASE_URL = "https://www.simplyhired.com"
SEARCH_URL = f"{BASE_URL}/search"

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]


def _headers() -> dict:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://www.simplyhired.com/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _fetch(keyword: str) -> str | None:
    params = {"q": keyword, "sort": "dd"}
    try:
        resp = requests.get(
            SEARCH_URL,
            params=params,
            headers=_headers(),
            timeout=20,
            allow_redirects=True,
        )
        resp.raise_for_status()
        if len(resp.text) < 1000:
            log.warning("[SimplyHired] Suspiciously short response for '%s'", keyword)
            return None
        return resp.text
    except Exception as e:
        log.warning("[SimplyHired] Fetch error for '%s': %s", keyword, e)
        return None


def _parse_jobs(html: str) -> list[dict]:
    """
    Parse SimplyHired job listings with stacked fallback selectors.

    SimplyHired occasionally refactors its HTML; multiple selector strategies
    ensure we keep finding results even after minor markup changes.
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    seen_urls: set[str] = set()

    # ── Strategy 1: li[data-jobkey] (most common current structure) ──────────
    cards = soup.select("li[data-jobkey]")

    # ── Strategy 2: SerpJob divs ─────────────────────────────────────────────
    if not cards:
        cards = soup.select("div.SerpJob, article.SerpJob")

    # ── Strategy 3: generic job article/li containers ────────────────────────
    if not cards:
        cards = soup.select(
            "article[class*='job'], li[class*='job'], div[class*='job-card']"
        )

    for card in cards:
        try:
            # Title + link — try selectors from most to least specific
            title_a = (
                card.select_one("a.jobposting-title")
                or card.select_one("h2 > a[href]")
                or card.select_one("h3 > a[href]")
                or card.select_one("a[data-testid='jobTitle']")
                or card.select_one("a[href*='/job/']")
            )
            if not title_a:
                continue

            title = title_a.get_text(strip=True)
            href  = title_a.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = BASE_URL + href
            if href in seen_urls:
                continue
            seen_urls.add(href)

            # Description snippet
            snip_el = (
                card.select_one(".jobposting-snippet")
                or card.select_one("p[class*='snippet']")
                or card.select_one("p[class*='description']")
                or card.select_one("p")
            )
            snippet = snip_el.get_text(separator=" ", strip=True) if snip_el else ""

            if title:
                jobs.append({
                    "title": title,
                    "url": href,
                    "snippet": snippet[:2000],
                })
        except Exception:
            continue

    return jobs


def scrape(keywords: list[str], max_per_keyword: int = 15) -> int:
    saved = 0

    for i, kw in enumerate(keywords):
        if i > 0:
            time.sleep(random.uniform(6, 12))

        html = _fetch(kw)
        if not html:
            continue

        jobs = _parse_jobs(html)
        log.info("[SimplyHired] '%s' → %d jobs parsed", kw, len(jobs))

        for job in jobs[:max_per_keyword]:
            lead_id = upsert_lead(
                source=SOURCE,
                title=job["title"],
                description=job["snippet"],
                url=job["url"],
                keywords=kw,
            )

            if lead_id:
                try:
                    analysis, proposal = process_lead(
                        lead_id, SOURCE, job["title"], job["snippet"]
                    )
                    save_proposal(lead_id, analysis, proposal)
                    saved += 1
                    log.info("[SimplyHired] Saved #%d: %s", lead_id, job["title"][:60])
                except Exception as e:
                    log.warning("[SimplyHired] Proposal error #%d: %s", lead_id, e)

    return saved
