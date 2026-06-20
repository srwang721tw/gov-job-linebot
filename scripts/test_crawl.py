#!/usr/bin/env python3
"""Crawler smoke-test script — validates scraping logic without writing to the DB.

Runs four validation phases:
    1. List-page parsing: title, agency, location, rank, deadline, URL.
    2. Rank-field derivation: ``rank_grade_min/max``, ``rank_type_codes``.
    3. Detail-page fetching: work_items, qualifications, work_address.
    4. Full ``Job`` object construction including ``search_text``.

Usage:
    python scripts/test_crawl.py
    MAX_CRAWL_PAGES=1 python scripts/test_crawl.py   # faster 1-page run
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from app.crawler.scraper import crawl_jobs, fetch_job_detail, HEADERS
from app.utils.logger import logger


def print_separator(title: str = ""):
    print(f"\n{'─' * 50}")
    if title:
        print(f"  {title}")
        print(f"{'─' * 50}")


# ── 測試 1：列表頁（無詳細頁）──────────────────────────────────────────────
print_separator("測試 1：列表頁解析（is_office=True，1頁）")
jobs = crawl_jobs(is_office=True, max_pages=1, fetch_detail=False)
print(f"✅ 抓到 {len(jobs)} 筆\n")

for i, j in enumerate(jobs[:3], 1):
    print(f"【{i}】{j.title}")
    print(f"   機關：{j.org_name}")
    print(f"   地點：{j.work_place}（代碼：{j.work_place_code}）")
    print(f"   官等：{j.rank_type}")
    print(f"   官等代碼：{j.rank_type_codes}｜職等：{j.rank_grade_min}-{j.rank_grade_max}")
    print(f"   職系：{j.job_series}（{j.sysnam_grp}類）")
    print(f"   deadline_start：{j.deadline_start}")
    print(f"   deadline_end：{j.deadline_end}")
    print(f"   連結：{j.job_url}")
    print()

# ── 測試 2：職系大分類篩選 ───────────────────────────────────────────────
print_separator("測試 2：職系大分類篩選")
for grp, label in [("A", "行政類"), ("B", "技術類")]:
    results = crawl_jobs(sysnam_grp=grp, max_pages=1, fetch_detail=False)
    sample = f"→ {results[0].title}" if results else ""
    print(f"  {label}（{grp}）：{len(results)} 筆 {sample}")

# ── 測試 3：詳細頁抓取（第一筆）────────────────────────────────────────
print_separator("測試 3：詳細頁內容（抓第一筆的詳細頁）")
if jobs:
    session = requests.Session()
    detail = fetch_job_detail(session, jobs[0].job_url)

    if detail:
        print(f"✅ 詳細頁解析成功\n")
        print(f"   職稱：{detail.get('title', '─')}")
        print(f"   機關：{detail.get('org_name', '─')}")
        print(f"   官等：{detail.get('rank_type', '─') or '（未填）'}")
        print(f"   職系：{detail.get('job_series', '─')}")
        print(f"   date_range：{detail.get('date_range', '─')}")
        desc = detail.get("work_items", "")
        req  = detail.get("qualifications", "")
        print(f"\n   工作說明（前80字）：\n   {desc[:80]}...")
        print(f"\n   應徵條件（前80字）：\n   {req[:80]}...")
    else:
        print("❌ 詳細頁解析失敗")
else:
    print("⚠️ 無職缺可測試")

# ── 測試 4：完整 Job 物件（列表 + 詳細頁合併）──────────────────────────
print_separator("測試 4：完整 Job 物件（fetch_detail=True，1頁）")
full_jobs = crawl_jobs(is_office=True, max_pages=1, fetch_detail=True)
if full_jobs:
    j = full_jobs[0]
    print(f"✅ 建立 Job 物件成功")
    print(f"   job_id:          {j.job_id}")
    print(f"   title:           {j.title}")
    print(f"   org_name:        {j.org_name}")
    print(f"   work_place:      {j.work_place}（code: {j.work_place_code}）")
    print(f"   rank_type:       {j.rank_type}")
    print(f"   rank_type_codes: {j.rank_type_codes}")
    print(f"   rank_grade:      {j.rank_grade_min} ~ {j.rank_grade_max}")
    print(f"   job_series:      {j.job_series}（grp: {j.sysnam_grp}）")
    print(f"   deadline_start:  {j.deadline_start}")
    print(f"   deadline_end:    {j.deadline_end}")
    print(f"   search_text（前100字）：{j.search_text[:100]}...")
    print(f"   work_items（前60字）：{j.work_items[:60]}...")
else:
    print("⚠️ 無職缺可測試")

print_separator()
print("測試完成")
