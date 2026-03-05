import database as db
import logging

log = logging.getLogger(__name__)

def reset_skipped_leads():
    db.init_db()
    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE leads SET status = 'new' WHERE status = 'skipped';")
            count = cur.rowcount
            log.info(f"Successfully reset {count} leads back to 'new'.")
    except Exception as e:
        log.error(f"Failed to reset leads: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    reset_skipped_leads()
