import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

def _db_path() -> str:
    path = os.getenv("DB_PATH", "hunter.db")
    # Ensure the parent directory exists so SQLite can create the file.
    # This prevents a crash on Railway when DB_PATH points to a dir
    # (e.g. /data/hunter.db) that hasn't been mounted yet.
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


@contextmanager
def get_conn():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source      TEXT NOT NULL,
                title       TEXT NOT NULL,
                description TEXT,
                url         TEXT UNIQUE,
                author      TEXT,
                posted_at   TEXT,
                keywords    TEXT,
                analysis    TEXT,
                proposal    TEXT,
                status      TEXT NOT NULL DEFAULT 'new',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_leads_status  ON leads(status);
            CREATE INDEX IF NOT EXISTS idx_leads_source  ON leads(source);
            CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at DESC);
        """)


def upsert_lead(source: str, title: str, description: str,
                url: str, author: str = None, posted_at: str = None,
                keywords: str = None) -> int | None:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, status FROM leads WHERE url = ?", (url,)
        ).fetchone()

        if existing:
            return None  # already exists

        cur = conn.execute(
            """INSERT INTO leads
               (source, title, description, url, author, posted_at, keywords,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
            (source, title, description, url, author, posted_at, keywords, now, now)
        )
        return cur.lastrowid


def save_proposal(lead_id: int, analysis: str, proposal: str):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET analysis=?, proposal=?, updated_at=? WHERE id=?",
            (analysis, proposal, now, lead_id)
        )


def update_status(lead_id: int, status: str):
    allowed = {"new", "sent", "won", "skipped"}
    if status not in allowed:
        raise ValueError(f"Invalid status: {status}")
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET status=?, updated_at=? WHERE id=?",
            (status, now, lead_id)
        )


def get_leads(status: str = None, source: str = None,
              limit: int = 100, offset: int = 0) -> list[dict]:
    query = "SELECT * FROM leads WHERE 1=1"
    params: list = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if source:
        query += " AND source = ?"
        params.append(source)

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_lead(lead_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    return dict(row) if row else None


def get_stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        by_status = {
            r["status"]: r["cnt"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM leads GROUP BY status"
            ).fetchall()
        }
        by_source = {
            r["source"]: r["cnt"]
            for r in conn.execute(
                "SELECT source, COUNT(*) AS cnt FROM leads GROUP BY source"
            ).fetchall()
        }
        recent_24h = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE created_at >= datetime('now','-1 day')"
        ).fetchone()[0]

    return {
        "total": total,
        "by_status": by_status,
        "by_source": by_source,
        "recent_24h": recent_24h,
    }
