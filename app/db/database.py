"""
資料庫抽象層（v3.1）：支援兩個後端
  - 本機開發：SQLite（無需設定 DATABASE_URL）
  - 正式環境：Neon PostgreSQL（設定 DATABASE_URL 環境變數）

資料表：
  line_user     LINE Bot 使用者
  telegram_user Telegram Bot 使用者
  subscription  使用者訂閱條件（LINE + Telegram 共用）
  jobs          每日爬取的政府職缺資料（含詳細頁）

v3.1 主要變更：
  subscription: 多地點/多官等/職務列等/職系細項/多關鍵字
  jobs: 統一日期為 YYYY-MM-DD，新增 rank_grade_min/max、rank_type_codes、search_text
"""
import re
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

# v3.1 subscription：多地點/多官等/職務列等/職系細項/關鍵字
_CREATE_SUBSCRIPTION_PG = """
CREATE TABLE IF NOT EXISTS subscription (
    id               SERIAL PRIMARY KEY,
    platform         VARCHAR(10)  NOT NULL,
    platform_user_id VARCHAR(50)  NOT NULL,
    work_place_codes TEXT         DEFAULT '',
    work_place_names TEXT         DEFAULT '',
    rank_types       TEXT         DEFAULT '',
    rank_grade_min   INTEGER      DEFAULT 0,
    rank_grade_max   INTEGER      DEFAULT 0,
    sysnam_grp       VARCHAR(5)   DEFAULT '',
    sysnam_grp_name  VARCHAR(20)  DEFAULT '',
    sysnam_names     TEXT         DEFAULT '',
    keywords         TEXT         DEFAULT '',
    updated_at       TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE(platform, platform_user_id)
)
"""

_CREATE_SUBSCRIPTION_SQLITE = """
CREATE TABLE IF NOT EXISTS subscription (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform         TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    work_place_codes TEXT DEFAULT '',
    work_place_names TEXT DEFAULT '',
    rank_types       TEXT DEFAULT '',
    rank_grade_min   INTEGER DEFAULT 0,
    rank_grade_max   INTEGER DEFAULT 0,
    sysnam_grp       TEXT DEFAULT '',
    sysnam_grp_name  TEXT DEFAULT '',
    sysnam_names     TEXT DEFAULT '',
    keywords         TEXT DEFAULT '',
    updated_at       TEXT,
    UNIQUE(platform, platform_user_id)
)
"""

# v3.2 jobs：job_id 直接作為 PRIMARY KEY（移除無意義的 serial id）
_CREATE_JOBS_PG = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id           VARCHAR(100) PRIMARY KEY,
    title            VARCHAR(200) DEFAULT '',
    org_name         VARCHAR(200) DEFAULT '',
    work_place       TEXT         DEFAULT '',
    work_place_code  VARCHAR(10)  DEFAULT '',
    rank_type        TEXT         DEFAULT '',
    rank_type_codes  TEXT         DEFAULT '',
    rank_grade_min   INTEGER      DEFAULT 0,
    rank_grade_max   INTEGER      DEFAULT 0,
    job_series       TEXT         DEFAULT '',
    sysnam_grp       VARCHAR(5)   DEFAULT '',
    regular_slots    INTEGER      DEFAULT 0,
    alternate_slots  INTEGER      DEFAULT 0,
    qualifications   TEXT         DEFAULT '',
    work_items       TEXT         DEFAULT '',
    work_address     TEXT         DEFAULT '',
    publish_date     VARCHAR(10)  DEFAULT '',
    deadline_start   VARCHAR(10)  DEFAULT '',
    deadline_end     VARCHAR(10)  DEFAULT '',
    job_url          VARCHAR(500) DEFAULT '',
    search_text      TEXT         DEFAULT '',
    crawled_at       TIMESTAMPTZ  DEFAULT NOW()
)
"""

_CREATE_JOBS_SQLITE = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    title           TEXT DEFAULT '',
    org_name        TEXT DEFAULT '',
    work_place      TEXT DEFAULT '',
    work_place_code TEXT DEFAULT '',
    rank_type       TEXT DEFAULT '',
    rank_type_codes TEXT DEFAULT '',
    rank_grade_min  INTEGER DEFAULT 0,
    rank_grade_max  INTEGER DEFAULT 0,
    job_series      TEXT DEFAULT '',
    sysnam_grp      TEXT DEFAULT '',
    regular_slots   INTEGER DEFAULT 0,
    alternate_slots INTEGER DEFAULT 0,
    qualifications  TEXT DEFAULT '',
    work_items      TEXT DEFAULT '',
    work_address    TEXT DEFAULT '',
    publish_date    TEXT DEFAULT '',
    deadline_start  TEXT DEFAULT '',
    deadline_end    TEXT DEFAULT '',
    job_url         TEXT DEFAULT '',
    search_text     TEXT DEFAULT '',
    crawled_at      TEXT DEFAULT (datetime('now'))
)
"""

