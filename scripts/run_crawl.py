#!/usr/bin/env python3
"""Crawler entry point for Render Cron Job and local manual runs.

Usage:
    # Direct connection (local machine, Taiwan IP)
    python scripts/run_crawl.py

    # Via Taiwan proxy (Render US server)
    python scripts/run_crawl.py --proxy

    # Crawl only 1 page for a quick smoke test
    MAX_CRAWL_PAGES_SCHEDULED=1 python scripts/run_crawl.py --proxy

When ``--proxy`` is given, the script calls ``get_working_proxy()`` to
select a validated Taiwan proxy from proxynova.com before crawling.
Without ``--proxy``, a direct connection is used (appropriate when the
machine has a Taiwan IP address).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.crawler.scraper import crawl_jobs
from app.db.database import delete_expired_jobs, init_db, upsert_jobs
from app.utils.config import MAX_CRAWL_PAGES_SCHEDULED
from app.utils.logger import logger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy", action="store_true", help="透過 proxynova.com 台灣 proxy 連線（Render 用）")
    args = parser.parse_args()

    logger.info("=== 職缺爬取開始 ===")
    init_db()

    proxy_dict = None
    if args.proxy:
        from app.crawler.proxy_manager import get_working_proxy
        proxy_dict = get_working_proxy()
        if proxy_dict is None:
            logger.error("無可用 proxy，結束")
            return -1
        logger.info(f"使用 proxy: {list(proxy_dict.values())[0]}")
    else:
        logger.info("直接連線（無 proxy）")

    jobs = crawl_jobs(
        proxy_dict=proxy_dict,
        is_office=None,
        fetch_detail=True,
        max_pages=MAX_CRAWL_PAGES_SCHEDULED,
        lookback_days=365,
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
