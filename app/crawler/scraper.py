"""
行政院人事行政總處事求人機關徵才系統 爬蟲（v3.1）
目標：https://web3.dgpa.gov.tw/want03front/AP/WANTF00001.ASPX
網站類型：ASP.NET WebForms，需攜帶 __VIEWSTATE 跨頁 POST（無 __EVENTVALIDATION）。

v3.1 改動：
  - 排程爬取固定 is_office=True（須具公務人員任用資格）
  - 新增 _parse_rank_grades()、_derive_rank_type_codes()
  - 日期統一為 YYYY-MM-DD（deadline_start + deadline_end）
  - 新增 search_text 計算欄位
  - 移除 person_kind、contact_method、apply_method
"""
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from typing import List
from urllib.parse import urljoin

import requests
import urllib3.util.connection as _urllib3_cn
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

from app.crawler.form_options import (
    code_to_sysnam_grp,
    get_form_options,
    text_to_code,
)
from app.models.job import Job
from app.utils.config import (
    CRAWLER_BASE_URL,
    CRAWLER_LIST_PAGE,
    MAX_CRAWL_PAGES,
)

_DETAIL_WORKERS = 8   # 並行抓詳細頁的 thread 數
from app.utils.logger import logger

# ── 強制 IPv4（解決 Render 等主機 IPv6 路由不通的問題）────────────────────────
# DGPA 網站只支援 IPv4；部分雲端環境預設嘗試 IPv6 → errno 101 Network unreachable
_urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

LIST_URL = CRAWLER_BASE_URL + CRAWLER_LIST_PAGE
DETAIL_BASE = CRAWLER_BASE_URL + "/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": LIST_URL,
}

# ── 請求重試策略 ──────────────────────────────────────────────────────────────
_RETRY = Retry(
    total=3,
    backoff_factor=2,          # 1s → 2s → 4s
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
)


