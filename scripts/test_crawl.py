#!/usr/bin/env python3
"""Smoke test — run the crawler and print the first result."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.crawler.scraper import crawl_all_jobs
from app.utils.logger import logger

if __name__ == "__main__":
    logger.info("Starting test crawl...")
    jobs = crawl_all_jobs()
    logger.info(f"Total jobs crawled: {len(jobs)}")
    if jobs:
        j = jobs[0]
        print(f"\nSample job:\n  title={j.title}\n  agency={j.agency}"
              f"\n  location={j.location}\n  deadline={j.deadline}"
              f"\n  url={j.detail_url}")
