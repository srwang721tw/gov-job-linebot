"""
每日職缺爬取排程（v3.1）。

排程方式：
  1. APScheduler AsyncIOScheduler：伺服器持續運行時在 02:00 台灣時間自動觸發。
  2. /admin/trigger-crawl 端點：由 cron-job.org 每日打一次，解決 Render free tier
     15 分鐘無流量後 spin down 導致 APScheduler 不執行的問題。

爬取流程（v3.1）：
  1. 固定 is_office=True（只爬「須具公務人員任用資格」職缺）
  2. 抓取全部職缺列表頁（max_pages=0 = 不限）+ 詳細頁
  3. 整批 UPSERT 到 jobs 資料表
  4. 整批完成後一次性刪除截止日已過的職缺
"""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.crawler.scraper import crawl_jobs
from app.db.database import delete_expired_jobs, upsert_jobs
from app.utils.config import MAX_CRAWL_PAGES_SCHEDULED
from app.utils.logger import logger

_scheduler: AsyncIOScheduler | None = None


async def daily_crawl_task() -> int:
    """
    執行一次完整的職缺爬取任務。
    回傳本次抓到的職缺數。
    """
    logger.info("=== 每日職缺爬取開始 ===")
    try:
        # 在執行緒池中執行同步爬蟲（避免 blocking asyncio event loop）
        loop = asyncio.get_event_loop()
        jobs = await loop.run_in_executor(
            None,
            lambda: crawl_jobs(
                is_office=True,          # v3.1: 固定只爬公務人員資格職缺
                fetch_detail=True,
                max_pages=MAX_CRAWL_PAGES_SCHEDULED,
                lookback_days=30,
            ),
        )

        if jobs:
            upsert_jobs(jobs)

        deleted = delete_expired_jobs()
        logger.info(
            f"=== 爬取完成：新增/更新 {len(jobs)} 筆，刪除過期 {deleted} 筆 ==="
        )
        return len(jobs)

    except Exception as e:
        logger.error(f"每日爬取任務失敗：{e}")
        return 0


def start_scheduler() -> None:
    """啟動 APScheduler（在 FastAPI lifespan 呼叫）。"""
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
    _scheduler.add_job(
        daily_crawl_task,
        trigger="cron",
        hour=2,
        minute=0,
        id="daily_crawl",
        name="每日職缺爬取",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("APScheduler 已啟動（每日 02:00 台灣時間執行爬取）")


def stop_scheduler() -> None:
    """停止排程器（在 FastAPI lifespan shutdown 呼叫）。"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler 已停止")
    _scheduler = None
