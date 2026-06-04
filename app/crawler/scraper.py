"""
行政院人事行政總處事求人機關徵才系統 爬蟲（v3）
目標：https://web3.dgpa.gov.tw/want03front/AP/WANTF00001.ASPX
網站類型：ASP.NET WebForms，需攜帶 __VIEWSTATE 跨頁 POST（無 __EVENTVALIDATION）。

v3 新增：
  - fetch_detail 參數：排程爬取時設 True，抓取每筆職缺的詳細頁
  - 新 DGPA 表單欄位：chkTYPE1-4（官等）、IS_OFFICE/IS_NOT_OFFICE（職缺類別）
  - Job 物件包含完整欄位（合併列表頁 + 詳細頁）
"""
import re
import time
from datetime import datetime, timezone, timedelta
from typing import List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.crawler.form_options import (
    code_to_sysnam_grp,
    get_form_options,
    get_sysnam_names_for_grp,
    text_to_code,
)
from app.models.job import Job
from app.utils.config import (
    CRAWL_DETAIL_DELAY,
    CRAWLER_BASE_URL,
    CRAWLER_LIST_PAGE,
    MAX_CRAWL_PAGES,
)
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


def _roc_to_iso(roc: str) -> str:
    """
    民國年日期字串 → ISO 格式。
    '115/06/03' → '2026-06-03'
    '115/05/30~115/06/03' → 取截止日 '2026-06-03'
    """
    # 若是範圍，取後半段截止日
    s = roc.split("~")[-1].strip()
    parts = s.replace(" ", "").split("/")
    if len(parts) == 3:
        try:
            year = int(parts[0]) + 1911
            return f"{year}-{parts[1]}-{parts[2]}"
        except (ValueError, IndexError):
            pass
    return ""


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
    sysnam_grp: str = "",
    sysnam: str = "",
    chk_types: list[str] | None = None,
    is_office: bool | None = None,
    title_keyword: str = "",
    org_keyword: str = "",
    event_target: str = "",
) -> dict:
    """建立查詢或分頁 POST 的 payload。"""
    payload: dict = {
        **hidden,
        "__EVENTTARGET":   event_target,
        "__EVENTARGUMENT": "",
        "__LASTFOCUS":     "",
        "ctl00$ContentPlaceHolder1$drpPERSON_KIND":        person_kind,
        "ctl00$ContentPlaceHolder1$drpWORK_PLACE":         work_place,
        "ctl00$ContentPlaceHolder1$drpSYSNAM_grp":         sysnam_grp,
        "ctl00$ContentPlaceHolder1$drpSYSNAM":             sysnam,
        "ctl00$ContentPlaceHolder1$drpSPECIAL_CONDITIONS": "",
        "ctl00$ContentPlaceHolder1$txtTITLE":              title_keyword,
        "ctl00$ContentPlaceHolder1$txbORG_NAME":           org_keyword,
        "ctl00$ContentPlaceHolder1$DATE_FROM":             date_from,
        "ctl00$ContentPlaceHolder1$DATE_TO":               date_to,
    }

    # 官等 checkbox（只有值為 'on' 時才送）
    for t in (chk_types or []):
        payload[f"ctl00$ContentPlaceHolder1$chkTYPE{t}"] = "on"

    # 職缺類別 checkbox
    if is_office is True:
        payload["ctl00$ContentPlaceHolder1$IS_OFFICE"] = "on"
    elif is_office is False:
        payload["ctl00$ContentPlaceHolder1$IS_NOT_OFFICE"] = "on"

    # 第一次查詢才送出按鈕參數，分頁時不送
    if not event_target:
        payload["ctl00$ContentPlaceHolder1$btnQUERY"] = "查詢"

    return payload


# ── 列表頁解析 ────────────────────────────────────────────────────────────────

def _text(tag) -> str:
    return tag.get_text(strip=True) if tag else ""


def _parse_list_page(soup: BeautifulSoup) -> List[dict]:
    """從 GridView 解析職缺摘要列，回傳 raw dict list。"""
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

        # 桌面版隱藏 div 依序：職系、官等（列等）、地點、截止日
        md_hides = [
            d for d in main_div.find_all("div")
            if "md_hide" in (d.get("class") or [])
            and "md_show" not in (d.get("class") or [])
        ]
        job_series = _text(md_hides[0]) if len(md_hides) > 0 else ""
        rank_type  = _text(md_hides[1]) if len(md_hides) > 1 else ""
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
            "org_name":   agency,
            "location":   location,
            "job_series": job_series,
            "rank_type":  rank_type,
            "deadline":   deadline.replace("有效期間：", "").strip(),
            "job_url":    detail_url,
        })

    return raw_jobs


