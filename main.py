import os
import json
import logging
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime
import time
import threading
from flask import Flask, render_template, jsonify, request, abort, send_file
from werkzeug.exceptions import HTTPException
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import database as db
import qualifier
import builder
from scrapers import upwork_scraper
import sales_agent
import manager_agent
import support_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "hunter-agent-secret")

# Initialise the DB schema on the first non-health request so Flask can
# bind and respond to /health immediately without waiting for PostgreSQL.
@app.before_request
def ensure_db():
    if request.path == "/health":
        return
    try:
        db.init_db()
    except Exception as e:
        log.error(f"Database unavailable: {e}")
        return jsonify({"error": "Database unavailable", "detail": str(e)}), 503


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    log.error("Unhandled exception", exc_info=True)
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500

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
    raw = os.getenv(
        "KEYWORDS",
        "automation,chatbot,zapier,n8n,crm,whatsapp bot,workflow,ai agent",
    )
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

    log.info(f"Scan complete — {total} new leads saved")
    return total


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/")
@app.route("/dashboard")
def dashboard():
    try:
        stats = db.get_stats()
        leads = db.get_leads(limit=50)
    except Exception as e:
        log.error(f"Dashboard DB error: {e}")
        return jsonify({"error": "Database error", "detail": str(e)}), 500
    return render_template(
        "dashboard.html",
        stats=stats,
        leads=leads,
        keywords=get_keywords(),
        scan_interval=get_scan_interval(),
    )


@app.route("/api/leads")
def api_leads():
    try:
        status = request.args.get("status")
        source = request.args.get("source")
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = int(request.args.get("offset", 0))
        leads = db.get_leads(status=status, source=source, limit=limit, offset=offset)
        return jsonify(leads)
    except Exception as e:
        log.error(f"api_leads error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/leads/<int:lead_id>")
def api_lead(lead_id):
    try:
        lead = db.get_lead(lead_id)
    except Exception as e:
        log.error(f"api_lead DB error: {e}")
        return jsonify({"error": str(e)}), 500
    if not lead:
        abort(404)

    # Parse JSON fields for nicer output
    for field in ("analysis", "proposal", "qualification"):
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
    try:
        return jsonify(db.get_stats())
    except Exception as e:
        log.error(f"api_stats error: {e}")
        return jsonify({"error": str(e)}), 500


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


@app.route("/api/qualify", methods=["POST"])
def api_qualify():
    """Qualify all leads with status 'new'."""
    log.info("Bulk qualification triggered via API")
    try:
        count = qualifier.run_qualification()
        return jsonify({"ok": True, "qualified": count})
    except Exception as e:
        log.error(f"Bulk qualification failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/leads/<int:lead_id>/qualify", methods=["POST"])
def api_qualify_lead(lead_id):
    """Qualify a single lead by ID."""
    try:
        result = qualifier.qualify_single(lead_id)
        return jsonify({"ok": True, "qualification": result})
    except ValueError as e:
        abort(404, str(e))
    except Exception as e:
        log.error(f"Qualification failed for lead {lead_id}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/leads/<int:lead_id>/build", methods=["POST"])
def api_build_lead(lead_id):
    """Generate a production-ready code project and package it as a ZIP."""
    try:
        zip_path = builder.build_lead(lead_id)
        return jsonify({"ok": True, "path": zip_path})
    except ValueError as e:
        abort(404, str(e))
    except Exception as e:
        log.error(f"Build failed for lead {lead_id}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/leads/<int:lead_id>/download")
def api_download_lead(lead_id):
    """Download the ZIP deliverable for a built lead."""
    try:
        lead = db.get_lead(lead_id)
    except Exception as e:
        log.error(f"api_download_lead DB error: {e}")
        return jsonify({"error": str(e)}), 500
    if not lead:
        abort(404)
    path = lead.get("deliverable_path")
    if not path or not os.path.exists(path):
        abort(404, "Build file not found. Run the builder first.")
    return send_file(
        path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=os.path.basename(path),
    )


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
        replace_existing=True,
        coalesce=True,
    )
    scheduler.add_job(
        manager_agent.run_manager_cycle,
        trigger=IntervalTrigger(hours=3),
        id="manager",
        replace_existing=True,
        coalesce=True,
    )
    scheduler.add_job(
        sales_agent.run_sales_cycle,
        trigger=IntervalTrigger(hours=1),
        id="sales",
        replace_existing=True,
        coalesce=True,
    )
    scheduler.add_job(
        support_agent.run_support_cycle,
        trigger=IntervalTrigger(hours=1),
        id="support",
        replace_existing=True,
        coalesce=True,
    )
    scheduler.start()
    log.info(f"Scheduler started — scanning every {interval_hours}h")
    
    # Run the manager and sales cycles once on startup for testing
    def delayed_startup_cycle():
        log.info("Waiting 10 seconds before running initial startup cycles...")
        time.sleep(10)

        log.info("Running startup scan to fetch fresh leads...")
        try:
            run_scan()
        except Exception as e:
            log.error(f"Startup scan failed: {e}")

        log.info("Running manager cycle to build leads...")
        manager_agent.run_manager_cycle()
        
        log.info("Manager cycle finished. Waiting 60 seconds before running sales cycle to ensure all ZIPs are written...")
        time.sleep(60)
        
        log.info("Running sales cycle to dispatch emails...")
        sales_agent.run_sales_cycle()

    threading.Thread(target=delayed_startup_cycle, daemon=True).start()
    
    return scheduler


# Attempt DB init at startup so tables exist before the first request.
# If the DB isn't reachable yet, before_request will retry on each request.
try:
    db.init_db()
    log.info("Database initialised at startup")
except Exception as e:
    log.warning(f"Database not reachable at startup (will retry): {e}")

# Start the scheduler; the first scan fires after SCAN_INTERVAL_HOURS.
_scheduler = start_scheduler()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
