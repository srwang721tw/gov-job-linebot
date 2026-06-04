"""
查詢服務（v3）：從 jobs 資料表搜尋符合訂閱條件的職缺。

流程：
  1. 讀取訂閱條件
  2. 搜尋 jobs 表（有效職缺 + 條件篩選）
  3. 若 jobs 表為空（尚未排程爬取），fallback 至即時爬取（無詳細頁，速度快）
  4. 格式化為行動版訊息回覆

訊息格式以手機版 LINE / Telegram 顯示為準（短行、適當換行）。
"""
from app.crawler.form_options import get_sysnam_names_for_grp
from app.crawler.scraper import crawl_jobs
from app.db.database import get_jobs_count, get_subscription, search_jobs
from app.models.job import Job
from app.utils.config import TOP_K_RESULTS
from app.utils.logger import logger


# ── 格式化工具 ────────────────────────────────────────────────────────────────

def _short_deadline(deadline_end_iso: str, deadline_raw: str) -> str:
    """
    取截止日的 MM/DD 格式。
    優先用 ISO 日期，fallback 用原始字串。
    '2026-06-03' → '06/03'
    '115/05/30~115/06/03' → '06/03'
    """
    if deadline_end_iso and len(deadline_end_iso) == 10:
        return deadline_end_iso[5:].replace("-", "/")  # 'MM/DD'
    # fallback：從原始字串取截止日
    end = deadline_raw.split("~")[-1].strip()
    parts = end.replace(" ", "").split("/")
    if len(parts) == 3:
        return f"{parts[1]}/{parts[2]}"
    return deadline_raw


def _format_job_block(idx: int, job: Job) -> str:
    """
    單筆職缺的行動版格式：
    【1】股長
    🏛 臺北市政府社會局
    📍 臺北市｜⏰ 截止 06/06
    👤 聘用人員｜📋 薦任
    🔗 https://...
    """
    deadline = _short_deadline(job.deadline_end_iso, job.deadline)

    lines = [f"【{idx}】{job.title}"]
    if job.org_name:
        lines.append(f"🏛 {job.org_name}")

    meta = []
    if job.work_place:
        meta.append(f"📍 {job.work_place}")
    if deadline:
        meta.append(f"⏰ 截止 {deadline}")
    if meta:
        lines.append("｜".join(meta))

    meta2 = []
    if job.person_kind:
        meta2.append(f"👤 {job.person_kind}")
    if job.rank_type:
        meta2.append(f"📋 {job.rank_type}")
    if meta2:
        lines.append("｜".join(meta2))

    if job.job_url:
        lines.append(f"🔗 {job.job_url}")

    return "\n".join(lines)


# ── 主要查詢函式 ──────────────────────────────────────────────────────────────

def handle_user_query(platform: str, platform_user_id: str) -> str:
    sub = get_subscription(platform, platform_user_id)

    if not sub:
        return (
            "👋 尚未設定訂閱條件\n\n"
            "輸入「訂閱」設定查詢條件：\n"
            "• 工作地點\n"
            "• 人員類別\n"
            "• 職系大分類\n"
            "• 職缺關鍵字\n\n"
            "設定完成後，傳任何訊息\n"
            "即可搜尋最新符合條件的職缺！"
        )

    logger.info(
        f"查詢中 {platform}:{platform_user_id[:8]}... | "
        f"地點={sub.work_place_name!r} 職系={sub.sysnam_grp!r} "
        f"關鍵字={sub.title_keyword!r}"
    )

    # 職系名稱清單（for sysnam_grp filter）
    sysnam_names = get_sysnam_names_for_grp(sub.sysnam_grp) if sub.sysnam_grp else None

    jobs: list[Job] = []

    # 先嘗試從 DB 搜尋
    try:
        jobs = search_jobs(
            work_place_code  = sub.work_place_code,
            person_kind_code = sub.person_kind_code,
            sysnam_grp       = sub.sysnam_grp,
            title_keyword    = sub.title_keyword,
            org_keyword      = sub.org_keyword,
            sysnam_names     = sysnam_names,
            limit            = TOP_K_RESULTS * 3,   # 多抓一點，可能有格式問題
        )
    except Exception as e:
        logger.error(f"DB 搜尋錯誤：{e}")

    # jobs 表為空 → fallback 到即時爬取（列表頁，速度快）
    if not jobs:
        total = 0
        try:
            total = get_jobs_count()
        except Exception:
            pass

        if total == 0:
            logger.info("jobs 表為空，改用即時爬取")
            try:
                raw_jobs = crawl_jobs(
                    work_place    = sub.work_place_code,
                    person_kind   = sub.person_kind_code,
                    sysnam_grp    = sub.sysnam_grp,
                    title_keyword = sub.title_keyword,
                    org_keyword   = sub.org_keyword,
                    fetch_detail  = False,
                )
                jobs = raw_jobs
            except Exception as e:
                logger.error(f"即時爬取錯誤：{e}")
                return "⚠️ 查詢時發生錯誤\n請稍後再試。"

    if not jobs:
        cond = f"地點：{sub.work_place_name or '不限'}"
        if sub.person_kind_name:
            cond += f"\n人員：{sub.person_kind_name}"
        if sub.sysnam_grp_name and sub.sysnam_grp_name != "不限":
            cond += f"\n職系：{sub.sysnam_grp_name}"
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

    return header + "\n\n" + "\n\n".join(blocks)