def _has_next_page(soup: BeautifulSoup) -> bool:
    for a in soup.find_all("a", href=re.compile(r"doPostBack")):
        if "btnNEXT" in a.get("href", "") or "下一頁" in a.get_text():
            return True
    return False


# ── 詳細頁解析 ────────────────────────────────────────────────────────────────

def fetch_job_detail(session: requests.Session, url: str) -> dict:
    """
    抓取職缺詳細頁並解析關鍵欄位。
    已驗證的 element ID（2026-05）：
        PLTITLE          職稱
        PLORG_NAME       機關名稱
        PLPERSON_KIND    人員區分
        PLWORK_PLACE_TYPE 工作地點（帶代碼前綴）
        PLRANK           官等
        PLSYSNAM         職系
        PLDATE_FROM_TO   徵才期間
        PLWORK_ITEM      工作說明
        PLWORK_QUALITY   應徵條件
        PLWORK_ADDRESS   工作地址
        PLCONTACT_METHOD 聯絡方式
        V_Work_Type      應徵方式

    TODO: 正取/候補名額的 element ID 尚未確認。
    """
    if not url:
        return {}
    try:
        r = session.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "lxml")

        def by_id(eid: str) -> str:
            tag = soup.find(id=eid)
            return tag.get_text(" ", strip=True) if tag else ""

        date_range = by_id("PLDATE_FROM_TO")
        parts = date_range.split("~")
        publish_date = parts[0].strip() if parts else ""
        deadline_raw = parts[-1].strip() if len(parts) > 1 else date_range.strip()

        return {
            "title":        by_id("PLTITLE"),
            "org_name":     by_id("PLORG_NAME"),
            "person_kind":  by_id("PLPERSON_KIND"),
            "location":     by_id("PLWORK_PLACE_TYPE"),
            "rank_type":    by_id("PLRANK"),
            "job_series":   by_id("PLSYSNAM"),
            "work_items":   by_id("PLWORK_ITEM"),
            "qualifications": by_id("PLWORK_QUALITY"),
            "work_address": by_id("PLWORK_ADDRESS"),
            "contact_method": by_id("PLCONTACT_METHOD"),
            "apply_method": by_id("V_Work_Type"),
            "publish_date": publish_date,
            "deadline_raw": deadline_raw,
        }
    except Exception as e:
        logger.warning(f"詳細頁抓取失敗 {url}: {e}")
        return {}


# ── 原始資料 → Job 物件轉換 ──────────────────────────────────────────────────

def _extract_work_place_code(location: str) -> str:
    """'42-臺中市' → '42'"""
    m = re.match(r"^(\d+)-", location.strip())
    return m.group(1) if m else ""


def _clean_location(location: str) -> str:
    """'42-臺中市' → '臺中市'"""
    m = re.match(r"^\d+-(.+)$", location.strip())
    return m.group(1) if m else location.strip()


def _build_job(raw: dict, detail: dict | None = None) -> Job:
    """
    從列表頁原始 dict + 詳細頁 dict 建立 Job 物件。
    detail 優先覆蓋列表頁的同名欄位。
    """
    d = detail or {}

    # 地點：優先用詳細頁（帶完整名稱），否則用列表頁
    raw_location = d.get("location") or raw.get("location", "")
    work_place_code = _extract_work_place_code(raw_location)
    work_place = _clean_location(raw_location)

    # 職系：優先詳細頁
    job_series = d.get("job_series") or raw.get("job_series", "")
    # 職系大分類：嘗試從 form_options 反查代碼
    sysnam_code = text_to_code("sysnam", job_series)
    sysnam_grp  = code_to_sysnam_grp(sysnam_code)

    # 人員區分：只有詳細頁有
    person_kind = d.get("person_kind", "")
    person_kind_code = text_to_code("person_kind", person_kind)

    # 截止日：列表頁是 "115/05/30~115/06/03"，取後半段
    deadline_str = raw.get("deadline", "")
    deadline_end_iso = _roc_to_iso(deadline_str)

    return Job(
        job_id           = raw["job_id"],
        title            = d.get("title") or raw.get("title", ""),
        org_name         = d.get("org_name") or raw.get("org_name", ""),
        work_place       = work_place,
        work_place_code  = work_place_code,
        person_kind      = person_kind,
        person_kind_code = person_kind_code,
        rank_type        = d.get("rank_type") or raw.get("rank_type", ""),
        job_series       = job_series,
        sysnam_grp       = sysnam_grp,
        regular_slots    = 0,     # TODO: 待確認 DGPA element ID
        alternate_slots  = 0,     # TODO: 待確認 DGPA element ID
        qualifications   = d.get("qualifications", ""),
        work_items       = d.get("work_items", ""),
        work_address     = d.get("work_address", ""),
        contact_method   = d.get("contact_method", ""),
        apply_method     = d.get("apply_method", ""),
        publish_date     = d.get("publish_date", ""),
        deadline         = deadline_str,
        deadline_end_iso = deadline_end_iso,
        job_url          = raw.get("job_url", ""),
    )


