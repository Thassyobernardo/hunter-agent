"""
Upwork scraper via Apify actor flash_mage/upwork.

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

import requests

from database import upsert_lead, save_proposal
from proposal_generator import process_lead

log = logging.getLogger(__name__)

SOURCE = "upwork"
ACTOR = "flash_mage~upwork"
APIFY_BASE = "https://api.apify.com/v2/acts"

CORE_KEYWORDS = [
    "automation",
    "chatbot",
    "zapier",
    "n8n",
    "crm",
    "whatsapp bot",
    "workflow",
    "ai agent",
    "make.com",
    "email automation",
]


def _get_token() -> str:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        raise RuntimeError("APIFY_TOKEN is not set.")
    return token


def _fetch_jobs(keyword: str, max_jobs: int = 5) -> list[dict]:
    url = f"{APIFY_BASE}/{ACTOR}/run-sync-get-dataset-items"
    try:
        resp = requests.post(
            url,
            params={"token": _get_token(), "timeout": 60},
            json={"query": [keyword], "maxJobs": max_jobs},
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
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

        jobs = _fetch_jobs(kw, max_jobs=max_per_keyword)
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
