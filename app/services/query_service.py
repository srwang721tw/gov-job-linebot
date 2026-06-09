"""
查詢服務（v3.2）：從 jobs 資料表搜尋符合訂閱條件的職缺。

流程：
  1. 讀取訂閱條件
  2. 搜尋 jobs 表（有效職缺 + 結構化條件篩選 + 多關鍵字模糊比對）
  3. 格式化為行動版訊息回覆

回傳欄位：職稱、機關名稱、職系、職務列等、工作地點、有效期間、url
  - LINE：純文字 URL
  - Telegram：HTML 超連結（parse_mode='HTML'）
"""
from app.db.database import get_subscription, search_jobs
from app.models.job import Job
from app.utils.config import DETAIL_PAGE_URL, TOP_K_RESULTS
from app.utils.logger import logger


# ── 格式化工具 ────────────────────────────────────────────────────────────────

def _grade_label(grade_min: int, grade_max: int) -> str:
    """
    將職等數字轉為顯示標籤。
    (5, 9) → '5-9職等'
    (9, 9) → '9職等'
    (0, 0) → '不分職等'
    """
    if grade_min == 0 and grade_max == 0:
        return "不分職等"
    if grade_min == grade_max:
        return f"{grade_min}職等"
    return f"{grade_min}-{grade_max}職等"


def _format_period(deadline_start: str, deadline_end: str) -> str:
    """
    格式化有效期間。
    '2026-05-30', '2026-09-30' → '2026-05-30 ~ 2026-09-30'
    '', '2026-09-30'           → '截止 2026-09-30'
    """
    if deadline_start and deadline_end:
        return f"{deadline_start} ~ {deadline_end}"
    if deadline_end:
        return f"截止 {deadline_end}"
    return ""


def _format_job_block(idx: int, job: Job, platform: str = "line") -> str:
    """
    單筆職缺格式：

    【1】職稱
    🏛 機關名稱
    🗂 職系｜📋 職務列等（X-Y職等）
    📍 工作地點｜📅 有效期間
    🔗 url（LINE 純文字 / Telegram HTML 超連結）
    """
    lines = [f"【{idx}】{job.title}"]

    if job.org_name:
        lines.append(f"🏛 {job.org_name}")

    meta2 = []
    if job.job_series:
        meta2.append(f"🗂 {job.job_series}")
    grade = _grade_label(job.rank_grade_min, job.rank_grade_max)
    if grade:
        meta2.append(f"📋 {grade}")
    if meta2:
        lines.append("｜".join(meta2))

    meta3 = []
    if job.work_place:
        meta3.append(f"📍 {job.work_place}")
    period = _format_period(job.deadline_start, job.deadline_end)
    if period:
        meta3.append(f"📅 {period}")
    if meta3:
        lines.append("｜".join(meta3))

    if job.job_url:
        if platform == "telegram":
            lines.append(f'🔗 <a href="{job.job_url}">職缺網址</a>')
        else:
            lines.append(f"🔗 {job.job_url}")

    return "\n".join(lines)


# ── 主要查詢函式 ──────────────────────────────────────────────────────────────

def handle_user_query(
    platform: str,
    platform_user_id: str,
    keyword: str = "",
) -> tuple[str, str]:
    """
    回傳 (message_text, parse_mode)。
    LINE：parse_mode=''（純文字）
    Telegram：parse_mode='HTML'

    keyword：用戶即時輸入的關鍵字（非空時取代訂閱的 keywords 欄位）。
    空字串（/results 指令）→ 使用訂閱中儲存的 keywords。
    """
    sub = get_subscription(platform, platform_user_id)
    parse_mode = "HTML" if platform == "telegram" else ""

    if not sub:
        return (
            "👋 尚未設定訂閱條件\n\n"
            "輸入「訂閱」設定查詢條件：\n"
            "• 工作地點\n"
            "• 官等類別\n"
            "• 職系\n"
            "• 職務列等區間\n"
            "• 關鍵字\n\n"
            "設定完成後，傳任何訊息\n"
            "即可搜尋最新符合條件的職缺！",
            parse_mode,
        )

    # keyword 非空 → 以用戶輸入取代訂閱關鍵字；空 → 沿用訂閱關鍵字
    effective_kw = keyword if keyword else sub.keywords

    logger.info(
        f"查詢中 {platform}:{platform_user_id[:8]}... | "
        f"地點={sub.work_place_names!r} 職系={sub.sysnam_grp!r} "
        f"關鍵字={effective_kw!r}"
    )

    jobs: list[Job] = []
    try:
        jobs = search_jobs(
            work_place_codes = sub.work_place_codes,
            rank_types       = sub.rank_types,
            rank_grade_min   = sub.rank_grade_min,
            rank_grade_max   = sub.rank_grade_max,
            sysnam_grp       = sub.sysnam_grp,
            sysnam_names     = sub.sysnam_names,
            keywords         = effective_kw,
            limit            = TOP_K_RESULTS * 3,
        )
    except Exception as e:
        logger.error(f"DB 搜尋錯誤：{e}")
        return "⚠️ 查詢時發生錯誤，請稍後再試。", parse_mode

    if not jobs:
        cond = _build_cond_summary(sub)
        return (
            "😔 沒有找到符合條件的職缺\n\n"
            f"目前條件：\n{cond}\n\n"
            "職缺資料每日更新，請稍後再查。\n"
            "輸入「訂閱」可修改條件。",
            parse_mode,
        )

    top = jobs[:TOP_K_RESULTS]
    loc_label = sub.work_place_names.replace(",", "、") if sub.work_place_names else "全部地區"
    header = f"🔍 {loc_label}｜找到 {len(jobs)} 個職缺\n（顯示前 {len(top)} 筆）"
    blocks = [_format_job_block(i + 1, job, platform) for i, job in enumerate(top)]

    footer = f"\n\n💻 查看全部職缺（可篩選/排序）：\n{DETAIL_PAGE_URL}"
    return header + "\n\n" + "\n\n".join(blocks) + footer, parse_mode


def _build_cond_summary(sub) -> str:
    """建立訂閱條件摘要字串（用於「找不到職缺」訊息）。"""
    lines = []
    lines.append(f"地點：{sub.work_place_names.replace(',', '、') or '不限'}")
    if sub.rank_types:
        type_map = {"1": "簡任", "2": "薦任", "3": "委任", "4": "其他"}
        names = [type_map.get(c, c) for c in sub.rank_types.split(",") if c]
        lines.append(f"官等：{'、'.join(names)}")
    if sub.rank_grade_min or sub.rank_grade_max:
        lines.append(f"職等：{_grade_label(sub.rank_grade_min, sub.rank_grade_max)}")
    if sub.sysnam_grp_name and sub.sysnam_grp_name != "不限":
        lines.append(f"職系：{sub.sysnam_grp_name}")
    if sub.sysnam_names:
        lines.append(f"職系細項：{sub.sysnam_names.replace(',', '、')}")
    if sub.keywords:
        lines.append(f"關鍵字：{sub.keywords}")
    return "\n".join(lines)
