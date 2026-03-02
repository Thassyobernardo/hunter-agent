"""
RemoteOK scraper using the free public JSON API.

Endpoint: https://remoteok.com/api?tag=<tag>
Returns a JSON array. The first element is always a metadata object (not a
job), so we skip index 0. No API key, no authentication, no browser simulation
required — works reliably from any cloud server.

Tags queried cover automation, AI, dev, and no-code niches.
"""
import time
import random
import logging

import requests

from database import upsert_lead, save_proposal
from proposal_generator import process_lead

log = logging.getLogger(__name__)

SOURCE = "remoteok"
API_BASE = "https://remoteok.com/api"

# RemoteOK uses single-word or hyphenated tags
TAGS = [
    "automation",
    "python",
    "javascript",
    "api",
    "backend",
    "devops",
    "ai",
    "machine-learning",
    "data",
    "scraping",
    "chatbot",
    "integrations",
    "node",
    "django",
    "fastapi",
]

# RemoteOK requests a descriptive User-Agent
_HEADERS = {
    "User-Agent": "HunterAgent/1.0 (lead aggregator; contact via github)",
    "Accept": "application/json",
}


def _fetch_tag(tag: str) -> list[dict]:
    try:
        resp = requests.get(
            API_BASE,
            params={"tag": tag},
            headers=_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        # Index 0 is always the API metadata object, not a job
        return [item for item in data[1:] if isinstance(item, dict)]
    except Exception as e:
        log.warning("[RemoteOK] API error for tag '%s': %s", tag, e)
        return []


def scrape(keywords: list[str], max_per_tag: int = 15) -> int:
    # Derive extra tags from caller keywords (lowercase, spaces → hyphens)
    extra_tags = [kw.lower().replace(" ", "-") for kw in keywords]
    seen: set[str] = set()
    all_tags: list[str] = []
    for tag in TAGS + extra_tags:
        if tag not in seen:
            seen.add(tag)
            all_tags.append(tag)

    saved = 0

    for i, tag in enumerate(all_tags):
        if i > 0:
            time.sleep(random.uniform(2, 4))

        jobs = _fetch_tag(tag)
        if not jobs:
            continue

        log.info("[RemoteOK] tag='%s' → %d jobs", tag, len(jobs))

        for job in jobs[:max_per_tag]:
            title    = job.get("position") or job.get("title", "")
            url      = job.get("url") or job.get("apply_url", "")
            company  = job.get("company", "")
            desc_raw = job.get("description") or job.get("tags_str", "")
            if isinstance(desc_raw, list):
                desc_raw = " ".join(desc_raw)
            description = f"{company}: {desc_raw}".strip(": ") if company else desc_raw

            posted_at = job.get("date") or job.get("epoch")
            if isinstance(posted_at, (int, float)):
                try:
                    from datetime import datetime
                    posted_at = datetime.utcfromtimestamp(posted_at).isoformat()
                except Exception:
                    posted_at = None

            if not title or not url:
                continue

            lead_id = upsert_lead(
                source=SOURCE,
                title=title,
                description=description,
                url=url,
                author=company or None,
                posted_at=posted_at,
                keywords=tag,
            )

            if lead_id:
                try:
                    analysis, proposal = process_lead(
                        lead_id, SOURCE, title, description
                    )
                    save_proposal(lead_id, analysis, proposal)
                    saved += 1
                    log.info("[RemoteOK] Saved #%d: %s", lead_id, title[:60])
                except Exception as e:
                    log.warning("[RemoteOK] Proposal error #%d: %s", lead_id, e)

    return saved
