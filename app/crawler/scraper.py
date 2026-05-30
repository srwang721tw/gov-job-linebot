"""
行政院人事行政總處事求人機關徵才系統 爬蟲
目標：https://web3.dgpa.gov.tw/want03front/AP/WANTF00001.ASPX
網站類型：ASP.NET WebForms，需攜帶 __VIEWSTATE 跨頁 POST（無 __EVENTVALIDATION）。

只抓列表頁資料（職稱、機關、地點、截止日、連結），不抓詳細頁，以加快即時回應。
"""
import re
import time
from datetime import datetime, timezone, timedelta
from typing import List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.models.job import Job
from app.utils.config import CRAWLER_BASE_URL, CRAWLER_LIST_PAGE, MAX_CRAWL_PAGES
from app.utils.logger import logger

LIST_URL = CRAWLER_BASE_URL + CRAWLER_LIST_PAGE
DETAIL_BASE = CRAWLER_BASE_URL + "/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": LIST_URL,
}


# ── 日期工具 ──────────────────────────────────────────────────────────────────

def _roc_today() -> str:
    """回傳今日民國年日期，格式 YYYMMDD（例：1150526）。"""
    today = datetime.now(timezone(timedelta(hours=8)))
    return f"{today.year - 1911}{today.month:02d}{today.day:02d}"


def _roc_days_ago(days: int) -> str:
    d = datetime.now(timezone(timedelta(hours=8))) - timedelta(days=days)
    return f"{d.year - 1911}{d.month:02d}{d.day:02d}"


# ── ASP.NET Form 工具 ─────────────────────────────────────────────────────────

def _extract_hidden_fields(soup: BeautifulSoup) -> dict:
    """蒐集頁面中所有 ASP.NET 隱藏欄位（VIEWSTATE 等）。"""
    fields = {}
    for inp in soup.find_all("input", type="hidden"):
        name = inp.get("name")
        if name:
            fields[name] = inp.get("value", "")
    return fields


def _search_payload(
    hidden: dict,
    date_from: str,
    date_to: str,
    work_place: str = "",
    person_kind: str = "",
    sysnam: str = "",
    title_keyword: str = "",
    org_keyword: str = "",
    event_target: str = "",
) -> dict:
    """建立查詢或分頁 POST 的 payload。"""
    return {
        **hidden,
        "__EVENTTARGET":   event_target,
        "__EVENTARGUMENT": "",
        "__LASTFOCUS":     "",
        "ctl00$ContentPlaceHolder1$drpPERSON_KIND":        person_kind,
        "ctl00$ContentPlaceHolder1$drpWORK_PLACE":         work_place,
        "ctl00$ContentPlaceHolder1$drpSYSNAM_grp":         "",
        "ctl00$ContentPlaceHolder1$drpSYSNAM":             sysnam,
        "ctl00$ContentPlaceHolder1$drpSPECIAL_CONDITIONS": "",
        "ctl00$ContentPlaceHolder1$txtTITLE":              title_keyword,
        "ctl00$ContentPlaceHolder1$txbORG_NAME":           org_keyword,
        "ctl00$ContentPlaceHolder1$DATE_FROM":             date_from,
        "ctl00$ContentPlaceHolder1$DATE_TO":               date_to,
        # 第一次查詢才送出按鈕參數，分頁時不送
        **({"ctl00$ContentPlaceHolder1$btnQUERY": "查詢"} if not event_target else {}),
    }


# ── 列表頁解析 ────────────────────────────────────────────────────────────────

def _text(tag) -> str:
    return tag.get_text(strip=True) if tag else ""


def _parse_list_page(soup: BeautifulSoup) -> List[dict]:
    """從 GridView 解析職缺摘要列。"""
    table = soup.find("table", id="ctl00_ContentPlaceHolder1_gvMAIN")
    if not table:
        return []

    raw_jobs = []
    for row in table.find_all("tr"):
        main_div = row.find("div", class_="cursor_point")
        if not main_div:
            continue

        title  = _text(main_div.find("div", class_=lambda c: c and "md_block_bold" in c))
        agency = _text(main_div.find("div", class_=lambda c: c and "md_red" in c))

        # 桌面版隱藏 div 依序：列等、職系、地點、截止日
        md_hides = [
            d for d in main_div.find_all("div")
            if "md_hide" in (d.get("class") or [])
            and "md_show" not in (d.get("class") or [])
        ]
        rank_type  = _text(md_hides[0]) if len(md_hides) > 0 else ""
        job_series = _text(md_hides[1]) if len(md_hides) > 1 else ""
        location   = _text(md_hides[2]) if len(md_hides) > 2 else ""
        deadline   = _text(md_hides[3]) if len(md_hides) > 3 else ""

        onclick = main_div.get("onclick", "")
        m = re.search(r"window\.open\('([^']+)'", onclick)
        detail_path = m.group(1) if m else ""
        detail_url  = urljoin(DETAIL_BASE, detail_path) if detail_path else ""

        id_m   = re.search(r"work_id=([^&]+)", detail_path)
        job_id = id_m.group(1) if id_m else detail_path

        if not title or not job_id:
            continue

        raw_jobs.append({
            "job_id":     job_id,
            "title":      title,
            "agency":     agency,
            "location":   location,
            "job_series": job_series,
            "rank_type":  rank_type,
            "deadline":   deadline.replace("有效期間：", "").strip(),
            "detail_url": detail_url,
        })

    return raw_jobs


