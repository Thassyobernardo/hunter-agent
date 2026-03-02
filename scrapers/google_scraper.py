"""
Lead scraper using DuckDuckGo HTML endpoint.

DuckDuckGo's html.duckduckgo.com interface returns full search results as
plain HTML with no JavaScript required. When running on a datacenter IP
(e.g. Railway) DuckDuckGo sometimes blocks requests; in that case the scraper
automatically falls back to Upwork RSS with an expanded keyword set so a scan
never returns zero results.
"""
import re
import time
import random
import logging
from urllib.parse import urlparse, parse_qs, unquote

import feedparser
import requests
from bs4 import BeautifulSoup

from database import upsert_lead, save_proposal
from proposal_generator import process_lead

log = logging.getLogger(__name__)

SOURCE = "google"   # keeps dashboard source label consistent

# ── Query templates ───────────────────────────────────────────────────────────

QUERY_TEMPLATES = [
    'site:upwork.com "{keyword}"',
    '"looking for" "{keyword}" developer',
    '"need a" "{keyword}" developer freelancer',
    '"hire" "{keyword}" developer',
    '"help with" "{keyword}" project',
    '"{keyword}" developer "get in touch" OR "DM me" OR "contact me"',
]

LEAD_SIGNALS = [
    "looking for", "need a", "hire", "hiring", "freelancer",
    "help with", "build", "create", "automate", "developer",
    "get in touch", "dm me", "contact", "upwork.com",
    "budget", "project", "quote", "proposal",
]

# Fallback keywords used in the Upwork RSS backup pass
FALLBACK_KEYWORDS = [
    "python automation",
    "automation script",
    "web scraping",
    "data extraction",
    "api integration",
    "workflow automation",
    "bot development",
    "selenium scraper",
]

# ── User-agent pool ───────────────────────────────────────────────────────────

_USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Firefox Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Safari Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

_REFERERS = [
    "https://duckduckgo.com/",
    "https://www.google.com/",
    "https://search.yahoo.com/",
]


def _make_headers() -> dict:
    ua = random.choice(_USER_AGENTS)
    is_firefox = "Firefox" in ua
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Referer": random.choice(_REFERERS),
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        **({"sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1"} if not is_firefox else {}),
    }


# ── DuckDuckGo fetch + parse ──────────────────────────────────────────────────

def _clean_url(href: str) -> str | None:
    if not href:
        return None
    if "duckduckgo.com/l/" in href:
        qs = parse_qs(urlparse(href).query)
        uddg = qs.get("uddg", [])
        if uddg:
            href = unquote(uddg[0])
    if not href.startswith("http"):
        return None
    if "duckduckgo." in urlparse(href).netloc:
        return None
    return href


def _fetch_ddg(query: str) -> str | None:
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "us-en"},
            headers=_make_headers(),
            timeout=20,
        )
        resp.raise_for_status()
        # Detect block / JS-gate pages
        if len(resp.text) < 800 or "enable javascript" in resp.text.lower():
            log.warning("[Google] DDG returned a blocked/gate page for: %s", query[:60])
            return None
        return resp.text
    except Exception as e:
        log.warning("[Google] DDG fetch error for '%s': %s", query[:60], e)
        return None


def _parse_ddg_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    for div in soup.select("div.result"):
        try:
            a = div.select_one("a.result__a")
            if not a:
                continue
            title = a.get_text(strip=True)
            url = _clean_url(a.get("href", ""))
            if not url or url in seen:
                continue
            seen.add(url)
            snip = div.select_one("a.result__snippet")
            snippet = snip.get_text(separator=" ", strip=True) if snip else ""
            results.append({"title": title, "url": url, "snippet": snippet[:2000]})
        except Exception:
            continue
    return results


def _is_lead(r: dict) -> bool:
    text = (r["title"] + " " + r["snippet"]).lower()
    return any(sig in text for sig in LEAD_SIGNALS)


# ── Upwork RSS fallback ───────────────────────────────────────────────────────

_UPWORK_RSS = "https://www.upwork.com/ab/feed/jobs/rss"


def _upwork_rss_fallback(keywords: list[str]) -> int:
    """
    Run when DuckDuckGo is blocked. Queries Upwork RSS with the caller's
    keywords plus a broader set of automation-related terms.
    Labels leads as SOURCE="upwork" for accuracy.
    """
    combined = list(keywords) + FALLBACK_KEYWORDS
    seen_kw: set[str] = set()
    unique_kw = [k for k in combined if not (k in seen_kw or seen_kw.add(k))]

    saved = 0
    for kw in unique_kw[:10]:
        url = f"{_UPWORK_RSS}?q={kw.replace(' ', '+')}&sort=recency&paging=0%3B10"
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            log.warning("[Google/Fallback] Upwork RSS error for '%s': %s", kw, e)
            continue

        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            link  = entry.get("link", "")
            desc  = re.sub(r"<[^>]+>", " ", entry.get("summary", "")).strip()
            if not link:
                continue

            lead_id = upsert_lead(
                source="upwork",
                title=title,
                description=desc,
                url=link,
                keywords=kw,
            )
            if lead_id:
                try:
                    analysis, proposal = process_lead(lead_id, "upwork", title, desc)
                    save_proposal(lead_id, analysis, proposal)
                    saved += 1
                    log.info("[Google/Fallback] Saved #%d: %s", lead_id, title[:60])
                except Exception as e:
                    log.warning("[Google/Fallback] Proposal error #%d: %s", lead_id, e)

        time.sleep(random.uniform(1, 3))

    return saved


# ── Public scrape() ───────────────────────────────────────────────────────────

def scrape(keywords: list[str]) -> int:
    queries = []
    for kw in keywords[:4]:
        for tmpl in QUERY_TEMPLATES:
            queries.append((tmpl.format(keyword=kw), kw))

    saved = 0
    ddg_hits = 0   # track total raw results — zero means DDG is blocked

    for i, (query, kw) in enumerate(queries):
        if i > 0:
            # Longer delays on server/datacenter IPs reduce block rate
            time.sleep(random.uniform(8, 15))

        html = _fetch_ddg(query)
        if not html:
            continue

        results = _parse_ddg_html(html)
        ddg_hits += len(results)
        log.info("[Google] '%s' → %d results", query[:55], len(results))

        for result in results:
            if not _is_lead(result):
                continue

            lead_id = upsert_lead(
                source=SOURCE,
                title=result["title"],
                description=result["snippet"],
                url=result["url"],
                keywords=kw,
            )
            if lead_id:
                try:
                    analysis, proposal = process_lead(
                        lead_id, SOURCE, result["title"], result["snippet"]
                    )
                    save_proposal(lead_id, analysis, proposal)
                    saved += 1
                    log.info("[Google] Saved #%d: %s", lead_id, result["title"][:60])
                except Exception as e:
                    log.warning("[Google] Proposal error #%d: %s", lead_id, e)

    # If DDG returned nothing at all, the IP is likely blocked — run fallback
    if ddg_hits == 0:
        log.warning("[Google] DDG returned 0 results — activating Upwork RSS fallback")
        saved += _upwork_rss_fallback(keywords)

    return saved
