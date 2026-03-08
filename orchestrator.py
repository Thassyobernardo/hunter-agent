import logging
from scrapers import google_maps_scraper, linkedin_scraper
from database import log_action, get_leads

log = logging.getLogger(__name__)

def run_full_cycle():
    """
    Simplified Orchestrator for version 1.0.2.
    Triggers active scrapers and logs results.
    """
    log.info("--- [Orchestrator] Starting B2B Hunter Cycle (Luxembourg) ---")
    total_new = 0
    
    # 1. Google Maps Scan
    try:
        log.info("[Orchestrator] Triggering Google Maps Scraper...")
        g_count = google_maps_scraper.scrape(max_results=5)
        log.info(f"[Orchestrator] Google Maps found {g_count} new leads.")
        total_new += g_count
    except Exception as e:
        log.error(f"[Orchestrator] Google Maps failed: {e}")
    
    # 2. LinkedIn Scan
    try:
        log.info("[Orchestrator] Triggering LinkedIn Scraper...")
        l_count = linkedin_scraper.scrape(max_per_keyword=5)
        log.info(f"[Orchestrator] LinkedIn found {l_count} new leads.")
        total_new += l_count
    except Exception as e:
        log.error(f"[Orchestrator] LinkedIn failed: {e}")
    
    log.info(f"--- [Orchestrator] Cycle Complete. Total new leads: {total_new} ---")
    log_action("orchestrator_cycle", f"Found {total_new} new leads total across all platforms.")
    
    return total_new

if __name__ == "__main__":
    # Test run
    count = run_full_cycle()
    print(f"Test scan complete. Found {count} leads.")
    
    print("\n--- Top 5 Leads ---")
    leads = get_leads(limit=5)
    for i, lead in enumerate(leads, 1):
        print(f"{i}. {lead['name']} | {lead['sector']} | {lead['location']} | {lead['source']}")