_CREATE_JOBS_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_jobs_work_place_code ON jobs(work_place_code)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_sysnam_grp      ON jobs(sysnam_grp)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_deadline_end    ON jobs(deadline_end)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_rank_grade_min  ON jobs(rank_grade_min)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_rank_grade_max  ON jobs(rank_grade_max)",
]

# Migration：為已存在的舊表新增欄位（IF NOT EXISTS，安全執行）
_ALTER_SUBSCRIPTION = [
    "ALTER TABLE subscription ADD COLUMN IF NOT EXISTS work_place_codes TEXT DEFAULT ''",
    "ALTER TABLE subscription ADD COLUMN IF NOT EXISTS work_place_names TEXT DEFAULT ''",
    "ALTER TABLE subscription ADD COLUMN IF NOT EXISTS rank_types       TEXT DEFAULT ''",
    "ALTER TABLE subscription ADD COLUMN IF NOT EXISTS rank_grade_min   INTEGER DEFAULT 0",
    "ALTER TABLE subscription ADD COLUMN IF NOT EXISTS rank_grade_max   INTEGER DEFAULT 0",
    "ALTER TABLE subscription ADD COLUMN IF NOT EXISTS sysnam_names     TEXT DEFAULT ''",
    "ALTER TABLE subscription ADD COLUMN IF NOT EXISTS keywords         TEXT DEFAULT ''",
]

_ALTER_JOBS = [
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS rank_type_codes TEXT DEFAULT ''",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS rank_grade_min  INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS rank_grade_max  INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS deadline_start  VARCHAR(10) DEFAULT ''",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS deadline_end    VARCHAR(10) DEFAULT ''",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS search_text     TEXT DEFAULT ''",
    # Bug fix v3.2.1：DGPA 詳細頁文字可能超過 100 字元
    "ALTER TABLE jobs ALTER COLUMN work_place TYPE TEXT",
    "ALTER TABLE jobs ALTER COLUMN job_series TYPE TEXT",
]

# ── UPSERT SQL ────────────────────────────────────────────────────────────────

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

_UPSERT_SUBSCRIPTION = """
INSERT INTO subscription
    (platform, platform_user_id,
     work_place_codes, work_place_names,
     rank_types, rank_grade_min, rank_grade_max,
     sysnam_grp, sysnam_grp_name, sysnam_names,
     keywords, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(platform, platform_user_id) DO UPDATE SET
    work_place_codes = EXCLUDED.work_place_codes,
    work_place_names = EXCLUDED.work_place_names,
    rank_types       = EXCLUDED.rank_types,
    rank_grade_min   = EXCLUDED.rank_grade_min,
    rank_grade_max   = EXCLUDED.rank_grade_max,
    sysnam_grp       = EXCLUDED.sysnam_grp,
    sysnam_grp_name  = EXCLUDED.sysnam_grp_name,
    sysnam_names     = EXCLUDED.sysnam_names,
    keywords         = EXCLUDED.keywords,
    updated_at       = EXCLUDED.updated_at
"""

_UPSERT_COLS = """(job_id, title, org_name, work_place, work_place_code,
     rank_type, rank_type_codes, rank_grade_min, rank_grade_max,
     job_series, sysnam_grp, regular_slots, alternate_slots,
     qualifications, work_items, work_address,
     publish_date, deadline_start, deadline_end,
     job_url, search_text, crawled_at)"""

