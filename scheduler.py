import os
import logging
from datetime import datetime

log = logging.getLogger(__name__)

def send_daily_report():
    try:
        import requests
        import database as db

        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return

        stats = db.get_stats()
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

        msg = (
            f"🦅 *Claw Agency — Relatório Diário*\n\n"
            f"📊 *Leads capturados:* {stats['leads']}\n"
            f"📧 *Emails enviados:* {stats['emails_sent']}\n"
            f"🔍 *Scans hoje:* {stats['scans_today']}\n\n"
            f"🕐 {now} UTC\n"
            f"🌍 Luxembourg B2B Hunter"
        )

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
        log.info("Daily Telegram report sent")
    except Exception as e:
        log.error(f"Daily report failed: {e}")

def init_scheduler(app):
    from apscheduler.schedulers.background import BackgroundScheduler
    import pytz

    tz = pytz.timezone("Europe/Luxembourg")
    scheduler = BackgroundScheduler(timezone=tz)

    # Daily report at 19:00 Luxembourg time
    scheduler.add_job(
        send_daily_report,
        trigger="cron",
        hour=19,
        minute=0,
        id="daily_report"
    )

    scheduler.start()
    log.info("Scheduler started — daily report at 19:00 Luxembourg time")
    return scheduler
