#!/usr/bin/env python3
"""
本機爬蟲腳本（v3.2）。

功能：
  1. 從 DGPA 全量爬取所有職缺（不篩選職缺類別）
  2. 含詳細頁（qualifications, work_items, search_text）
  3. 整批 UPSERT 至 Neon PostgreSQL（job_id 為 PK，存在則 UPDATE，不存在則 INSERT）
  4. 刪除截止日已過的職缺

用法（本機執行，需在 .env 設定 DATABASE_URL）：
  python scripts/run_crawl.py
  MAX_CRAWL_PAGES_SCHEDULED=1 python scripts/run_crawl.py  # 測試：只爬 1 頁

排程建議（crontab）：
  0 2 * * * cd /path/to/gov-job-linebot && python3 scripts/run_crawl.py >> /tmp/gov_job_crawl.log 2>&1
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.crawler.scraper import crawl_jobs
from app.db.database import delete_expired_jobs, init_db, upsert_jobs
from app.utils.config import MAX_CRAWL_PAGES_SCHEDULED
from app.utils.logger import logger


def main() -> int:
    logger.info("=== 職缺爬取開始 ===")

    # 初始化資料庫（確保資料表與欄位存在）
    init_db()

    # 全量爬取（不篩選職缺類別、不限頁數、往回一年）
    jobs = crawl_jobs(
        is_office=None,       # 不篩選，爬取所有職缺（含須具資格與不須資格）
        fetch_detail=True,    # 含詳細頁資料
        max_pages=MAX_CRAWL_PAGES_SCHEDULED,  # 0 = 不限（抓全部）
        lookback_days=365,    # 往回一年，涵蓋所有有效職缺
    )

    if not jobs:
        logger.warning("爬取結果為空，不更新資料庫")
        return 0

    upsert_jobs(jobs)
    deleted = delete_expired_jobs()

    logger.info(f"=== 爬取完成：新增/更新 {len(jobs)} 筆，刪除過期 {deleted} 筆 ===")
    return len(jobs)


if __name__ == "__main__":
    count = main()
    sys.exit(0 if count >= 0 else 1)
