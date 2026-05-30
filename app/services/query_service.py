from app.crawler.scraper import crawl_jobs
from app.db.database import get_subscription
from app.utils.config import TOP_K_RESULTS
from app.utils.logger import logger


def handle_user_query(user_id: str) -> str:
    """
    讀取使用者訂閱條件 → 即時爬取符合職缺 → 格式化回傳。
    無訂閱時提示設定。
    """
    sub = get_subscription(user_id)

    if not sub:
        return (
            "👋 您尚未設定訂閱條件！\n\n"
            "輸入「訂閱」開始設定查詢條件\n"
            "（工作地點、人員類別、職缺關鍵字），\n"
            "設定完成後每次傳訊息都會自動搜尋\n"
            "符合條件的最新職缺。"
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
        return "⚠️ 查詢時發生錯誤，請稍後再試。"

    if not jobs:
        cond_lines = [f"地點：{sub.work_place_name or '不限'}"]
        if sub.person_kind_name:
            cond_lines.append(f"人員類別：{sub.person_kind_name}")
        if sub.title_keyword:
            cond_lines.append(f"關鍵字：{sub.title_keyword}")
        return (
            "目前沒有找到符合條件的職缺。\n\n"
            "您的條件：\n" + "\n".join(cond_lines) +
            "\n\n輸入「訂閱」可修改條件。"
        )

    top = jobs[:TOP_K_RESULTS]
    loc_label = sub.work_place_name or "全部地區"
    lines = [f"🔍 {loc_label} 最新 {len(top)} 個職缺：\n"]

    for i, job in enumerate(top, 1):
        block = [f"【{i}】{job.title}"]
        if job.agency:
            block.append(f"機關：{job.agency}")
        if job.location:
            block.append(f"地點：{job.location}")
        if job.deadline:
            block.append(f"截止：{job.deadline}")
        if job.detail_url:
            block.append(f"🔗 {job.detail_url}")
        lines.append("\n".join(block))

    return "\n\n".join(lines)
