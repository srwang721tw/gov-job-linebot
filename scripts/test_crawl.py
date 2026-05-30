#!/usr/bin/env python3
"""
爬蟲完整測試腳本
驗證：
  1. 列表頁解析（職稱、機關、地點、截止日、連結）
  2. 關鍵字搜尋功能
  3. 詳細頁抓取（工作說明、應徵條件、聯絡方式等）
  4. 地點代碼清理（'42-臺中市' → '臺中市'）

用法：
    python scripts/test_crawl.py
    MAX_CRAWL_PAGES=1 python scripts/test_crawl.py
"""
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from app.crawler.scraper import crawl_jobs, fetch_job_detail, HEADERS
from app.utils.logger import logger


def clean_location(loc: str) -> str:
    m = re.match(r"^\d{1,2}-(.+)$", loc.strip())
    return m.group(1) if m else loc.strip()


def short_deadline(deadline: str) -> str:
    end = deadline.split("~")[-1].strip()
    parts = end.replace(" ", "").split("/")
    if len(parts) == 3:
        return f"{parts[1]}/{parts[2]}"
    return deadline


def print_separator(title: str = ""):
    print(f"\n{'─' * 50}")
    if title:
        print(f"  {title}")
        print(f"{'─' * 50}")


# ── 測試 1：列表頁 ─────────────────────────────────────────────────────────────
print_separator("測試 1：列表頁解析（不限條件，1頁）")
jobs = crawl_jobs(max_pages=1)
print(f"✅ 抓到 {len(jobs)} 筆\n")

for i, j in enumerate(jobs[:3], 1):
    print(f"【{i}】{j.title}")
    print(f"   機關：{j.agency}")
    print(f"   地點：{clean_location(j.location)}")
    print(f"   截止：{short_deadline(j.deadline)}")
    print(f"   連結：{j.detail_url}")
    print()

# ── 測試 2：關鍵字搜尋 ────────────────────────────────────────────────────────
print_separator("測試 2：關鍵字搜尋")
for kw in ["採購", "資訊", "行政"]:
    results = crawl_jobs(title_keyword=kw, max_pages=1)
    status = "✅" if results else "⚠️ 無結果"
    sample = f"→ {results[0].title}" if results else ""
    print(f"  「{kw}」：{len(results)} 筆 {status} {sample}")

# ── 測試 3：詳細頁抓取 ────────────────────────────────────────────────────────
print_separator("測試 3：詳細頁內容（抓第一筆的詳細頁）")
if jobs:
    session = requests.Session()
    detail = fetch_job_detail(session, jobs[0].detail_url)

    if detail:
        print(f"✅ 詳細頁解析成功\n")
        print(f"   職稱：{detail.get('title', '─')}")
        print(f"   機關：{detail.get('agency', '─')}")
        print(f"   地點：{clean_location(detail.get('location', ''))}")
        print(f"   人員：{detail.get('person_kind', '─')}")
        print(f"   列等：{detail.get('rank_type', '─') or '（未填）'}")
        print(f"   職系：{detail.get('job_series', '─')}")
        print(f"   截止：{detail.get('deadline', '─')}")
        desc = detail.get("description", "")
        req  = detail.get("requirement", "")
        print(f"\n   工作說明（前80字）：\n   {desc[:80]}...")
        print(f"\n   應徵條件（前80字）：\n   {req[:80]}...")
        print(f"\n   應徵方式：{detail.get('apply_method', '─')}")
    else:
        print("❌ 詳細頁解析失敗")
else:
    print("⚠️ 無職缺可測試")

print_separator()
print("測試完成")
