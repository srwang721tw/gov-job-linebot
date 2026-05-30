"""
查詢服務：讀取使用者訂閱條件 → 即時爬取 DGPA → 格式化為 LINE 訊息。
訊息格式以手機版 LINE 顯示為準（短行、適當換行）。
"""
import re

from app.crawler.scraper import crawl_jobs
from app.db.database import get_subscription
from app.utils.config import TOP_K_RESULTS
from app.utils.logger import logger


# ── 格式化工具 ────────────────────────────────────────────────────────────────

def _clean_location(loc: str) -> str:
    """移除 DGPA 地點代碼前綴：'42-臺中市' → '臺中市'"""
    m = re.match(r"^\d{1,2}-(.+)$", loc.strip())
    return m.group(1) if m else loc.strip()


def _short_deadline(deadline: str) -> str:
    """
    從截止日字串取出結束日並轉為 MM/DD 格式。
    '115/05/30~115/06/03' → '06/03'
    '115/06/03'           → '06/03'
    """
    end = deadline.split("~")[-1].strip()
    parts = end.replace(" ", "").split("/")
    if len(parts) == 3:
        return f"{parts[1]}/{parts[2]}"
    return deadline


def _format_job_block(idx: int, job) -> str:
    """
    單筆職缺的行動版格式：
    【1】股長
    🏛 臺北市政府社會局
    📍 臺北市｜⏰ 截止 06/06
    🔗 https://...
    """
    loc      = _clean_location(job.location) if job.location else ""
    deadline = _short_deadline(job.deadline) if job.deadline else ""

    lines = [f"【{idx}】{job.title}"]
    if job.agency:
        lines.append(f"🏛 {job.agency}")

    meta = []
    if loc:
        meta.append(f"📍 {loc}")
    if deadline:
        meta.append(f"⏰ 截止 {deadline}")
    if meta:
        lines.append("｜".join(meta))

    if job.detail_url:
        lines.append(f"🔗 {job.detail_url}")

    return "\n".join(lines)


# ── 主要查詢函式 ──────────────────────────────────────────────────────────────

def handle_user_query(user_id: str) -> str:
    sub = get_subscription(user_id)

    if not sub:
        return (
            "👋 尚未設定訂閱條件\n\n"
            "輸入「訂閱」設定查詢條件：\n"
            "• 工作地點\n"
            "• 人員類別\n"
            "• 職缺關鍵字\n\n"
            "設定完成後，傳任何訊息\n"
            "即可搜尋最新符合條件的職缺！"
        )

    logger.info(
        f"查詢中 user={user_id[:8]}... | "
        f"地點={sub.work_place_name!r} 關鍵字={sub.title_keyword!r}"
    )

    try:
        jobs = crawl_jobs(
            work_place=sub.work_place_code,
            person_kind=sub.person_kind_code,
            title_keyword=sub.title_keyword,
            org_keyword=sub.org_keyword,
        )
    except Exception as e:
        logger.error(f"爬蟲錯誤：{e}")
        return "⚠️ 查詢時發生錯誤\n請稍後再試。"

    if not jobs:
        cond = f"地點：{sub.work_place_name or '不限'}"
        if sub.person_kind_name:
            cond += f"\n人員：{sub.person_kind_name}"
        if sub.title_keyword:
            cond += f"\n關鍵字：{sub.title_keyword}"
        return (
            "😔 沒有找到符合條件的職缺\n\n"
            f"目前條件：\n{cond}\n\n"
            "輸入「訂閱」可修改條件。"
        )

    top = jobs[:TOP_K_RESULTS]
    loc_label = sub.work_place_name or "全部地區"

    header = f"🔍 {loc_label}｜找到 {len(jobs)} 個職缺\n（顯示前 {len(top)} 筆）"

    blocks = [_format_job_block(i + 1, job) for i, job in enumerate(top)]

    # 每筆之間用空行分隔，手機上視覺清晰
    return header + "\n\n" + "\n\n".join(blocks)
