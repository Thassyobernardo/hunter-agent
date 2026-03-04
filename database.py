import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from contextlib import contextmanager

_initialized = False


def _get_dsn() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Add the Railway PostgreSQL service and link it to this app."
        )
    # Railway (and some other providers) emit postgres:// — psycopg2 requires
    # the postgresql:// scheme for URI connections.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


@contextmanager
def get_conn():
    conn = psycopg2.connect(_get_dsn())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    global _initialized
    if _initialized:
        return
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id               SERIAL PRIMARY KEY,
                source           TEXT NOT NULL,
                title            TEXT NOT NULL,
                description      TEXT,
                url              TEXT UNIQUE,
                author           TEXT,
                posted_at        TEXT,
                keywords         TEXT,
                analysis         TEXT,
                proposal         TEXT,
                qualification    TEXT,
                deliverable_path TEXT,
                status           TEXT NOT NULL DEFAULT 'new',
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL
            )
        """)

        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_status  ON leads(status)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_source  ON leads(source)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at DESC)"
        )

        # Safe migration: add columns that may not exist in older schemas
        for col, definition in [
            ("qualification",    "TEXT"),
            ("deliverable_path", "TEXT"),
        ]:
            cur.execute(
                f"ALTER TABLE leads ADD COLUMN IF NOT EXISTS {col} {definition}"
            )
    _initialized = True


def upsert_lead(source: str, title: str, description: str,
                url: str, author: str = None, posted_at: str = None,
                keywords: str = None) -> int | None:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM leads WHERE url = %s", (url,))
        if cur.fetchone():
            return None  # already exists

        cur.execute(
            """
            INSERT INTO leads
                (source, title, description, url, author, posted_at, keywords,
                 status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'new', %s, %s)
            RETURNING id
            """,
            (source, title, description, url, author, posted_at, keywords, now, now),
        )
        return cur.fetchone()[0]


def save_proposal(lead_id: int, analysis: str, proposal: str):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE leads SET analysis=%s, proposal=%s, updated_at=%s WHERE id=%s",
            (analysis, proposal, now, lead_id),
        )


def save_qualification(lead_id: int, qualification: str):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE leads SET qualification=%s, updated_at=%s WHERE id=%s",
            (qualification, now, lead_id),
        )


def save_deliverable_path(lead_id: int, path: str):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE leads SET deliverable_path=%s, updated_at=%s WHERE id=%s",
            (path, now, lead_id),
        )


def update_status(lead_id: int, status: str):
    allowed = {"new", "sent", "won", "skipped", "qualified", "skip", "built", "paid", "delivered"}
    if status not in allowed:
        raise ValueError(f"Invalid status: {status}")
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE leads SET status=%s, updated_at=%s WHERE id=%s",
            (status, now, lead_id),
        )


def get_leads(status: str = None, source: str = None,
              limit: int = 100, offset: int = 0) -> list[dict]:
    query = "SELECT * FROM leads WHERE 1=1"
    params: list = []

    if status:
        query += " AND status = %s"
        params.append(status)
    if source:
        query += " AND source = %s"
        params.append(source)

    query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params += [limit, offset]

    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def get_lead(lead_id: int) -> dict | None:
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM leads WHERE id = %s", (lead_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def count_recently_sent_leads(hours: int = 24) -> int:
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM leads WHERE status = 'sent' AND updated_at >= %s",
            (cutoff,)
        )
        return cur.fetchone()[0]


def get_stats() -> dict:
    # Use a Python-computed cutoff so we don't rely on any DB date functions
    cutoff = (datetime.utcnow() - timedelta(days=1)).isoformat()

    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT COUNT(*) AS total FROM leads")
        total = cur.fetchone()["total"]

        cur.execute(
            "SELECT status, COUNT(*) AS cnt FROM leads GROUP BY status"
        )
        by_status = {r["status"]: r["cnt"] for r in cur.fetchall()}

        cur.execute(
            "SELECT source, COUNT(*) AS cnt FROM leads GROUP BY source"
        )
        by_source = {r["source"]: r["cnt"] for r in cur.fetchall()}

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM leads WHERE created_at >= %s",
            (cutoff,),
        )
        recent_24h = cur.fetchone()["cnt"]

    return {
        "total": total,
        "by_status": by_status,
        "by_source": by_source,
        "recent_24h": recent_24h,
    }
