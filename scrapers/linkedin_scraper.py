"""
LinkedIn scraper via Apify Actor (linkedin-jobs-scraper).
No official API required. Falls back gracefully if APIFY_TOKEN not set.
"""
import os
import requests
from datetime import datetime
from database import upsert_lead, save_proposal
from proposal_generator import process_lead

SOURCE = "linkedin"
APIFY_ACTOR = "bebity/linkedin-jobs-scraper"
APIFY_BASE = "https://api.apify.com/v2"


def _run_actor(keyword: str, max_items: int = 15) -> list[dict]:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        return []

    run_url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"
    payload = {
        "title": keyword,
        "location": "Worldwide",
        "rows": max_items,
        "contractType": "freelance",
    }

    try:
        resp = requests.post(
            run_url,
            json=payload,
            params={"token": token},
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[LinkedIn] Apify error for '{keyword}': {e}")
        return []


def scrape(keywords: list[str], max_per_keyword: int = 15) -> int:
    if not os.getenv("APIFY_TOKEN"):
        print("[LinkedIn] APIFY_TOKEN not set, skipping.")
        return 0

    saved = 0
    for kw in keywords[:3]:  # limit Apify calls
        jobs = _run_actor(kw, max_per_keyword)

        for job in jobs:
            title = job.get("title", "No title")
            company = job.get("companyName", "")
            description = job.get("description", "") or job.get("descriptionText", "")
            url = job.get("jobUrl") or job.get("url", "")
            posted = job.get("postedAt") or job.get("publishedAt", "")

            if not url:
                continue

            author = company or None
            full_desc = f"{description}"[:4000]

            lead_id = upsert_lead(
                source=SOURCE,
                title=title,
                description=full_desc,
                url=url,
                author=author,
                posted_at=posted,
                keywords=kw,
            )

            if lead_id:
                try:
                    analysis, proposal = process_lead(
                        lead_id, SOURCE, title, full_desc
                    )
                    save_proposal(lead_id, analysis, proposal)
                    saved += 1
                    print(f"[LinkedIn] Saved lead #{lead_id}: {title[:60]}")
                except Exception as e:
                    print(f"[LinkedIn] Proposal error for #{lead_id}: {e}")

    return saved