def _new_session() -> requests.Session:
    """建立帶重試策略的 requests Session（強制 IPv4）。"""
    s = requests.Session()
    adapter = HTTPAdapter(max_retries=_RETRY)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


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
    將單一民國年日期字串轉為 ISO YYYY-MM-DD。
    '115/06/03' → '2026-06-03'
    若格式不符則回傳 ''。
    """
    s = roc.strip().replace(" ", "")
    parts = s.split("/")
    if len(parts) == 3:
        try:
            year = int(parts[0]) + 1911
            return f"{year}-{parts[1]}-{parts[2]}"
        except (ValueError, IndexError):
            pass
    return ""


def _parse_deadline_range(deadline_raw: str) -> tuple[str, str]:
    """
    解析列表頁截止日範圍字串，回傳 (deadline_start, deadline_end) ISO 格式。
    '115/05/30~115/06/03' → ('2026-05-30', '2026-06-03')
    '115/06/03' → ('', '2026-06-03')
    """
    s = deadline_raw.strip()
    if "~" in s:
        parts = s.split("~", 1)
        return (_roc_to_iso(parts[0].strip()), _roc_to_iso(parts[1].strip()))
    return ("", _roc_to_iso(s))


# ── Rank 解析工具 ──────────────────────────────────────────────────────────────

def _parse_rank_grades(rank_text: str) -> tuple[int, int]:
    """
    從官等文字提取最低/最高職等。
    '薦任第6至第9職等'               → (6, 9)
    '委任第5職等或薦任第6職等至薦任第7職等' → (5, 7)
    '簡任第10職等'                    → (10, 10)
    '不分官等' / '' / 無法解析         → (0, 0)

    使用 regex 同時匹配「第N職等」與「第N至」兩種格式。
    """
    nums = [int(n) for n in re.findall(r"第(\d+)(?:職等|至|～|~)", rank_text)]
    if not nums:
        return (0, 0)
    return (min(nums), max(nums))


def _derive_rank_type_codes(rank_text: str) -> str:
    """
    從官等文字推算代碼（逗號分隔）。
    代碼：1=簡任/簡派, 2=薦任/薦派, 3=委任/委派, 4=其他（無法識別）
    '薦任第6職等'            → '2'
    '委任第5職等或薦任第6職等' → '3,2'
    '不分官等'               → '4'
    """
    codes: list[str] = []
    if "簡任" in rank_text or "簡派" in rank_text:
        codes.append("1")
    if "薦任" in rank_text or "薦派" in rank_text:
        codes.append("2")
    if "委任" in rank_text or "委派" in rank_text:
        codes.append("3")
    if not codes and rank_text.strip():
        codes.append("4")
    return ",".join(codes)


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

def fetch_job_detail(session: requests.Session | None, url: str) -> dict:
    """session 為 None 時自動建立新 Session。"""
    if session is None:
        session = _new_session()
    """
    抓取職缺詳細頁並解析關鍵欄位。
    已驗證的 element ID（2026-05）：
        PLTITLE          職稱
        PLORG_NAME       機關名稱
        PLWORK_PLACE_TYPE 工作地點（帶代碼前綴）
        PLRANK           官等
        PLSYSNAM         職系
        PLDATE_FROM_TO   徵才期間（格式：起始日~截止日，民國年）
        PLWORK_ITEM      工作說明
        PLWORK_QUALITY   應徵條件
        PLWORK_ADDRESS   工作地址
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

        return {
            "title":          by_id("PLTITLE"),
            "org_name":       by_id("PLORG_NAME"),
            "location":       by_id("PLWORK_PLACE_TYPE"),
            "rank_type":      by_id("PLRANK"),
            "job_series":     by_id("PLSYSNAM"),
            "work_items":     by_id("PLWORK_ITEM"),
            "qualifications": by_id("PLWORK_QUALITY"),
            "work_address":   by_id("PLWORK_ADDRESS"),
            "date_range":     date_range,   # 'YYY/MM/DD~YYY/MM/DD'
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

    # 官等：優先詳細頁
    rank_type = d.get("rank_type") or raw.get("rank_type", "")
    rank_type_codes = _derive_rank_type_codes(rank_type)
    rank_grade_min, rank_grade_max = _parse_rank_grades(rank_type)

    # 日期：列表頁是 "115/05/30~115/06/03"
    deadline_str = raw.get("deadline", "")
    deadline_start, deadline_end = _parse_deadline_range(deadline_str)

    # 若詳細頁有 date_range，覆蓋
    if d.get("date_range"):
        ds, de = _parse_deadline_range(d["date_range"])
        if ds:
            deadline_start = ds
        if de:
            deadline_end = de

    # publish_date：目前從 date_range 起始日取，無法取得時用爬取當天
    publish_date = deadline_start  # 大部分職缺 start = 公告日

    # 全文搜尋欄位
    qualifications = d.get("qualifications", "")
    work_items = d.get("work_items", "")
    title = d.get("title") or raw.get("title", "")
    org_name = d.get("org_name") or raw.get("org_name", "")
    search_text = " ".join(filter(None, [title, org_name, qualifications, work_items]))

    return Job(
        job_id          = raw["job_id"],
        title           = title,
        org_name        = org_name,
        work_place      = work_place,
        work_place_code = work_place_code,
        rank_type       = rank_type,
        rank_type_codes = rank_type_codes,
        rank_grade_min  = rank_grade_min,
        rank_grade_max  = rank_grade_max,
        job_series      = job_series,
        sysnam_grp      = sysnam_grp,
        regular_slots   = 0,     # TODO: 待確認 DGPA element ID
        alternate_slots = 0,     # TODO: 待確認 DGPA element ID
        qualifications  = qualifications,
        work_items      = work_items,
        work_address    = d.get("work_address", ""),
        publish_date    = publish_date,
        deadline_start  = deadline_start,
        deadline_end    = deadline_end,
        job_url         = raw.get("job_url", ""),
        search_text     = search_text,
    )


# ── 主要爬取函式 ──────────────────────────────────────────────────────────────

def crawl_jobs(
    work_place: str = "",
    person_kind: str = "",
    sysnam_grp: str = "",
    sysnam: str = "",
    chk_types: list[str] | None = None,
    is_office: bool | None = True,   # v3.1: 預設固定 True（須具公務人員資格）
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
        is_office:     True=須具資格（預設）/ False=不具資格 / None=不限
        title_keyword: 職缺名稱關鍵字（只用於爬蟲 filter，不用於 DB 搜尋）
        org_keyword:   機關名稱關鍵字（只用於爬蟲 filter）
        lookback_days: 查詢幾天內的職缺（預設 30 天）
        max_pages:     最多爬幾頁（0 = 不限）
        fetch_detail:  是否同時抓取詳細頁（排程爬取時用）
    """
    session   = _new_session()
    date_to   = _roc_today()
    date_from = _roc_days_ago(lookback_days)
    logger.info(
        f"爬蟲啟動 | 地點={work_place!r} 職系={sysnam_grp!r} "
        f"is_office={is_office} fetch_detail={fetch_detail}"
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

    # 建立 Job 物件（選擇性並行抓詳細頁）
    jobs: List[Job] = []
    if fetch_detail and all_raw:
        # 並行抓詳細頁：ThreadPoolExecutor，session 的 urllib3 pool 是 thread-safe
        detail_map: dict[str, dict] = {}
        urls = [(raw["job_id"], raw["job_url"]) for raw in all_raw if raw.get("job_url")]
        done = 0
        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as pool:
            future_to_id = {pool.submit(fetch_job_detail, session, url): jid
                            for jid, url in urls}
            for future in as_completed(future_to_id):
                detail_map[future_to_id[future]] = future.result() or {}
                done += 1
                if done % 100 == 0:
                    logger.info(f"詳細頁進度：{done}/{len(urls)}")
        logger.info(f"詳細頁抓取完成：{len(detail_map)} 筆")

        for raw in all_raw:
            try:
                jobs.append(_build_job(raw, detail_map.get(raw["job_id"], {})))
            except Exception as e:
                logger.warning(f"Job 建立失敗（{raw.get('job_id')}）：{e}")
    else:
        for raw in all_raw:
            try:
                jobs.append(_build_job(raw, None))
            except Exception as e:
                logger.warning(f"Job 建立失敗（{raw.get('job_id')}）：{e}")

    logger.info(f"爬蟲完成：共 {len(jobs)} 筆（fetch_detail={fetch_detail}）")
    return jobs
