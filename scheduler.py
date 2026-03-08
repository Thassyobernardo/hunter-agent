import os
import pytz
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine, text
import config

# ----------------------------------------------------------------------
# Configuration – Railway environment variables
# ----------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Database connection (Railway provides DATABASE_URL)
# We delay engine creation or wrap it to avoid crash if env is missing
def get_engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    return create_engine(url)

def send_telegram(message: str) -> None:
    """Send a message via the Telegram Bot API."""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.get(
            f"https://api.telegram.org/bot{token}/sendMessage",
            params={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        ).raise_for_status()
    except Exception:
        pass

def _fetch_daily_stats() -> dict:
    """Query the PostgreSQL DB for today’s lead/email/reply counts."""
    engine = get_engine()
    if not engine:
        return {"leads": 0, "emails": 0, "replies": 0}
        
    try:
        with engine.connect() as conn:
            leads_cnt = conn.execute(
                text("SELECT COUNT(*) FROM leads WHERE created_at >= CURRENT_DATE")
            ).scalar()
            emails_cnt = conn.execute(
                text("SELECT COUNT(*) FROM emails_sent WHERE sent_at >= CURRENT_DATE")
            ).scalar()
            replies_cnt = conn.execute(
                text(
                    "SELECT COUNT(*) FROM emails_sent "
                    "WHERE opened = true AND replied = true "
                    "AND sent_at >= CURRENT_DATE"
                )
            ).scalar()
        return {"leads": leads_cnt, "emails": emails_cnt, "replies": replies_cnt}
    except Exception:
        return {"leads": 0, "emails": 0, "replies": 0}

def daily_telegram_report() -> None:
    """Compose the daily report and send it via Telegram."""
    stats = _fetch_daily_stats()
    
    header = f"📊 <b>{config.AGENCY_NAME} — Relatório Diário</b>"
    if config.OUTREACH_LANGUAGE == "fr":
        header = f"📊 <b>{config.AGENCY_NAME} — Rapport Quotidien</b>"
    
    message = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🔍 Leads trouvés: {stats['leads']}\n"
        f"📨 Emails envoyés: {stats['emails']}\n"
        f"💬 Réponses reçues: {stats['replies']}\n"
        f"📅 Système actif (Luxembourg)"
    )
    send_telegram(message)

def init_scheduler(app):
    """Start a background APScheduler that runs the report each day at 19:00 Luxembourg time."""
    tz = pytz.timezone("Europe/Luxembourg")
    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(
        daily_telegram_report,
        trigger="cron",
        hour=19,
        minute=0,
        id="telegram_daily_report",
        replace_existing=True,
    )
    scheduler.start()

    @app.teardown_appcontext
    def shutdown_scheduler(exception=None):
        if scheduler.running:
            scheduler.shutdown()
