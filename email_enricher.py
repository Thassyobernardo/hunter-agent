import re
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import database as db

log = logging.getLogger(__name__)

# Regex for email extraction
EMAIL_REGEX = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

# Emails to skip
SKIP_KEYWORDS = ["noreply", "no-reply", "example", "test", "info@google"]

def is_valid_email(email):
    """Checks if email is valid and doesn't contain skip keywords."""
    email = email.lower()
    if any(kw in email for kw in SKIP_KEYWORDS):
        return False
    return True

def extract_emails_from_url(url):
    """Visits a URL and extracts all unique valid emails."""
    try:
        log.info(f"Visiting {url}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        if response.status_code != 200:
            return set()
        
        # Search in text
        html = response.text
        emails = set(re.findall(EMAIL_REGEX, html))
        
        # Clean and filter
        valid_emails = {e for e in emails if is_valid_email(e)}
        return valid_emails
    except Exception as e:
        log.warning(f"Failed to scrape {url}: {e}")
        return set()

def get_website_from_notes(notes):
    """Extracts website URL from the notes field."""
    if not notes:
        return None
    # Look for Website: URL patterns we saved earlier
    match = re.search(r'Website:\s*(https?://[^\s|]+)', notes)
    if match:
        return match.group(1)
    return None

def enrich_lead(lead):
    """Enriches a single lead by visiting its website and contact pages."""
    website = get_website_from_notes(lead.get("notes"))
    if not website:
        return False

    found_emails = extract_emails_from_url(website)

    # If no email found on homepage, check /contact and /about
    if not found_emails:
        for path in ["/contact", "/about", "/contact-us", "/a-propos"]:
            contact_url = urljoin(website, path)
            # Only check if it's the same domain
            if urlparse(contact_url).netloc == urlparse(website).netloc:
                found_emails.update(extract_emails_from_url(contact_url))
            if found_emails:
                break

    if found_emails:
        # Take the first one, priority to those typically checked by human
        best_email = sorted(list(found_emails))[0]
        log.info(f"Found email for {lead['name']}: {best_email}")
        
        # Update database: update_email(lead_id, email)
        # We need to add this function to database.py or use a raw update
        try:
            engine = db.get_engine()
            with engine.connect() as conn:
                from sqlalchemy import text
                conn.execute(text("UPDATE leads SET email = :email WHERE id = :id"),
                            {"email": best_email, "id": lead["id"]})
                conn.commit()
            return True
        except Exception as e:
            log.error(f"Failed to update email for lead {lead['id']}: {e}")
    
    return False

def run_enrichment():
    """Runs enrichment for all leads with email='N/A'."""
    try:
        engine = db.get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("SELECT * FROM leads WHERE email = 'N/A' OR email IS NULL"))
            leads = [dict(r._mapping) for r in result.fetchall()]
    except Exception as e:
        log.error(f"Failed to fetch leads for enrichment: {e}")
        return 0

    log.info(f"Starting enrichment for {len(leads)} leads")
    enriched_count = 0
    for lead in leads:
        if enrich_lead(lead):
            enriched_count += 1
            
    return enriched_count

if __name__ == "__main__":
    count = run_enrichment()
    print(f"Enrichment complete. Found {count} emails.")
