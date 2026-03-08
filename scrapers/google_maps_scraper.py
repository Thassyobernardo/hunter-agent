"""
Google Maps scraper via Apify Actor (jan.mraz/google-maps-scraper).
Targets local businesses like dental clinics and real estate agencies in Luxembourg.
"""
import os
import time
import logging
import config
from apify_client import ApifyClient
from database import save_lead, log_action

log = logging.getLogger(__name__)

SOURCE = "google_maps"
ACTOR = "compass/crawler-google-places"

def _get_client() -> ApifyClient:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        raise RuntimeError("APIFY_TOKEN is not set.")
    return ApifyClient(token)

def scrape(queries: list[str] = None, max_results: int = 10) -> int:
    try:
        client = _get_client()
    except Exception as e:
        log.error(f"[GoogleMaps] {e}")
        return 0

    # If no queries provided, build from config
    search_queries = queries
    if not search_queries:
        search_queries = []
        # Target sectors in Luxembourg specifically as requested
        for sector in config.TARGET_SECTORS:
            search_queries.append(f"{sector} Luxembourg")

    saved = 0
    for query in search_queries:
        log.info(f"[GoogleMaps] Searching for: {query}")
        try:
            run_input = {
                "queries": [query],
                "maxResults": max_results,
                "language": "fr",
                "deeperCity": True,
            }
            run = client.actor(ACTOR).call(run_input=run_input, timeout_secs=300)
            items = client.dataset(run["defaultDatasetId"]).list_items().items
            
            for item in items:
                name = item.get("title", "").strip()
                url = item.get("website") or item.get("url", "").strip()
                if not name:
                    continue
                
                address = item.get("address", "Luxembourg")
                category = item.get("categoryName", "Business")
                phone = item.get("phone", "N/A")
                
                # New SQLAlchemy-based schema uses save_lead(name, email, phone, sector, location, score, source, notes)
                success = save_lead(
                    name=name,
                    email="N/A", # Google Maps often lacks direct emails
                    phone=phone,
                    sector=category,
                    location=address,
                    score=50, # Default score
                    source=SOURCE,
                    notes=f"Found via Google Maps search for {query}. Web: {url}"
                )

                if success:
                    saved += 1
                    log.info(f"[GoogleMaps] Saved lead: {name[:60]}")

        except Exception as e:
            log.error(f"[GoogleMaps] Actor run failed for '{query}': {e}")
        
        # Delay to avoid hammering the API
        time.sleep(2)

    if saved > 0:
        log_action("google_maps_scan", f"Found {saved} leads for {search_queries}")
        
    return saved
