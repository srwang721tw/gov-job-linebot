#!/usr/bin/env python3
"""
爬蟲完整測試腳本（v3）
驗證：
  1. 列表頁解析（職稱、機關、地點、截止日、連結）
  2. 關鍵字搜尋功能
  3. 詳細頁抓取（工作說明、應徵條件、聯絡方式等）
  4. 新參數：sysnam_grp、chk_types、is_office

用法：
    python scripts/test_crawl.py
    MAX_CRAWL_PAGES=1 python scripts/test_crawl.py
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


# ── 測試 1：列表頁（無詳細頁） ─────────────────────────────────────────────
print_separator("測試 1：列表頁解析（不限條件，1頁）")
jobs = crawl_jobs(max_pages=1, fetch_detail=False)
print(f"✅ 抓到 {len(jobs)} 筆\n")

for i, j in enumerate(jobs[:3], 1):
    print(f"【{i}】{j.title}")
    print(f"   機關：{j.org_name}")
    print(f"   地點：{j.work_place}（代碼：{j.work_place_code}）")
    print(f"   官等：{j.rank_type}｜職系：{j.job_series}（{j.sysnam_grp}類）")
    print(f"   截止：{j.deadline}（ISO：{j.deadline_end_iso}）")
    print(f"   連結：{j.job_url}")
    print()

# ── 測試 2：關鍵字搜尋 ────────────────────────────────────────────────────
print_separator("測試 2：關鍵字搜尋（無詳細頁）")
for kw in ["採購", "資訊", "行政"]:
    results = crawl_jobs(title_keyword=kw, max_pages=1, fetch_detail=False)
    status = "✅" if results else "⚠️ 無結果"
    sample = f"→ {results[0].title}" if results else ""
    print(f"  「{kw}」：{len(results)} 筆 {status} {sample}")

# ── 測試 3：sysnam_grp 篩選 ───────────────────────────────────────────────
print_separator("測試 3：職系大分類篩選")
for grp, label in [("A", "行政類"), ("B", "技術類")]:
    results = crawl_jobs(sysnam_grp=grp, max_pages=1, fetch_detail=False)
    sample = f"→ {results[0].title}" if results else ""
    print(f"  {label}（{grp}）：{len(results)} 筆 {sample}")

# ── 測試 4：職缺類別篩選 ──────────────────────────────────────────────────
print_separator("測試 4：職缺類別（is_office）")
for flag, label in [(True, "須具公務員資格"), (False, "不具公務員資格")]:
    results = crawl_jobs(is_office=flag, max_pages=1, fetch_detail=False)
    sample = f"→ {results[0].title}" if results else ""
    print(f"  {label}：{len(results)} 筆 {sample}")

# ── 測試 5：詳細頁抓取（第一筆） ─────────────────────────────────────────
print_separator("測試 5：詳細頁內容（抓第一筆的詳細頁）")
if jobs:
    session = requests.Session()
    detail = fetch_job_detail(session, jobs[0].job_url)

    if detail:
        print(f"✅ 詳細頁解析成功\n")
        print(f"   職稱：{detail.get('title', '─')}")
        print(f"   機關：{detail.get('org_name', '─')}")
        print(f"   人員：{detail.get('person_kind', '─')}")
        print(f"   官等：{detail.get('rank_type', '─') or '（未填）'}")
        print(f"   職系：{detail.get('job_series', '─')}")
        print(f"   截止：{detail.get('deadline_raw', '─')}")
        desc = detail.get("work_items", "")
        req  = detail.get("qualifications", "")
        print(f"\n   工作說明（前80字）：\n   {desc[:80]}...")
        print(f"\n   應徵條件（前80字）：\n   {req[:80]}...")
        print(f"\n   應徵方式：{detail.get('apply_method', '─')}")
    else:
        print("❌ 詳細頁解析失敗")
else:
    print("⚠️ 無職缺可測試")

# ── 測試 6：完整 Job 物件（列表 + 詳細頁合併） ───────────────────────────
print_separator("測試 6：完整 Job 物件（fetch_detail=True，1筆）")
full_jobs = crawl_jobs(max_pages=1, fetch_detail=True)
if full_jobs:
    j = full_jobs[0]
    print(f"✅ 建立 Job 物件成功")
    print(f"   job_id:        {j.job_id}")
    print(f"   title:         {j.title}")
    print(f"   org_name:      {j.org_name}")
    print(f"   work_place:    {j.work_place}（code: {j.work_place_code}）")
    print(f"   person_kind:   {j.person_kind}（code: {j.person_kind_code}）")
    print(f"   rank_type:     {j.rank_type}")
    print(f"   job_series:    {j.job_series}（grp: {j.sysnam_grp}）")
    print(f"   deadline_end:  {j.deadline_end_iso}")
    print(f"   work_items:    {j.work_items[:60]}...")
else:
    print("⚠️ 無職缺可測試")

print_separator()
print("測試完成")