_UPSERT_CONFLICT = """
ON CONFLICT(job_id) DO UPDATE SET
    title           = EXCLUDED.title,
    org_name        = EXCLUDED.org_name,
    work_place      = EXCLUDED.work_place,
    work_place_code = EXCLUDED.work_place_code,
    rank_type       = EXCLUDED.rank_type,
    rank_type_codes = EXCLUDED.rank_type_codes,
    rank_grade_min  = EXCLUDED.rank_grade_min,
    rank_grade_max  = EXCLUDED.rank_grade_max,
    job_series      = EXCLUDED.job_series,
    sysnam_grp      = EXCLUDED.sysnam_grp,
    deadline_start  = EXCLUDED.deadline_start,
    deadline_end    = EXCLUDED.deadline_end,
    job_url         = EXCLUDED.job_url,
    crawled_at      = EXCLUDED.crawled_at,
    qualifications  = CASE WHEN EXCLUDED.qualifications != '' THEN EXCLUDED.qualifications ELSE jobs.qualifications END,
    work_items      = CASE WHEN EXCLUDED.work_items     != '' THEN EXCLUDED.work_items     ELSE jobs.work_items     END,
    work_address    = CASE WHEN EXCLUDED.work_address   != '' THEN EXCLUDED.work_address   ELSE jobs.work_address   END,
    publish_date    = CASE WHEN EXCLUDED.publish_date   != '' THEN EXCLUDED.publish_date   ELSE jobs.publish_date   END,
    regular_slots   = CASE WHEN EXCLUDED.regular_slots  != 0  THEN EXCLUDED.regular_slots  ELSE jobs.regular_slots  END,
    alternate_slots = CASE WHEN EXCLUDED.alternate_slots != 0  THEN EXCLUDED.alternate_slots ELSE jobs.alternate_slots END,
    search_text     = CASE WHEN EXCLUDED.search_text    != '' THEN EXCLUDED.search_text    ELSE jobs.search_text    END
"""

