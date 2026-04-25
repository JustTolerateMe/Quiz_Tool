import sqlite3
from datetime import datetime, timezone
from typing import Optional

from backend.config import DB_PATH

_ACTIVE_STATUSES = ('QUEUED', 'PARSING', 'TRIAGING', 'PROCESSING', 'GENERATING', 'EXPORTING')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    """Open a connection with WAL mode and a write timeout to handle concurrency."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id           TEXT PRIMARY KEY,
            status           TEXT NOT NULL DEFAULT 'QUEUED',
            pdf_filename     TEXT NOT NULL,
            total_images     INTEGER NOT NULL DEFAULT 0,
            processed_images INTEGER NOT NULL DEFAULT 0,
            skipped_images   INTEGER NOT NULL DEFAULT 0,
            generated_images INTEGER NOT NULL DEFAULT 0,
            quiz_count       INTEGER NOT NULL DEFAULT 0,
            export_path      TEXT,
            html_export_path TEXT,
            pdf_export_path  TEXT,
            error            TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        )
    """)
    # Migrate existing DBs that predate the generated_images column
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN generated_images INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN html_export_path TEXT")
    except Exception:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN pdf_export_path TEXT")
    except Exception:
        pass  # Column already exists
    conn.commit()
    conn.close()


def create_job(job_id: str, filename: str) -> None:
    now = _now()
    conn = _connect()
    conn.execute(
        """INSERT INTO jobs
           (job_id, status, pdf_filename, total_images, processed_images,
            skipped_images, quiz_count, export_path, error, created_at, updated_at)
           VALUES (?, 'QUEUED', ?, 0, 0, 0, 0, NULL, NULL, ?, ?)""",
        (job_id, filename, now, now),
    )
    conn.commit()
    conn.close()


def update_job(job_id: str, **kwargs) -> None:
    kwargs["updated_at"] = _now()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    conn = _connect()
    conn.execute(f"UPDATE jobs SET {sets} WHERE job_id = ?", vals)
    conn.commit()
    conn.close()


def get_job(job_id: str) -> Optional[dict]:
    conn = _connect()
    row = conn.execute("""
        SELECT job_id, status, pdf_filename, total_images, processed_images,
               skipped_images, generated_images, quiz_count, export_path,
               html_export_path, pdf_export_path, error, created_at, updated_at
        FROM jobs WHERE job_id = ?
    """, (job_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    cols = [
        "job_id", "status", "pdf_filename", "total_images", "processed_images",
        "skipped_images", "generated_images", "quiz_count", "export_path",
        "html_export_path", "pdf_export_path", "error", "created_at", "updated_at",
    ]
    return dict(zip(cols, row))


def get_queue_position(job_id: str) -> Optional[int]:
    """Return how many active/queued jobs are ahead of this one, or None if not queued."""
    conn = _connect()
    job_row = conn.execute(
        "SELECT status, created_at FROM jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    if job_row is None or job_row[0] != "QUEUED":
        conn.close()
        return None
    created_at = job_row[1]
    placeholders = ",".join("?" * len(_ACTIVE_STATUSES))
    ahead = conn.execute(
        f"SELECT COUNT(*) FROM jobs WHERE status IN ({placeholders}) AND created_at < ?",
        (*_ACTIVE_STATUSES, created_at),
    ).fetchone()[0]
    conn.close()
    return ahead + 1


def get_stale_jobs(statuses: tuple, older_than_minutes: int) -> list[dict]:
    """Return jobs in given statuses whose updated_at is older than N minutes."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)).isoformat()
    placeholders = ",".join("?" * len(statuses))
    conn = _connect()
    rows = conn.execute(
        f"SELECT job_id, status FROM jobs WHERE status IN ({placeholders}) AND updated_at < ?",
        (*statuses, cutoff),
    ).fetchall()
    conn.close()
    return [{"job_id": r[0], "status": r[1]} for r in rows]


def get_jobs_for_cleanup() -> dict:
    """Return jobs eligible for cleanup grouped by rule."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    conn = _connect()

    # AWAITING_REVIEW older than 24h
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    abandoned = conn.execute(
        "SELECT job_id FROM jobs WHERE status = 'AWAITING_REVIEW' AND updated_at < ?",
        (cutoff_24h,),
    ).fetchall()

    # COMPLETE or FAILED older than 7 days
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    expired = conn.execute(
        "SELECT job_id FROM jobs WHERE status IN ('COMPLETE','FAILED') AND updated_at < ?",
        (cutoff_7d,),
    ).fetchall()

    # QUEUED older than 2h (task message likely lost from Redis)
    cutoff_2h = (now - timedelta(hours=2)).isoformat()
    lost = conn.execute(
        "SELECT job_id FROM jobs WHERE status = 'QUEUED' AND created_at < ?",
        (cutoff_2h,),
    ).fetchall()

    conn.close()
    return {
        "abandoned": [r[0] for r in abandoned],
        "expired": [r[0] for r in expired],
        "lost": [r[0] for r in lost],
    }


def delete_job(job_id: str) -> None:
    conn = _connect()
    conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()
