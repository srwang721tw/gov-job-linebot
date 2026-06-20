"""Job query pipeline: subscription → database search → formatted reply.

Flow:
    1. Load the user's subscription from the database.
    2. Call ``search_jobs()`` with all subscription filters applied.
    3. Format the top-K results as a platform-appropriate chat message.

Platform differences are handled only at the formatting layer:
    - LINE: plain-text URLs.
    - Telegram: HTML ``<a href>`` anchor tags (``parse_mode="HTML"``).

The optional ``keyword`` argument in ``handle_user_query`` lets an
ad-hoc keyword override the subscription's saved keywords for a single
query — used when a user types free text instead of a command.
"""
from app.db.database import get_subscription, search_jobs
from app.models.job import Job
from app.utils.config import DETAIL_PAGE_URL, TOP_K_RESULTS
from app.utils.formatting import comma_to_jap, grade_label, rank_names
from app.utils.logger import logger


def _format_period(deadline_start: str, deadline_end: str) -> str:
    """Format an application period as a human-readable date string.

    Args:
        deadline_start: ISO start date, or ``""`` if not available.
        deadline_end: ISO end date (deadline).

    Returns:
        ``"START ~ END"`` when both dates are present, ``"截止 END"``
        when only the end date is available, or ``""`` if both are empty.

    Example:
        >>> _format_period("2026-05-30", "2026-09-30")
        '2026-05-30 ~ 2026-09-30'
        >>> _format_period("", "2026-09-30")
        '截止 2026-09-30'
    """
    if deadline_start and deadline_end:
        return f"{deadline_start} ~ {deadline_end}"
    if deadline_end:
        return f"截止 {deadline_end}"
    return ""


def _format_job_block(idx: int, job: Job, platform: str = "line") -> str:
    """Format a single job posting as a multi-line chat message block.

    Layout::

        【1】Job Title
        🏛 Agency Name
        🗂 Job Series ｜ 📋 Grade Range
        📍 Location ｜ 📅 Deadline
        🔗 URL  ← plain text for LINE, HTML anchor for Telegram

    Args:
        idx: 1-based display index shown in the header.
        job: ``Job`` model instance to format.
        platform: ``"line"`` (default) or ``"telegram"``.

    Returns:
        Multi-line string ready to send as a chat message.
    """
    lines = [f"【{idx}】{job.title}"]

    if job.org_name:
        lines.append(f"🏛 {job.org_name}")

    meta2 = []
    if job.job_series:
        meta2.append(f"🗂 {job.job_series}")
    grade = grade_label(job.rank_grade_min, job.rank_grade_max)
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
    """Search jobs matching the user's subscription and return a formatted reply.

    If ``keyword`` is provided it overrides the subscription's saved
    keywords for this query only (ad-hoc search).  An empty ``keyword``
    uses the subscription's stored keywords (triggered by ``/results``).

    Args:
        platform: ``"line"`` or ``"telegram"``.
        platform_user_id: Platform-specific user identifier.
        keyword: Ad-hoc keyword override; ``""`` uses subscription keywords.

    Returns:
        Tuple ``(message_text, parse_mode)`` where ``parse_mode`` is
        ``"HTML"`` for Telegram and ``""`` for LINE.
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
    loc_label = comma_to_jap(sub.work_place_names) if sub.work_place_names else "全部地區"
    header = f"🔍 {loc_label}｜找到 {len(jobs)} 個職缺\n（顯示前 {len(top)} 筆）"
    blocks = [_format_job_block(i + 1, job, platform) for i, job in enumerate(top)]

    footer = f"\n\n💻 查看全部職缺（可篩選/排序）：\n{DETAIL_PAGE_URL}"
    return header + "\n\n" + "\n\n".join(blocks) + footer, parse_mode


def _build_cond_summary(sub) -> str:
    """Build a human-readable summary of the active subscription filters.

    Used in the "no results found" reply to show the user which filters
    are currently applied.

    Args:
        sub: ``Subscription`` model instance.

    Returns:
        Newline-separated string of active filter conditions.
    """
    lines = []
    lines.append(f"地點：{comma_to_jap(sub.work_place_names) or '不限'}")
    if sub.rank_types:
        lines.append(f"官等：{'、'.join(rank_names(sub.rank_types))}")
    if sub.rank_grade_min or sub.rank_grade_max:
        lines.append(f"職等：{grade_label(sub.rank_grade_min, sub.rank_grade_max)}")
    if sub.sysnam_grp_name and sub.sysnam_grp_name != "不限":
        lines.append(f"職系：{sub.sysnam_grp_name}")
    if sub.sysnam_names:
        lines.append(f"職系細項：{comma_to_jap(sub.sysnam_names)}")
    if sub.keywords:
        lines.append(f"關鍵字：{sub.keywords}")
    return "\n".join(lines)