# PostgreSQL 批次寫入：VALUES %s 由 execute_values 展開為多列
_BULK_UPSERT_PG  = f"INSERT INTO jobs {_UPSERT_COLS} VALUES %s {_UPSERT_CONFLICT}"
# SQLite / 單筆 fallback
_UPSERT_JOB      = f"INSERT INTO jobs {_UPSERT_COLS} VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) {_UPSERT_CONFLICT}"


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
        create_stmts = [
            _CREATE_LINE_USER_PG,
            _CREATE_TELEGRAM_USER_PG,
            _CREATE_SUBSCRIPTION_PG,
            _CREATE_JOBS_PG,
        ]
    else:
        create_stmts = [
            _CREATE_LINE_USER_SQLITE,
            _CREATE_TELEGRAM_USER_SQLITE,
            _CREATE_SUBSCRIPTION_SQLITE,
            _CREATE_JOBS_SQLITE,
        ]

    # Step 1：建表（一個 transaction）
    with get_conn() as conn:
        for sql in create_stmts:
            _run(conn, sql)
        for idx_sql in _CREATE_JOBS_IDX:
            _run(conn, idx_sql)
        if _IS_POSTGRES:
            _run(conn, "CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Step 2：Migration — 每個 ALTER TABLE 各自獨立 connection，失敗不影響其他
    if _IS_POSTGRES:
        for sql in _ALTER_SUBSCRIPTION + _ALTER_JOBS:
            try:
                with get_conn() as conn:
                    _run(conn, sql)
            except Exception as e:
                logger.debug(f"ALTER 略過（可能已存在）: {e}")

    # Step 3：資料 Migration（v3.2 起 jobs 表已重建，此步驟保留給 subscription 用）

    # Step 4：建立 GIN 索引（在 search_text 欄位確定存在後才執行）
    if _IS_POSTGRES:
        try:
            with get_conn() as conn:
                _run(conn, """
                    DO $$ BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_indexes
                            WHERE tablename='jobs' AND indexname='idx_jobs_search_text'
                        ) THEN
                            CREATE INDEX idx_jobs_search_text
                                ON jobs USING gin(search_text gin_trgm_ops);
                        END IF;
                    END $$
                """)
        except Exception as e:
            logger.warning(f"GIN 索引建立失敗（不影響功能）: {e}")

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
            sub.work_place_codes, sub.work_place_names,
            sub.rank_types, sub.rank_grade_min, sub.rank_grade_max,
            sub.sysnam_grp, sub.sysnam_grp_name, sub.sysnam_names,
            sub.keywords, now,
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
        platform          = d["platform"],
        platform_user_id  = d["platform_user_id"],
        work_place_codes  = d.get("work_place_codes", "") or "",
        work_place_names  = d.get("work_place_names", "") or "",
        rank_types        = d.get("rank_types", "") or "",
        rank_grade_min    = d.get("rank_grade_min", 0) or 0,
        rank_grade_max    = d.get("rank_grade_max", 0) or 0,
        sysnam_grp        = d.get("sysnam_grp", "") or "",
        sysnam_grp_name   = d.get("sysnam_grp_name", "") or "",
        sysnam_names      = d.get("sysnam_names", "") or "",
        keywords          = d.get("keywords", "") or "",
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

def _job_to_tuple(job: Job, now: str) -> tuple:
    """Job 物件 → upsert 用的參數 tuple（DRY：PostgreSQL 和 SQLite 共用）。"""
    return (
        job.job_id, job.title, job.org_name, job.work_place, job.work_place_code,
        job.rank_type, job.rank_type_codes, job.rank_grade_min, job.rank_grade_max,
        job.job_series, job.sysnam_grp, job.regular_slots, job.alternate_slots,
        job.qualifications, job.work_items, job.work_address,
        job.publish_date, job.deadline_start, job.deadline_end,
        job.job_url, job.search_text, now,
    )


def upsert_jobs(jobs: list[Job]) -> None:
    """批次 UPSERT 職缺。
    PostgreSQL：execute_values 單次 SQL（最快）。
    SQLite：executemany 單一 transaction。
    """
    if not jobs:
        return
    now = datetime.now(timezone.utc).isoformat()
    params = [_job_to_tuple(j, now) for j in jobs]

    if _IS_POSTGRES:
        from psycopg2.extras import execute_values
        with get_conn() as conn:
            cur = conn.cursor()
            execute_values(cur, _BULK_UPSERT_PG, params)
    else:
        with get_conn() as conn:
            conn.executemany(_UPSERT_JOB, params)

    logger.info(f"upsert_jobs 完成：{len(jobs)} 筆")


def search_jobs(
    work_place_codes: str = "",
    rank_types: str = "",
    rank_grade_min: int = 0,
    rank_grade_max: int = 0,
    sysnam_grp: str = "",
    sysnam_names: str = "",
    keywords: str = "",
    limit: int = 20,
) -> list[Job]:
    """
    依條件從 jobs 表搜尋有效職缺（deadline_end >= 今日）。

    work_place_codes: 逗號分隔代碼，如 "10,42"（空=不限）
    rank_types: 逗號分隔代碼，如 "2,3"（空=不限）
    rank_grade_min/max: 職等篩選（0=不限）
    sysnam_grp: '' / 'A' / 'B'（'A' 同時包含 sysnam_grp=''）
    sysnam_names: 逗號分隔職系名稱（空=不限）
    keywords: 逗號/空格分隔，多關鍵字 OR 比對（空=不限）

    PostgreSQL：用 pg_trgm similarity 排序；SQLite：用 ILIKE。
    """
    from datetime import date
    today = date.today().isoformat()

    where = ["deadline_end >= ?"]
    params: list = [today]

    # 多地點 IN 比對
    if work_place_codes:
        codes = [c.strip() for c in work_place_codes.split(",") if c.strip()]
        if codes:
            placeholders = ",".join(["?"] * len(codes))
            where.append(f"work_place_code IN ({placeholders})")
            params.extend(codes)

    # 官等代碼 ILIKE（代碼為單數字 1-4，直接用 LIKE '%N%' 安全）
    if rank_types:
        type_codes = [c.strip() for c in rank_types.split(",") if c.strip()]
        if type_codes:
            type_clauses = [f"rank_type_codes LIKE ?" for _ in type_codes]
            where.append(f"({' OR '.join(type_clauses)})")
            params.extend([f"%{c}%" for c in type_codes])

    # 職務列等範圍
    if rank_grade_min > 0:
        where.append("rank_grade_max >= ?")   # 職缺最高職等 >= 使用者最低要求
        params.append(rank_grade_min)
    if rank_grade_max > 0:
        where.append("rank_grade_min <= ?")   # 職缺最低職等 <= 使用者最高要求
        params.append(rank_grade_max)

    # 職系大分類
    if sysnam_grp == "B":
        where.append("sysnam_grp = 'B'")
    elif sysnam_grp == "A":
        where.append("(sysnam_grp = 'A' OR sysnam_grp = '')")

    # 職系細項
    if sysnam_names:
        names = [n.strip() for n in sysnam_names.split(",") if n.strip()]
        if names:
            placeholders = ",".join(["?"] * len(names))
            where.append(f"job_series IN ({placeholders})")
            params.extend(names)

    # 多關鍵字 OR 比對
    kw_list = _split_keywords(keywords)
    if kw_list:
        kw_clauses = [
            "(search_text LIKE ? OR title LIKE ? OR org_name LIKE ?)"
            for _ in kw_list
        ]
        where.append(f"({' OR '.join(kw_clauses)})")
        for kw in kw_list:
            params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%"])

    base_where = " AND ".join(where)

    # PostgreSQL：用 pg_trgm similarity 計分排序
    if _IS_POSTGRES and kw_list:
        score_parts = []
        score_params: list = []
        for kw in kw_list:
            score_parts.append(
                "(similarity(title,?) + similarity(org_name,?) "
                "+ similarity(qualifications,?) + similarity(work_items,?))"
            )
            score_params.extend([kw, kw, kw, kw])
        score_expr = " + ".join(score_parts)
        sql = (
            f"SELECT *, ({score_expr}) AS _score FROM jobs "
            f"WHERE {base_where} "
            f"ORDER BY _score DESC, deadline_end ASC LIMIT ?"
        )
        all_params = tuple(score_params + params + [limit])
    else:
        sql = (
            f"SELECT * FROM jobs WHERE {base_where} "
            f"ORDER BY deadline_end ASC LIMIT ?"
        )
        all_params = tuple(params + [limit])

    with get_conn() as conn:
        rows = _run(conn, sql, all_params).fetchall()

    return [_row_to_job(dict(row)) for row in rows]


def _split_keywords(raw: str) -> list[str]:
    """將逗號/空格/頓號分隔的關鍵字字串拆成 list。"""
    if not raw:
        return []
    return [k for k in re.split(r"[\s、，,]+", raw.strip()) if k]


def _row_to_job(d: dict) -> Job:
    return Job(
        job_id          = d["job_id"],
        title           = d.get("title", ""),
        org_name        = d.get("org_name", ""),
        work_place      = d.get("work_place", ""),
        work_place_code = d.get("work_place_code", ""),
        rank_type       = d.get("rank_type", ""),
        rank_type_codes = d.get("rank_type_codes", "") or "",
        rank_grade_min  = d.get("rank_grade_min", 0) or 0,
        rank_grade_max  = d.get("rank_grade_max", 0) or 0,
        job_series      = d.get("job_series", ""),
        sysnam_grp      = d.get("sysnam_grp", ""),
        regular_slots   = d.get("regular_slots", 0) or 0,
        alternate_slots = d.get("alternate_slots", 0) or 0,
        qualifications  = d.get("qualifications", ""),
        work_items      = d.get("work_items", ""),
        work_address    = d.get("work_address", ""),
        publish_date    = d.get("publish_date", ""),
        deadline_start  = d.get("deadline_start", "") or "",
        deadline_end    = d.get("deadline_end", "") or "",
        job_url         = d.get("job_url", ""),
        search_text     = d.get("search_text", "") or "",
    )


def get_jobs_count() -> int:
    with get_conn() as conn:
        row = _run(conn, "SELECT COUNT(*) AS cnt FROM jobs").fetchone()
    if not row:
        return 0
    return dict(row).get("cnt", 0)


def delete_expired_jobs() -> int:
    """刪除截止日已過的職缺。整批 upsert 完成後呼叫一次。回傳刪除筆數。"""
    from datetime import date
    today = date.today().isoformat()
    with get_conn() as conn:
        cur = _run(
            conn,
            "DELETE FROM jobs WHERE deadline_end != '' AND deadline_end < ?",
            (today,),
        )
        count = cur.rowcount if hasattr(cur, "rowcount") else 0
    logger.info(f"已清除 {count} 筆過期職缺")
    return count
