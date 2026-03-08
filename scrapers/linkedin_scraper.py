"""
LinkedIn scraper via Apify Actor (linkedin-jobs-scraper).
Targets dental clinics and real estate opportunities in Luxembourg.
"""
import os
import requests
import logging
from database import save_lead, log_action
import config

log = logging.getLogger(__name__)

SOURCE = "linkedin"
APIFY_ACTOR = "bebity/linkedin-jobs-scraper"
APIFY_BASE = "https://api.apify.com/v2"

def _run_actor(keyword: str, location: str, max_items: int = 10) -> list[dict]:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        return []

    run_url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"
    payload = {
        "title": keyword,
        "location": location,
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
        log.error(f"[LinkedIn] Apify error for '{keyword}' in '{location}': {e}")
        return []

def scrape(keywords: list[str] = None, max_per_keyword: int = 10) -> int:
    if not os.getenv("APIFY_TOKEN"):
        log.warning("[LinkedIn] APIFY_TOKEN not set, skipping.")
        return 0

    # Use specific Luxembourg targeting for the test
    search_keywords = keywords if keywords else config.TARGET_SECTORS
    location = "Luxembourg"

    saved = 0
    for kw in search_keywords:
        log.info(f"[LinkedIn] Searching '{kw}' in {location}...")
        jobs = _run_actor(kw, location, max_per_keyword)

        for job in jobs:
            title = job.get("title", "No title")
            company = job.get("companyName", "Unknown")
            url = job.get("jobUrl") or job.get("url", "")
            
            if not url:
                continue

            # New SQLAlchemy-based schema uses save_lead(name, email, phone, sector, location, score, source, notes)
            success = save_lead(
                name=company,
                email="N/A",
                phone="N/A",
                sector=kw,
                location=location,
                score=70, # Higher score for LinkedIn jobs
                source=SOURCE,
                notes=f"Job Title: {title}. Link: {url}"
            )

            if success:
                saved += 1
                log.info(f"[LinkedIn] Saved lead from {company}: {title[:60]}")

    if saved > 0:
        log_action("linkedin_scan", f"Found {saved} leads in Luxembourg")
        
    return saved