# ── 主要爬取函式 ──────────────────────────────────────────────────────────────

def crawl_jobs(
    work_place: str = "",
    person_kind: str = "",
    sysnam_grp: str = "",
    sysnam: str = "",
    chk_types: list[str] | None = None,
    is_office: bool | None = None,
    title_keyword: str = "",
    org_keyword: str = "",
    lookback_days: int = 30,
    max_pages: int = MAX_CRAWL_PAGES,
    fetch_detail: bool = False,
) -> List[Job]:
    """
    依條件爬取職缺。

    Args:
        work_place:    drpWORK_PLACE 值（空字串 = 全部地點）
        person_kind:   drpPERSON_KIND 值（空字串 = 全部類別）
        sysnam_grp:    drpSYSNAM_grp 值：'' / 'A'（行政類）/ 'B'（技術類）
        sysnam:        drpSYSNAM 值（空字串 = 全部職系）
        chk_types:     官等 checkbox 清單，e.g. ['1','2'] = 簡任+薦任
        is_office:     True=須具資格 / False=不具資格 / None=不限
        title_keyword: 職缺名稱關鍵字
        org_keyword:   機關名稱關鍵字
        lookback_days: 查詢幾天內的職缺（預設 30 天）
        max_pages:     最多爬幾頁（0 = 不限）
        fetch_detail:  是否同時抓取詳細頁（排程爬取時用）
    """
    session   = requests.Session()
    date_to   = _roc_today()
    date_from = _roc_days_ago(lookback_days)
    logger.info(
        f"爬蟲啟動 | 地點={work_place!r} 人員={person_kind!r} "
        f"職系={sysnam_grp!r} 關鍵字={title_keyword!r} fetch_detail={fetch_detail}"
    )

    # Step 1：GET 初始頁取得 VIEWSTATE
    r = session.get(LIST_URL, headers=HEADERS, timeout=30)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "lxml")

    # Step 2：第一次 POST 帶查詢條件
    hidden  = _extract_hidden_fields(soup)
    payload = _search_payload(
        hidden, date_from, date_to,
        work_place=work_place, person_kind=person_kind,
        sysnam_grp=sysnam_grp, sysnam=sysnam,
        chk_types=chk_types, is_office=is_office,
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
            work_place=work_place, person_kind=person_kind,
            sysnam_grp=sysnam_grp, sysnam=sysnam,
            chk_types=chk_types, is_office=is_office,
            title_keyword=title_keyword, org_keyword=org_keyword,
            event_target="ctl00$ContentPlaceHolder1$btnNEXT",
        )
        r = session.post(LIST_URL, data=payload, headers=HEADERS, timeout=30)
        r.encoding = "utf-8"
        result_soup = BeautifulSoup(r.text, "lxml")
        page += 1
        time.sleep(0.5)

    # 建立 Job 物件（選擇性抓詳細頁）
    jobs: List[Job] = []
    for i, raw in enumerate(all_raw):
        detail: dict = {}
        if fetch_detail and raw.get("job_url"):
            detail = fetch_job_detail(session, raw["job_url"])
            if CRAWL_DETAIL_DELAY > 0:
                time.sleep(CRAWL_DETAIL_DELAY)
            if (i + 1) % 50 == 0:
                logger.info(f"詳細頁進度：{i + 1}/{len(all_raw)}")

        try:
            jobs.append(_build_job(raw, detail if fetch_detail else None))
        except Exception as e:
            logger.warning(f"Job 建立失敗（job_id={raw.get('job_id')}）：{e}")

    logger.info(f"爬蟲完成：共 {len(jobs)} 筆（fetch_detail={fetch_detail}）")
    return jobs
