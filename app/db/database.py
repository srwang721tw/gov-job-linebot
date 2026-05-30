"""
資料庫抽象層：支援兩個後端
  - 本機開發：SQLite（無需設定 DATABASE_URL）
  - 正式環境：Neon PostgreSQL（設定 DATABASE_URL 環境變數）

SQL 語法差異由 _run() 自動處理（? → %s）。
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.models.subscription import Subscription
from app.utils.config import DATABASE_URL, SQLITE_PATH
from app.utils.logger import logger

_IS_POSTGRES = bool(DATABASE_URL)

# ── 建表 SQL ─────────────────────────────────────────────────────────────────
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
INSERT INTO subscriptions
    (line_user_id, work_place_code, work_place_name,
     person_kind_code, person_kind_name,
     title_keyword, org_keyword, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(line_user_id) DO UPDATE SET
    work_place_code  = EXCLUDED.work_place_code,
    work_place_name  = EXCLUDED.work_place_name,
    person_kind_code = EXCLUDED.person_kind_code,
    person_kind_name = EXCLUDED.person_kind_name,
    title_keyword    = EXCLUDED.title_keyword,
    org_keyword      = EXCLUDED.org_keyword,
    updated_at       = EXCLUDED.updated_at
"""


# ── 連線管理 ──────────────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    if _IS_POSTGRES:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        conn.cursor_factory = psycopg2.extras.RealDictCursor
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _run(conn, sql: str, params: tuple = ()):
    """執行 SQL，自動將 ? 轉為 %s（psycopg2 格式）。"""
    if _IS_POSTGRES:
        cur = conn.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return cur
    return conn.execute(sql, params)


# ── 公開 API ──────────────────────────────────────────────────────────────────

def init_db() -> None:
    with get_conn() as conn:
        _run(conn, _CREATE_TABLE)
    backend = "PostgreSQL (Neon)" if _IS_POSTGRES else "SQLite"
    logger.info(f"資料庫初始化完成（{backend}）")


def save_subscription(sub: Subscription) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        _run(conn, _UPSERT, (
            sub.line_user_id,
            sub.work_place_code, sub.work_place_name,
            sub.person_kind_code, sub.person_kind_name,
            sub.title_keyword, sub.org_keyword,
            now,
        ))
    logger.info(f"訂閱已儲存：user={sub.line_user_id[:8]}...")


def get_subscription(line_user_id: str) -> Subscription | None:
    with get_conn() as conn:
        row = _run(
            conn,
            "SELECT * FROM subscriptions WHERE line_user_id = ?",
            (line_user_id,)
        ).fetchone()
    if not row:
        return None
    return Subscription(**dict(row))


def delete_subscription(line_user_id: str) -> None:
    with get_conn() as conn:
        _run(conn, "DELETE FROM subscriptions WHERE line_user_id = ?", (line_user_id,))
    logger.info(f"訂閱已刪除：user={line_user_id[:8]}...")


def get_subscription_count() -> int:
    with get_conn() as conn:
        row = _run(conn, "SELECT COUNT(*) FROM subscriptions").fetchone()
    # sqlite3.Row 和 psycopg2.RealDictRow 都支援 index 存取
    return list(row)[0] if row else 0
