"""
Search scraper using DuckDuckGo HTML endpoint + BeautifulSoup.

DuckDuckGo's html.duckduckgo.com interface returns full search results
as plain HTML with no JavaScript required — the only zero-cost option
that actually works with requests + BS4.

Supports the same queries as Google (site:upwork.com, quoted phrases,
boolean operators) and returns identical lead data.
"""
import re
import time
import random
from urllib.parse import urlencode, urlparse

import requests
from bs4 import BeautifulSoup

from database import upsert_lead, save_proposal
from proposal_generator import process_lead

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

# ── Browser headers ───────────────────────────────────────────────────────────

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]


def _make_headers() -> dict:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


# ── Query builder ─────────────────────────────────────────────────────────────

def _build_queries(keywords: list[str]) -> list[tuple[str, str]]:
    """Returns list of (query_string, source_keyword) tuples."""
    pairs = []
    for kw in keywords[:4]:
        for tmpl in QUERY_TEMPLATES:
            pairs.append((tmpl.format(keyword=kw), kw))
    return pairs


# ── DuckDuckGo fetch + parse ──────────────────────────────────────────────────

def _fetch(query: str) -> str | None:
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query, "kl": "us-en"}
    try:
        resp = requests.post(
            url,
            data=params,         # DDG HTML uses POST
            headers=_make_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        if "duckduckgo" not in resp.url and len(resp.text) < 500:
            print(f"[Google] Unexpected response for: {query[:60]}")
            return None
        return resp.text
    except Exception as e:
        print(f"[Google] Fetch error for '{query[:60]}': {e}")
        return None


def _clean_url(href: str) -> str | None:
    """Strip DDG redirect wrapper and return the real destination URL."""
    if not href:
        return None
    # DDG wraps results in //duckduckgo.com/l/?uddg=<encoded-url>
    if "duckduckgo.com/l/" in href:
        from urllib.parse import parse_qs, unquote
        qs = parse_qs(urlparse(href).query)
        uddg = qs.get("uddg", [])
        if uddg:
            href = unquote(uddg[0])
    if not href.startswith("http"):
        return None
    host = urlparse(href).netloc
    if "duckduckgo." in host:
        return None
    return href


def _parse_html(html: str, query: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_urls = set()

    for result_div in soup.select("div.result"):
        try:
            # Title + URL
            a_title = result_div.select_one("a.result__a")
            if not a_title:
                continue
            title = a_title.get_text(strip=True)
            url = _clean_url(a_title.get("href", ""))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            # Snippet
            snip_el = result_div.select_one("a.result__snippet")
            snippet = snip_el.get_text(separator=" ", strip=True) if snip_el else ""

            if title:
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet[:2000],
                    "query": query,
                })
        except Exception:
            continue

    return results


def _is_lead(result: dict) -> bool:
    text = (result["title"] + " " + result["snippet"]).lower()
    return any(sig in text for sig in LEAD_SIGNALS)


# ── Public scrape() ───────────────────────────────────────────────────────────

def scrape(keywords: list[str]) -> int:
    queries = _build_queries(keywords)
    saved = 0

    for i, (query, kw) in enumerate(queries):
        if i > 0:
            time.sleep(random.uniform(3, 7))

        html = _fetch(query)
        if not html:
            continue

        results = _parse_html(html, query)
        print(f"[Google] '{query[:55]}' → {len(results)} results")

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
                    print(f"[Google] Saved lead #{lead_id}: {result['title'][:60]}")
                except Exception as e:
                    print(f"[Google] Proposal error for #{lead_id}: {e}")

    return saved
