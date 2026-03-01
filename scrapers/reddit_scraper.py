"""
Reddit scraper via PRAW.
Searches subreddits for posts where people need help (hiring posts, etc.).
"""
import os
import praw
from datetime import datetime
from database import upsert_lead, save_proposal
from proposal_generator import process_lead

SOURCE = "reddit"

SUBREDDITS = [
    "forhire",
    "slavelabour",
    "entrepreneur",
    "startups",
    "smallbusiness",
    "webdev",
    "learnprogramming",
]

HIRING_FLAIRS = {"hiring", "[for hire]", "hiring - fixed", "job offer"}


def _get_client() -> praw.Reddit:
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent="HunterAgent/1.0 (lead scraper)",
    )


def _is_hiring(post) -> bool:
    flair = (post.link_flair_text or "").lower()
    title_lower = post.title.lower()
    return (
        any(f in flair for f in HIRING_FLAIRS)
        or "[hiring]" in title_lower
        or "looking for" in title_lower
    )


def scrape(keywords: list[str], max_per_sub: int = 25) -> int:
    try:
        reddit = _get_client()
    except Exception as e:
        print(f"[Reddit] Auth failed: {e}")
        return 0

    saved = 0
    for sub_name in SUBREDDITS:
        try:
            sub = reddit.subreddit(sub_name)
            posts = list(sub.new(limit=max_per_sub))
        except Exception as e:
            print(f"[Reddit] Failed r/{sub_name}: {e}")
            continue

        for post in posts:
            title_lower = post.title.lower()
            desc_lower = (post.selftext or "").lower()
            full_text = title_lower + " " + desc_lower

            # Match on keywords OR hiring indicators
            keyword_match = any(kw.lower() in full_text for kw in keywords)
            hiring = _is_hiring(post)

            if not (keyword_match or hiring):
                continue

            posted = datetime.utcfromtimestamp(post.created_utc).isoformat()
            url = f"https://reddit.com{post.permalink}"
            description = post.selftext[:4000] if post.selftext else post.title

            lead_id = upsert_lead(
                source=SOURCE,
                title=post.title,
                description=description,
                url=url,
                author=str(post.author) if post.author else None,
                posted_at=posted,
                keywords=", ".join(keywords),
            )

            if lead_id:
                try:
                    analysis, proposal = process_lead(
                        lead_id, SOURCE, post.title, description
                    )
                    save_proposal(lead_id, analysis, proposal)
                    saved += 1
                    print(f"[Reddit] Saved lead #{lead_id}: {post.title[:60]}")
                except Exception as e:
                    print(f"[Reddit] Proposal error for #{lead_id}: {e}")

    return saved