def _has_next_page(soup: BeautifulSoup) -> bool:
    for a in soup.find_all("a", href=re.compile(r"doPostBack")):
        if "btnNEXT" in a.get("href", "") or "下一頁" in a.get_text():
            return True
    return False


# ── 主要爬取函式 ──────────────────────────────────────────────────────────────

def crawl_jobs(
    work_place: str = "",
    person_kind: str = "",
    sysnam: str = "",
    title_keyword: str = "",
    org_keyword: str = "",
    lookback_days: int = 30,
    max_pages: int = MAX_CRAWL_PAGES,
) -> List[Job]:
    """
    依條件爬取職缺（只抓列表頁，不抓詳細頁，回應較快）。

    Args:
        work_place:    drpWORK_PLACE 的值（空字串 = 全部地點）
        person_kind:   drpPERSON_KIND 的值（空字串 = 全部類別）
        sysnam:        drpSYSNAM 的值（空字串 = 全部職系）
        title_keyword: 職缺名稱關鍵字（txtTITLE）
        org_keyword:   機關名稱關鍵字（txbORG_NAME）
        lookback_days: 查詢幾天內的職缺（預設 30 天）
        max_pages:     最多爬幾頁（0 = 不限）
    """
    session  = requests.Session()
    date_to  = _roc_today()
    date_from = _roc_days_ago(lookback_days)
    logger.info(
        f"爬蟲啟動 | 地點={work_place!r} 人員={person_kind!r} "
        f"關鍵字={title_keyword!r} 機關={org_keyword!r}"
    )

    # Step 1：GET 初始頁取得 VIEWSTATE
    r = session.get(LIST_URL, headers=HEADERS, timeout=30)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "lxml")

    # Step 2：第一次 POST 帶查詢條件
    hidden  = _extract_hidden_fields(soup)
    payload = _search_payload(
        hidden, date_from, date_to,
        work_place=work_place, person_kind=person_kind, sysnam=sysnam,
        title_keyword=title_keyword, org_keyword=org_keyword,
    )
    r = session.post(LIST_URL, data=payload, headers=HEADERS, timeout=30)
    r.encoding = "utf-8"
    result_soup = BeautifulSoup(r.text, "lxml")

    all_raw: List[dict] = []
    page = 1

    while True:
        raw = _parse_list_page(result_soup)
        if not raw:
            logger.info(f"第 {page} 頁無資料，停止")
            break

        all_raw.extend(raw)
        logger.info(f"第 {page} 頁：{len(raw)} 筆（累計 {len(all_raw)} 筆）")

        if max_pages and page >= max_pages:
            logger.info(f"已達 max_pages={max_pages}，停止")
            break

        if not _has_next_page(result_soup):
            break

        # 分頁：POST 帶 btnNEXT EVENTTARGET，並更新 VIEWSTATE
        hidden  = _extract_hidden_fields(result_soup)
        payload = _search_payload(
            hidden, date_from, date_to,
            work_place=work_place, person_kind=person_kind, sysnam=sysnam,
            title_keyword=title_keyword, org_keyword=org_keyword,
            event_target="ctl00$ContentPlaceHolder1$btnNEXT",
        )
        r = session.post(LIST_URL, data=payload, headers=HEADERS, timeout=30)
        r.encoding = "utf-8"
        result_soup = BeautifulSoup(r.text, "lxml")
        page += 1
        time.sleep(0.5)

    jobs = []
    for raw in all_raw:
        try:
            jobs.append(Job(**{k: raw.get(k, "") for k in Job.model_fields}))
        except Exception as e:
            logger.warning(f"Job 建立失敗（job_id={raw.get('job_id')}）：{e}")

    logger.info(f"爬蟲完成：共 {len(jobs)} 筆")
    return jobs
