#!/usr/bin/env python3
"""
煙霧測試：用關鍵字爬取職缺並印出前幾筆結果。
用法：
    python scripts/test_crawl.py
    MAX_CRAWL_PAGES=1 python scripts/test_crawl.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.crawler.scraper import crawl_jobs
from app.utils.logger import logger

if __name__ == "__main__":
    logger.info("開始測試爬蟲（1 頁）...")

    # 測試：不限條件，只爬 1 頁
    jobs = crawl_jobs(max_pages=1)
    logger.info(f"共抓到 {len(jobs)} 筆")

    for j in jobs[:3]:
        print(
            f"\n職稱：{j.title}\n"
            f"機關：{j.agency}\n"
            f"地點：{j.location}\n"
            f"截止：{j.deadline}\n"
            f"連結：{j.detail_url}"
        )

    # 測試：帶關鍵字
    logger.info("\n測試關鍵字「新聞」...")
    news_jobs = crawl_jobs(title_keyword="新聞", max_pages=1)
    logger.info(f"關鍵字「新聞」找到 {len(news_jobs)} 筆")
    for j in news_jobs[:2]:
        print(f"  - {j.title}（{j.agency}）")
