import os
import logging
from sqlalchemy import create_engine, text

log = logging.getLogger(__name__)

def get_engine():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL not set")
    # SQLAlchemy requires postgresql:// not postgres://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})

def init_db():
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255),
                email VARCHAR(255),
                phone VARCHAR(50),
                sector VARCHAR(100),
                location VARCHAR(100),
                score INTEGER DEFAULT 0,
                status VARCHAR(50) DEFAULT 'novo',
                source VARCHAR(100),
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS emails_sent (
                id SERIAL PRIMARY KEY,
                lead_id INTEGER,
                subject VARCHAR(255),
                body TEXT,
                sent_at TIMESTAMP DEFAULT NOW(),
                opened BOOLEAN DEFAULT FALSE,
                replied BOOLEAN DEFAULT FALSE
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_logs (
                id SERIAL PRIMARY KEY,
                action VARCHAR(100),
                details TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS security_log (
                id SERIAL PRIMARY KEY,
                threat_type VARCHAR(50),
                source TEXT,
                content_preview TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.commit()
    log.info("Database tables ready")

def get_stats():
    try:
        engine = get_engine()
        with engine.connect() as conn:
            leads = conn.execute(text("SELECT COUNT(*) FROM leads")).scalar()
            emails = conn.execute(text("SELECT COUNT(*) FROM emails_sent")).scalar()
            logs = conn.execute(text("SELECT COUNT(*) FROM agent_logs WHERE created_at > NOW() - INTERVAL '24 hours'")).scalar()
            return {"leads": leads, "emails_sent": emails, "scans_today": logs}
    except Exception as e:
        log.error(f"get_stats error: {e}")
        return {"leads": 0, "emails_sent": 0, "scans_today": 0}

def get_leads(limit=50):
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM leads ORDER BY created_at DESC LIMIT :limit"), {"limit": limit})
            rows = result.fetchall()
            return [dict(r._mapping) for r in rows]
    except Exception as e:
        log.error(f"get_leads error: {e}")
        return []

def save_lead(name, email, phone, sector, location, score, source, notes=""):
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO leads (name, email, phone, sector, location, score, source, notes)
                VALUES (:name, :email, :phone, :sector, :location, :score, :source, :notes)
            """), {
                "name": name, "email": email, "phone": phone,
                "sector": sector, "location": location,
                "score": score, "source": source, "notes": notes
            })
            conn.commit()
        return True
    except Exception as e:
        log.error(f"save_lead error: {e}")
        return False

def log_action(action, details=""):
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO agent_logs (action, details) VALUES (:action, :details)"),
                        {"action": action, "details": details})
            conn.commit()
    except Exception as e:
        log.error(f"log_action error: {e}")
