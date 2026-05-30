import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.models.subscription import Subscription
from app.utils.config import SQLITE_PATH
from app.utils.logger import logger

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS subscriptions (
    line_user_id     TEXT PRIMARY KEY,
    work_place_code  TEXT DEFAULT '',
    work_place_name  TEXT DEFAULT '',
    person_kind_code TEXT DEFAULT '',
    person_kind_name TEXT DEFAULT '',
    title_keyword    TEXT DEFAULT '',
    org_keyword      TEXT DEFAULT '',
    updated_at       TEXT
)
"""

_UPSERT = """
INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(line_user_id) DO UPDATE SET
    work_place_code  = excluded.work_place_code,
    work_place_name  = excluded.work_place_name,
    person_kind_code = excluded.person_kind_code,
    person_kind_name = excluded.person_kind_name,
    title_keyword    = excluded.title_keyword,
    org_keyword      = excluded.org_keyword,
    updated_at       = excluded.updated_at
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
    logger.info("資料庫初始化完成")


def save_subscription(sub: Subscription) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(_UPSERT, (
            sub.line_user_id,
            sub.work_place_code, sub.work_place_name,
            sub.person_kind_code, sub.person_kind_name,
            sub.title_keyword, sub.org_keyword,
            now,
        ))
        conn.commit()
    logger.info(f"訂閱已儲存：user={sub.line_user_id[:8]}...")


def get_subscription(line_user_id: str) -> Subscription | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE line_user_id = ?",
            (line_user_id,)
        ).fetchone()
    if not row:
        return None
    return Subscription(**dict(row))


def delete_subscription(line_user_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM subscriptions WHERE line_user_id = ?",
            (line_user_id,)
        )
        conn.commit()
    logger.info(f"訂閱已刪除：user={line_user_id[:8]}...")


def get_subscription_count() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()
    return row[0]
