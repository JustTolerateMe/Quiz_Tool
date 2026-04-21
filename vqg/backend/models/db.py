import sqlite3
from datetime import datetime, timezone
from typing import Optional

from backend.config import DB_PATH


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
               html_export_path, error, created_at, updated_at
        FROM jobs WHERE job_id = ?
    """, (job_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    cols = [
        "job_id", "status", "pdf_filename", "total_images", "processed_images",
        "skipped_images", "generated_images", "quiz_count", "export_path",
        "html_export_path", "error", "created_at", "updated_at",
    ]
    return dict(zip(cols, row))
