#!/usr/bin/env python3
"""
生產環境爬蟲腳本（供 GitHub Actions 排程使用）。

功能：
  1. 從 DGPA 爬取全部公務員任用資格職缺（is_office=True）
  2. 含詳細頁（qualifications, work_items, search_text）
  3. 整批 UPSERT 至 Neon PostgreSQL
  4. 刪除截止日已過的職缺

用法：
  DATABASE_URL=postgresql://... python scripts/run_crawl.py
  MAX_CRAWL_PAGES_SCHEDULED=1 python scripts/run_crawl.py  # 測試用（只抓 1 頁）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.crawler.scraper import crawl_jobs
from app.db.database import delete_expired_jobs, init_db, upsert_jobs
from app.utils.config import MAX_CRAWL_PAGES_SCHEDULED
from app.utils.logger import logger


def main() -> int:
    logger.info("=== 每日職缺爬取開始（GitHub Actions）===")

    # 初始化資料庫（確保資料表與欄位存在）
    init_db()

    # 爬取職缺
    jobs = crawl_jobs(
        is_office=True,
        fetch_detail=True,
        max_pages=MAX_CRAWL_PAGES_SCHEDULED,  # 0 = 不限（抓全部）
        lookback_days=30,
    )

    if not jobs:
        logger.warning("爬取結果為空，不更新資料庫")
        return 0

    upsert_jobs(jobs)
    deleted = delete_expired_jobs()

    logger.info(
        f"=== 爬取完成：新增/更新 {len(jobs)} 筆，刪除過期 {deleted} 筆 ==="
    )
    return len(jobs)


if __name__ == "__main__":
    count = main()
    sys.exit(0 if count >= 0 else 1)
