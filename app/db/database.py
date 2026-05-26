import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List

from app.models.job import Job
from app.utils.config import SQLITE_PATH
from app.utils.logger import logger

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT UNIQUE,
    title TEXT,
    agency TEXT,
    location TEXT,
    job_series TEXT,
    rank_type TEXT,
    description TEXT,
    requirement TEXT,
    contact TEXT,
    apply_method TEXT,
    note TEXT,
    publish_date TEXT,
    deadline TEXT,
    detail_url TEXT,
    created_at TEXT,
    updated_at TEXT
)
"""

_UPSERT = """
INSERT INTO jobs (
    job_id, title, agency, location, job_series, rank_type,
    description, requirement, contact, apply_method, note,
    publish_date, deadline, detail_url, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(job_id) DO UPDATE SET
    title=excluded.title,
    agency=excluded.agency,
    location=excluded.location,
    job_series=excluded.job_series,
    rank_type=excluded.rank_type,
    description=excluded.description,
    requirement=excluded.requirement,
    contact=excluded.contact,
    apply_method=excluded.apply_method,
    note=excluded.note,
    publish_date=excluded.publish_date,
    deadline=excluded.deadline,
    detail_url=excluded.detail_url,
    updated_at=excluded.updated_at
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(_CREATE_TABLE)
        conn.commit()
    logger.info("Database initialized")


def upsert_jobs(jobs: List[Job]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    saved = 0
    with get_conn() as conn:
        for job in jobs:
            try:
                conn.execute(_UPSERT, (
                    job.job_id, job.title, job.agency, job.location, job.job_series,
                    job.rank_type, job.description, job.requirement, job.contact,
                    job.apply_method, job.note, job.publish_date, job.deadline,
                    job.detail_url, now, now,
                ))
                saved += 1
            except Exception as e:
                logger.warning(f"Upsert failed for job {job.job_id}: {e}")
        conn.commit()
    return saved


def get_all_jobs() -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY deadline DESC").fetchall()
    return [dict(r) for r in rows]


def get_job_count() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
    return row[0]
