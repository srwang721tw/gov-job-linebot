"""
資料庫抽象層（v3）：支援兩個後端
  - 本機開發：SQLite（無需設定 DATABASE_URL）
  - 正式環境：Neon PostgreSQL（設定 DATABASE_URL 環境變數）

資料表：
  line_user     LINE Bot 使用者
  telegram_user Telegram Bot 使用者
  subscription  使用者訂閱條件（LINE + Telegram 共用）
  jobs          每日爬取的政府職缺資料（含詳細頁）

SQL 語法差異由 _run() 及各 SQL 字串自動處理。
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.models.job import Job
from app.models.subscription import Subscription
from app.utils.config import DATABASE_URL, SQLITE_PATH
from app.utils.logger import logger

_IS_POSTGRES = bool(DATABASE_URL)

# ── 建表 SQL ─────────────────────────────────────────────────────────────────

_CREATE_LINE_USER_PG = """
CREATE TABLE IF NOT EXISTS line_user (
    line_user_id VARCHAR(50)  PRIMARY KEY,
    display_name VARCHAR(100) DEFAULT '',
    created_at   TIMESTAMPTZ  DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  DEFAULT NOW()
)
"""

_CREATE_LINE_USER_SQLITE = """
CREATE TABLE IF NOT EXISTS line_user (
    line_user_id TEXT PRIMARY KEY,
    display_name TEXT DEFAULT '',
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
)
"""

_CREATE_TELEGRAM_USER_PG = """
CREATE TABLE IF NOT EXISTS telegram_user (
    telegram_user_id BIGINT       PRIMARY KEY,
    username         VARCHAR(100) DEFAULT '',
    first_name       VARCHAR(100) DEFAULT '',
    created_at       TIMESTAMPTZ  DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  DEFAULT NOW()
)
"""

_CREATE_TELEGRAM_USER_SQLITE = """
CREATE TABLE IF NOT EXISTS telegram_user (
    telegram_user_id INTEGER PRIMARY KEY,
    username         TEXT DEFAULT '',
    first_name       TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now'))
)
"""

_UPSERT_LINE_USER = """
INSERT INTO line_user (line_user_id, display_name, updated_at)
VALUES (?, ?, ?)
ON CONFLICT(line_user_id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    updated_at   = EXCLUDED.updated_at
"""

_UPSERT_TELEGRAM_USER = """
INSERT INTO telegram_user (telegram_user_id, username, first_name, updated_at)
VALUES (?, ?, ?, ?)
ON CONFLICT(telegram_user_id) DO UPDATE SET
    username   = EXCLUDED.username,
    first_name = EXCLUDED.first_name,
    updated_at = EXCLUDED.updated_at
"""

_CREATE_SUBSCRIPTION_PG = """
CREATE TABLE IF NOT EXISTS subscription (
    id               SERIAL PRIMARY KEY,
    platform         VARCHAR(10)  NOT NULL,
    platform_user_id VARCHAR(50)  NOT NULL,
    work_place_code  VARCHAR(10)  DEFAULT '',
    work_place_name  VARCHAR(50)  DEFAULT '',
    person_kind_code VARCHAR(10)  DEFAULT '',
    person_kind_name VARCHAR(50)  DEFAULT '',
    sysnam_grp       VARCHAR(5)   DEFAULT '',
    sysnam_grp_name  VARCHAR(20)  DEFAULT '',
    title_keyword    VARCHAR(100) DEFAULT '',
    org_keyword      VARCHAR(100) DEFAULT '',
    updated_at       TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE(platform, platform_user_id)
)
"""

_CREATE_SUBSCRIPTION_SQLITE = """
CREATE TABLE IF NOT EXISTS subscription (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform         TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    work_place_code  TEXT DEFAULT '',
    work_place_name  TEXT DEFAULT '',
    person_kind_code TEXT DEFAULT '',
    person_kind_name TEXT DEFAULT '',
    sysnam_grp       TEXT DEFAULT '',
    sysnam_grp_name  TEXT DEFAULT '',
    title_keyword    TEXT DEFAULT '',
    org_keyword      TEXT DEFAULT '',
    updated_at       TEXT,
    UNIQUE(platform, platform_user_id)
)
"""

_CREATE_JOBS_PG = """
CREATE TABLE IF NOT EXISTS jobs (
    id               SERIAL PRIMARY KEY,
    job_id           VARCHAR(100) UNIQUE NOT NULL,
    title            VARCHAR(200) DEFAULT '',
    org_name         VARCHAR(200) DEFAULT '',
    work_place       VARCHAR(100) DEFAULT '',
    work_place_code  VARCHAR(10)  DEFAULT '',
    person_kind      VARCHAR(50)  DEFAULT '',
    person_kind_code VARCHAR(10)  DEFAULT '',
    rank_type        VARCHAR(50)  DEFAULT '',
    job_series       VARCHAR(50)  DEFAULT '',
    sysnam_grp       VARCHAR(5)   DEFAULT '',
    regular_slots    INTEGER      DEFAULT 0,
    alternate_slots  INTEGER      DEFAULT 0,
    qualifications   TEXT         DEFAULT '',
    work_items       TEXT         DEFAULT '',
    work_address     VARCHAR(300) DEFAULT '',
    contact_method   VARCHAR(300) DEFAULT '',
    apply_method     VARCHAR(200) DEFAULT '',
    publish_date     VARCHAR(20)  DEFAULT '',
    deadline         VARCHAR(50)  DEFAULT '',
    deadline_end_iso VARCHAR(10)  DEFAULT '',
    job_url          VARCHAR(500) DEFAULT '',
    crawled_at       TIMESTAMPTZ  DEFAULT NOW()
)
"""

_CREATE_JOBS_SQLITE = """
CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT UNIQUE NOT NULL,
    title            TEXT DEFAULT '',
    org_name         TEXT DEFAULT '',
    work_place       TEXT DEFAULT '',
    work_place_code  TEXT DEFAULT '',
    person_kind      TEXT DEFAULT '',
    person_kind_code TEXT DEFAULT '',
    rank_type        TEXT DEFAULT '',
    job_series       TEXT DEFAULT '',
    sysnam_grp       TEXT DEFAULT '',
    regular_slots    INTEGER DEFAULT 0,
    alternate_slots  INTEGER DEFAULT 0,
    qualifications   TEXT DEFAULT '',
    work_items       TEXT DEFAULT '',
    work_address     TEXT DEFAULT '',
    contact_method   TEXT DEFAULT '',
    apply_method     TEXT DEFAULT '',
    publish_date     TEXT DEFAULT '',
    deadline         TEXT DEFAULT '',
    deadline_end_iso TEXT DEFAULT '',
    job_url          TEXT DEFAULT '',
    crawled_at       TEXT DEFAULT (datetime('now'))
)
"""

_CREATE_JOBS_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_jobs_work_place_code ON jobs(work_place_code)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_person_kind_code ON jobs(person_kind_code)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_sysnam_grp ON jobs(sysnam_grp)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_deadline_end ON jobs(deadline_end_iso)",
]

_UPSERT_SUBSCRIPTION = """
INSERT INTO subscription
    (platform, platform_user_id, work_place_code, work_place_name,
     person_kind_code, person_kind_name,
     sysnam_grp, sysnam_grp_name,
     title_keyword, org_keyword, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(platform, platform_user_id) DO UPDATE SET
    work_place_code  = EXCLUDED.work_place_code,
    work_place_name  = EXCLUDED.work_place_name,
    person_kind_code = EXCLUDED.person_kind_code,
    person_kind_name = EXCLUDED.person_kind_name,
    sysnam_grp       = EXCLUDED.sysnam_grp,
    sysnam_grp_name  = EXCLUDED.sysnam_grp_name,
    title_keyword    = EXCLUDED.title_keyword,
    org_keyword      = EXCLUDED.org_keyword,
    updated_at       = EXCLUDED.updated_at
"""

_UPSERT_JOB = """
INSERT INTO jobs
    (job_id, title, org_name, work_place, work_place_code,
     person_kind, person_kind_code, rank_type, job_series, sysnam_grp,
     regular_slots, alternate_slots, qualifications, work_items,
     work_address, contact_method, apply_method,
     publish_date, deadline, deadline_end_iso, job_url, crawled_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(job_id) DO UPDATE SET
    title            = EXCLUDED.title,
    org_name         = EXCLUDED.org_name,
    work_place       = EXCLUDED.work_place,
    work_place_code  = EXCLUDED.work_place_code,
    person_kind      = EXCLUDED.person_kind,
    person_kind_code = EXCLUDED.person_kind_code,
    rank_type        = EXCLUDED.rank_type,
    job_series       = EXCLUDED.job_series,
    sysnam_grp       = EXCLUDED.sysnam_grp,
    regular_slots    = EXCLUDED.regular_slots,
    alternate_slots  = EXCLUDED.alternate_slots,
    qualifications   = EXCLUDED.qualifications,
    work_items       = EXCLUDED.work_items,
    work_address     = EXCLUDED.work_address,
    contact_method   = EXCLUDED.contact_method,
    apply_method     = EXCLUDED.apply_method,
    publish_date     = EXCLUDED.publish_date,
    deadline         = EXCLUDED.deadline,
    deadline_end_iso = EXCLUDED.deadline_end_iso,
    job_url          = EXCLUDED.job_url,
    crawled_at       = EXCLUDED.crawled_at
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


# ── 初始化 ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    if _IS_POSTGRES:
        stmts = [
            _CREATE_LINE_USER_PG,
            _CREATE_TELEGRAM_USER_PG,
            _CREATE_SUBSCRIPTION_PG,
            _CREATE_JOBS_PG,
        ]
    else:
        stmts = [
            _CREATE_LINE_USER_SQLITE,
            _CREATE_TELEGRAM_USER_SQLITE,
            _CREATE_SUBSCRIPTION_SQLITE,
            _CREATE_JOBS_SQLITE,
        ]

    with get_conn() as conn:
        for sql in stmts:
            _run(conn, sql)
        for idx_sql in _CREATE_JOBS_IDX:
            _run(conn, idx_sql)
        if _IS_POSTGRES:
            _run(conn, "CREATE EXTENSION IF NOT EXISTS pg_trgm")

    backend = "PostgreSQL (Neon)" if _IS_POSTGRES else "SQLite"
    logger.info(f"資料庫初始化完成（{backend}）")


# ── 使用者 CRUD ────────────────────────────────────────────────────────────────

def upsert_line_user(line_user_id: str, display_name: str = "") -> None:
    """記錄 LINE 使用者（每次互動時更新）。"""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        _run(conn, _UPSERT_LINE_USER, (line_user_id, display_name, now))


def upsert_telegram_user(
    telegram_user_id: int,
    username: str = "",
    first_name: str = "",
) -> None:
    """記錄 Telegram 使用者（每次互動時更新）。"""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        _run(conn, _UPSERT_TELEGRAM_USER, (telegram_user_id, username, first_name, now))


# ── 訂閱 CRUD ──────────────────────────────────────────────────────────────────

def save_subscription(sub: Subscription) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        _run(conn, _UPSERT_SUBSCRIPTION, (
            sub.platform, sub.platform_user_id,
            sub.work_place_code, sub.work_place_name,
            sub.person_kind_code, sub.person_kind_name,
            sub.sysnam_grp, sub.sysnam_grp_name,
            sub.title_keyword, sub.org_keyword,
            now,
        ))
    logger.info(f"訂閱已儲存：{sub.platform}:{sub.platform_user_id[:8]}...")


def get_subscription(platform: str, platform_user_id: str) -> Subscription | None:
    with get_conn() as conn:
        row = _run(
            conn,
            "SELECT * FROM subscription WHERE platform = ? AND platform_user_id = ?",
            (platform, platform_user_id),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    return Subscription(
        platform         = d["platform"],
        platform_user_id = d["platform_user_id"],
        work_place_code  = d.get("work_place_code", ""),
        work_place_name  = d.get("work_place_name", ""),
        person_kind_code = d.get("person_kind_code", ""),
        person_kind_name = d.get("person_kind_name", ""),
        sysnam_grp       = d.get("sysnam_grp", ""),
        sysnam_grp_name  = d.get("sysnam_grp_name", ""),
        title_keyword    = d.get("title_keyword", ""),
        org_keyword      = d.get("org_keyword", ""),
    )


def delete_subscription(platform: str, platform_user_id: str) -> None:
    with get_conn() as conn:
        _run(
            conn,
            "DELETE FROM subscription WHERE platform = ? AND platform_user_id = ?",
            (platform, platform_user_id),
        )
    logger.info(f"訂閱已刪除：{platform}:{platform_user_id[:8]}...")


def get_subscription_count() -> int:
    with get_conn() as conn:
        row = _run(conn, "SELECT COUNT(*) AS cnt FROM subscription").fetchone()
    if not row:
        return 0
    return dict(row).get("cnt", 0)


# ── 職缺 CRUD ──────────────────────────────────────────────────────────────────

def upsert_job(job: Job) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        _run(conn, _UPSERT_JOB, (
            job.job_id, job.title, job.org_name,
            job.work_place, job.work_place_code,
            job.person_kind, job.person_kind_code,
            job.rank_type, job.job_series, job.sysnam_grp,
            job.regular_slots, job.alternate_slots,
            job.qualifications, job.work_items,
            job.work_address, job.contact_method, job.apply_method,
            job.publish_date, job.deadline, job.deadline_end_iso,
            job.job_url, now,
        ))


def upsert_jobs(jobs: list[Job]) -> None:
    """批次 UPSERT 職缺（每筆個別執行，避免單筆錯誤中斷整批）。"""
    ok = err = 0
    for job in jobs:
        try:
            upsert_job(job)
            ok += 1
        except Exception as e:
            logger.warning(f"upsert_job 失敗 job_id={job.job_id}: {e}")
            err += 1
    logger.info(f"upsert_jobs 完成：成功 {ok} 筆，失敗 {err} 筆")


def search_jobs(
    work_place_code: str = "",
    person_kind_code: str = "",
    sysnam_grp: str = "",
    title_keyword: str = "",
    org_keyword: str = "",
    sysnam_names: list[str] | None = None,
    limit: int = 20,
) -> list[Job]:
    """
    依條件從 jobs 表搜尋有效職缺（deadline_end_iso >= 今日）。

    sysnam_names：若 sysnam_grp 非空，呼叫方傳入對應的職系名稱清單，
                  用 IN 子句過濾 job_series。
    """
    from datetime import date
    today = date.today().isoformat()

    where = ["deadline_end_iso >= ?"]
    params: list = [today]

    if work_place_code:
        where.append("work_place_code = ?")
        params.append(work_place_code)

    if person_kind_code:
        where.append("person_kind_code = ?")
        params.append(person_kind_code)

    if sysnam_names:
        placeholders = ",".join(["?" for _ in sysnam_names])
        where.append(f"job_series IN ({placeholders})")
        params.extend(sysnam_names)

    if title_keyword:
        where.append("title LIKE ?")
        params.append(f"%{title_keyword}%")

    if org_keyword:
        where.append("org_name LIKE ?")
        params.append(f"%{org_keyword}%")

    sql = (
        "SELECT * FROM jobs WHERE "
        + " AND ".join(where)
        + " ORDER BY deadline_end_iso ASC LIMIT ?"
    )
    params.append(limit)

    with get_conn() as conn:
        rows = _run(conn, sql, tuple(params)).fetchall()

    results = []
    for row in rows:
        d = dict(row)
        results.append(Job(
            job_id           = d["job_id"],
            title            = d.get("title", ""),
            org_name         = d.get("org_name", ""),
            work_place       = d.get("work_place", ""),
            work_place_code  = d.get("work_place_code", ""),
            person_kind      = d.get("person_kind", ""),
            person_kind_code = d.get("person_kind_code", ""),
            rank_type        = d.get("rank_type", ""),
            job_series       = d.get("job_series", ""),
            sysnam_grp       = d.get("sysnam_grp", ""),
            regular_slots    = d.get("regular_slots", 0) or 0,
            alternate_slots  = d.get("alternate_slots", 0) or 0,
            qualifications   = d.get("qualifications", ""),
            work_items       = d.get("work_items", ""),
            work_address     = d.get("work_address", ""),
            contact_method   = d.get("contact_method", ""),
            apply_method     = d.get("apply_method", ""),
            publish_date     = d.get("publish_date", ""),
            deadline         = d.get("deadline", ""),
            deadline_end_iso = d.get("deadline_end_iso", ""),
            job_url          = d.get("job_url", ""),
        ))
    return results


def get_jobs_count() -> int:
    with get_conn() as conn:
        row = _run(conn, "SELECT COUNT(*) AS cnt FROM jobs").fetchone()
    if not row:
        return 0
    return dict(row).get("cnt", 0)


def delete_expired_jobs() -> int:
    """刪除截止日已過的職缺。回傳刪除筆數。"""
    from datetime import date
    today = date.today().isoformat()
    with get_conn() as conn:
        cur = _run(
            conn,
            "DELETE FROM jobs WHERE deadline_end_iso != '' AND deadline_end_iso < ?",
            (today,),
        )
        # rowcount 在 psycopg2 cursor 與 sqlite3 cursor 上均可用
        count = cur.rowcount if hasattr(cur, "rowcount") else 0
    logger.info(f"已清除 {count} 筆過期職缺")
    return count
