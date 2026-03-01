"""
Twitter/X scraper via Apify Actor (twitter-scraper).
Requires APIFY_TOKEN env var.
Falls back gracefully if token not set.
"""
import os
import requests
from datetime import datetime
from database import upsert_lead, save_proposal
from proposal_generator import process_lead

SOURCE = "twitter"
APIFY_ACTOR = "apidojo/tweet-scraper"
APIFY_BASE = "https://api.apify.com/v2"


def _run_actor(query: str, max_items: int = 20) -> list[dict]:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        return []

    run_url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"
    payload = {
        "searchTerms": [query],
        "maxItems": max_items,
        "queryType": "Latest",
        "lang": "en",
    }

    try:
        resp = requests.post(
            run_url,
            json=payload,
            params={"token": token},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[Twitter] Apify error for '{query}': {e}")
        return []


def _build_query(keywords: list[str]) -> str:
    kw_part = " OR ".join(f'"{k}"' for k in keywords[:5])
    hiring_terms = "(hiring OR \"looking for\" OR \"need a dev\" OR \"need developer\")"
    return f"({kw_part}) {hiring_terms} -is:retweet lang:en"


def scrape(keywords: list[str], max_items: int = 20) -> int:
    if not os.getenv("APIFY_TOKEN"):
        print("[Twitter] APIFY_TOKEN not set, skipping.")
        return 0

    query = _build_query(keywords)
    tweets = _run_actor(query, max_items)
    saved = 0

    for tweet in tweets:
        text = tweet.get("text") or tweet.get("full_text", "")
        tweet_id = tweet.get("id") or tweet.get("id_str", "")
        author = tweet.get("author", {})
        username = author.get("userName") or author.get("screen_name", "unknown")
        created = tweet.get("createdAt") or tweet.get("created_at", "")

        url = f"https://twitter.com/{username}/status/{tweet_id}"
        title = text[:120] + ("..." if len(text) > 120 else "")

        lead_id = upsert_lead(
            source=SOURCE,
            title=title,
            description=text,
            url=url,
            author=username,
            posted_at=created,
            keywords=", ".join(keywords),
        )

        if lead_id:
            try:
                analysis, proposal = process_lead(
                    lead_id, SOURCE, title, text
                )
                save_proposal(lead_id, analysis, proposal)
                saved += 1
                print(f"[Twitter] Saved lead #{lead_id}: {title[:60]}")
            except Exception as e:
                print(f"[Twitter] Proposal error for #{lead_id}: {e}")

    return saved
