import os
import json
import logging
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime
from flask import Flask, render_template, jsonify, request, abort
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import database as db
from scrapers import upwork_scraper, google_scraper, twitter_scraper, linkedin_scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "hunter-agent-secret")

# Jinja2 filter: parse JSON strings in templates
@app.template_filter("fromjson")
def fromjson_filter(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}

# ── Config ────────────────────────────────────────────────────────────────────

def get_keywords() -> list[str]:
    raw = os.getenv("KEYWORDS", "python developer,automation,web scraping,fastapi,flask")
    return [k.strip() for k in raw.split(",") if k.strip()]


def get_scan_interval() -> int:
    return int(os.getenv("SCAN_INTERVAL_HOURS", "3"))


# ── Scan job ─────────────────────────────────────────────────────────────────

def run_scan():
    keywords = get_keywords()
    log.info(f"Starting scan — keywords: {keywords}")
    total = 0

    try:
        n = upwork_scraper.scrape(keywords)
        log.info(f"Upwork: +{n} leads")
        total += n
    except Exception as e:
        log.error(f"Upwork scraper error: {e}")

    try:
        n = google_scraper.scrape(keywords)
        log.info(f"Google: +{n} leads")
        total += n
    except Exception as e:
        log.error(f"Google scraper error: {e}")

    try:
        n = twitter_scraper.scrape(keywords)
        log.info(f"Twitter: +{n} leads")
        total += n
    except Exception as e:
        log.error(f"Twitter scraper error: {e}")

    try:
        n = linkedin_scraper.scrape(keywords)
        log.info(f"LinkedIn: +{n} leads")
        total += n
    except Exception as e:
        log.error(f"LinkedIn scraper error: {e}")

    log.info(f"Scan complete — {total} new leads saved")
    return total


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    stats = db.get_stats()
    leads = db.get_leads(limit=50)
    return render_template(
        "dashboard.html",
        stats=stats,
        leads=leads,
        keywords=get_keywords(),
        scan_interval=get_scan_interval(),
    )


@app.route("/api/leads")
def api_leads():
    status = request.args.get("status")
    source = request.args.get("source")
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = int(request.args.get("offset", 0))
    leads = db.get_leads(status=status, source=source, limit=limit, offset=offset)
    return jsonify(leads)


@app.route("/api/leads/<int:lead_id>")
def api_lead(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        abort(404)

    # Parse JSON fields for nicer output
    for field in ("analysis", "proposal"):
        if lead.get(field):
            try:
                lead[field] = json.loads(lead[field])
            except Exception:
                pass

    return jsonify(lead)


@app.route("/api/leads/<int:lead_id>/status", methods=["PATCH"])
def api_update_status(lead_id):
    data = request.get_json(force=True)
    status = data.get("status")
    if not status:
        abort(400, "Missing status")
    try:
        db.update_status(lead_id, status)
    except ValueError as e:
        abort(400, str(e))
    return jsonify({"ok": True, "id": lead_id, "status": status})


@app.route("/api/stats")
def api_stats():
    return jsonify(db.get_stats())


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """Trigger a manual scan."""
    log.info("Manual scan triggered via API")
    try:
        total = run_scan()
        return jsonify({"ok": True, "new_leads": total})
    except Exception as e:
        log.error(f"Manual scan failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


# ── Startup ───────────────────────────────────────────────────────────────────

def start_scheduler():
    interval_hours = get_scan_interval()
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        run_scan,
        trigger=IntervalTrigger(hours=interval_hours),
        id="scan",
        next_run_time=datetime.now(),  # run immediately on start
        replace_existing=True,
        coalesce=True,
    )
    scheduler.start()
    log.info(f"Scheduler started — scanning every {interval_hours}h")
    return scheduler


# Always init DB and start scheduler (works with both gunicorn and direct run)
db.init_db()
_scheduler = start_scheduler()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
