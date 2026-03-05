"""
Upwork scraper via Apify actor flash_mage/upwork.

Uses the official apify-client library instead of the sync HTTP endpoint
to avoid 400/timeout errors on large result sets.

Actor: flash_mage~upwork
Input:  {"query": [keyword], "maxJobs": N}
Output: list of job objects with fields:
  - title
  - link  (full Upwork job URL)
  - data.opening.description
  - data.opening.postedOn
"""
import os
import time
import logging

from apify_client import ApifyClient

from database import upsert_lead, save_proposal
from proposal_generator import process_lead

log = logging.getLogger(__name__)

SOURCE = "upwork"
ACTOR = "flash_mage/upwork"

CORE_KEYWORDS = [
    "zapier automation",
]


def _get_client() -> ApifyClient:
    token = os.getenv("APIFY_TOKEN")
    log.info(f"[Upwork] APIFY_TOKEN (first 8): {str(token)[:8]}...")
    if not token:
        raise RuntimeError("APIFY_TOKEN is not set.")
    return ApifyClient(token)


def _fetch_jobs(client: ApifyClient, keyword: str, max_jobs: int = 5) -> list[dict]:
    try:
        run_input = {"query": [keyword], "maxJobs": max_jobs}
        log.info(f"[Upwork] Starting actor run for '{keyword}' with input: {run_input}")
        run = client.actor(ACTOR).call(run_input=run_input, timeout_secs=120)
        items = client.dataset(run["defaultDatasetId"]).list_items().items
        return items if isinstance(items, list) else []
    except Exception as e:
        log.warning("[Upwork] Actor call failed for '%s': %s", keyword, e)
        return []


def _parse_job(item: dict) -> dict | None:
    title = item.get("title", "").strip()
    url   = item.get("link", "").strip()
    if not title or not url:
        return None
    opening     = item.get("data", {}).get("opening", {})
    description = opening.get("description", "")
    posted_at   = opening.get("postedOn") or opening.get("publishTime")
    return {
        "title":       title,
        "url":         url,
        "description": description,
        "posted_at":   posted_at,
    }


def scrape(keywords: list[str] = None, max_per_keyword: int = 5) -> int:
    client = _get_client()

    # Merge CORE_KEYWORDS with any extra caller keywords, deduplicating
    seen: set[str] = set()
    all_kws: list[str] = []
    for kw in CORE_KEYWORDS + list(keywords or []):
        key = kw.lower().strip()
        if key not in seen:
            seen.add(key)
            all_kws.append(kw)

    saved = 0

    for i, kw in enumerate(all_kws):
        if i > 0:
            time.sleep(2)

        jobs = _fetch_jobs(client, kw, max_jobs=max_per_keyword)
        log.info("[Upwork] '%s' → %d jobs", kw, len(jobs))

        for item in jobs:
            parsed = _parse_job(item)
            if not parsed:
                continue

            lead_id = upsert_lead(
                source=SOURCE,
                title=parsed["title"],
                description=parsed["description"],
                url=parsed["url"],
                author=None,
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
