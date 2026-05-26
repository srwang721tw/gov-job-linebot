"""
Crawler for 行政院人事行政總處事求人機關徵才系統
Target: https://web3.dgpa.gov.tw/want03front/AP/WANTF00001.ASPX
Site: ASP.NET WebForms — uses __VIEWSTATE postback (no __EVENTVALIDATION).
"""
import re
import time
from datetime import datetime, timezone, timedelta
from typing import List
from urllib.parse import urljoin, unquote

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


def _roc_today() -> str:
    """Return ROC date string: YYYMMDD (e.g. 1150526)."""
    today = datetime.now(timezone(timedelta(hours=8)))  # Taipei time
    roc_year = today.year - 1911
    return f"{roc_year}{today.month:02d}{today.day:02d}"


def _roc_days_ago(days: int) -> str:
    d = datetime.now(timezone(timedelta(hours=8))) - timedelta(days=days)
    roc_year = d.year - 1911
    return f"{roc_year}{d.month:02d}{d.day:02d}"


def _extract_hidden_fields(soup: BeautifulSoup) -> dict:
    """Collect all ASP.NET hidden inputs (VIEWSTATE, extra state fields)."""
    fields = {}
    for inp in soup.find_all("input", type="hidden"):
        name = inp.get("name")
        if name:
            fields[name] = inp.get("value", "")
    return fields


def _search_payload(hidden: dict, date_from: str, date_to: str, event_target: str = "") -> dict:
    """Build the POST payload for a search or pagination request."""
    return {
        **hidden,
        "__EVENTTARGET": event_target,
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "ctl00$ContentPlaceHolder1$drpPERSON_KIND": "",
        "ctl00$ContentPlaceHolder1$drpWORK_PLACE": "",
        "ctl00$ContentPlaceHolder1$drpSYSNAM_grp": "",
        "ctl00$ContentPlaceHolder1$drpSYSNAM": "",
        "ctl00$ContentPlaceHolder1$drpSPECIAL_CONDITIONS": "",
        "ctl00$ContentPlaceHolder1$txtTITLE": "",
        "ctl00$ContentPlaceHolder1$txbORG_NAME": "",
        "ctl00$ContentPlaceHolder1$DATE_FROM": date_from,
        "ctl00$ContentPlaceHolder1$DATE_TO": date_to,
        # Only include the submit button on the first search, not on pagination
        **({"ctl00$ContentPlaceHolder1$btnQUERY": "查詢"} if not event_target else {}),
    }


def _parse_list_page(soup: BeautifulSoup) -> List[dict]:
    """Extract job summary rows from the GridView."""
    table = soup.find("table", id="ctl00_ContentPlaceHolder1_gvMAIN")
    if not table:
        return []

    raw_jobs = []
    for row in table.find_all("tr"):
        main_div = row.find("div", class_="cursor_point")
        if not main_div:
            continue

        # Title and agency are in clearly classed divs
        title = _text(main_div.find("div", class_=lambda c: c and "md_block_bold" in c))
        agency = _text(main_div.find("div", class_=lambda c: c and "md_red" in c))

        # Desktop-only hidden divs: rank_type, job_series, location, deadline (in order)
        md_hides = [d for d in main_div.find_all("div")
                    if "md_hide" in (d.get("class") or [])
                    and "md_show" not in (d.get("class") or [])]
        rank_type  = _text(md_hides[0]) if len(md_hides) > 0 else ""
        job_series = _text(md_hides[1]) if len(md_hides) > 1 else ""
        location   = _text(md_hides[2]) if len(md_hides) > 2 else ""
        deadline   = _text(md_hides[3]) if len(md_hides) > 3 else ""

        # Detail URL from onclick="window.open('WANTF00001_1.aspx?work_id=...', ...)"
        onclick = main_div.get("onclick", "")
        m = re.search(r"window\.open\('([^']+)'", onclick)
        detail_path = m.group(1) if m else ""
        detail_url = urljoin(DETAIL_BASE, detail_path) if detail_path else ""

        # work_id becomes the job's unique ID
        id_m = re.search(r"work_id=([^&]+)", detail_path)
        job_id = id_m.group(1) if id_m else detail_path

        if not title or not job_id:
            continue

        raw_jobs.append({
            "job_id": job_id,
            "title": title,
            "agency": agency,
            "location": location,
            "job_series": job_series,
            "rank_type": rank_type,
            "deadline": deadline.replace("有效期間：", "").strip(),
            "detail_url": detail_url,
        })

    return raw_jobs


def _has_next_page(soup: BeautifulSoup) -> bool:
    """Check if the '下一頁' link exists and is not disabled."""
    for a in soup.find_all("a", href=re.compile(r"doPostBack")):
        if "btnNEXT" in a.get("href", "") or "下一頁" in a.get_text():
            return True
    return False


def _fetch_detail(session: requests.Session, url: str) -> dict:
    """Fetch and parse a job detail page using known element IDs."""
    if not url:
        return {}
    try:
        r = session.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "lxml")

        def by_id(elem_id: str) -> str:
            tag = soup.find(id=elem_id)
            return tag.get_text(" ", strip=True) if tag else ""

        date_range = by_id("PLDATE_FROM_TO")  # "115/05/26~115/05/28"
        parts = date_range.split("~")
        publish_date = parts[0].strip() if parts else ""
        deadline = parts[-1].strip() if parts else ""

        return {
            "rank_type":    by_id("PLRANK"),
            "job_series":   by_id("PLSYSNAM"),
            "location":     by_id("PLWORK_PLACE_TYPE"),
            "description":  by_id("PLWORK_ITEM"),
            "requirement":  by_id("PLWORK_QUALITY"),
            "contact":      by_id("PLCONTACT_METHOD"),
            "apply_method": by_id("V_Work_Type"),
            "publish_date": publish_date,
            "deadline":     deadline,
        }
    except Exception as e:
        logger.warning(f"Detail fetch failed {url}: {e}")
        return {}


def _text(tag) -> str:
    return tag.get_text(strip=True) if tag else ""


def crawl_all_jobs() -> List[Job]:
    session = requests.Session()
    date_to   = _roc_today()
    date_from = _roc_days_ago(30)  # last 30 days of postings
    logger.info(f"Crawling jobs from {date_from} to {date_to}")

    # Step 1: GET initial page for VIEWSTATE
    r = session.get(LIST_URL, headers=HEADERS, timeout=30)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "lxml")

    # Step 2: First POST — submit search
    hidden = _extract_hidden_fields(soup)
    payload = _search_payload(hidden, date_from, date_to)
    r = session.post(LIST_URL, data=payload, headers=HEADERS, timeout=30)
    r.encoding = "utf-8"
    result_soup = BeautifulSoup(r.text, "lxml")

    all_raw: List[dict] = []
    page = 1

    while True:
        raw_jobs = _parse_list_page(result_soup)
        if not raw_jobs:
            logger.info(f"No jobs on page {page}, stopping")
            break

        all_raw.extend(raw_jobs)
        logger.info(f"Page {page}: {len(raw_jobs)} jobs (total so far: {len(all_raw)})")

        if MAX_CRAWL_PAGES and page >= MAX_CRAWL_PAGES:
            logger.info(f"Reached MAX_CRAWL_PAGES={MAX_CRAWL_PAGES}")
            break

        if not _has_next_page(result_soup):
            logger.info("No next page, done paginating")
            break

        # Pagination: postback to btnNEXT, carry hidden state from current result page
        hidden = _extract_hidden_fields(result_soup)
        payload = _search_payload(
            hidden, date_from, date_to,
            event_target="ctl00$ContentPlaceHolder1$btnNEXT",
        )
        r = session.post(LIST_URL, data=payload, headers=HEADERS, timeout=30)
        r.encoding = "utf-8"
        result_soup = BeautifulSoup(r.text, "lxml")
        page += 1
        time.sleep(0.8)

    # Step 3: Fetch detail pages
    jobs: List[Job] = []
    for i, raw in enumerate(all_raw):
        detail = _fetch_detail(session, raw.get("detail_url", ""))
        raw.update(detail)

        if i > 0 and i % 10 == 0:
            time.sleep(0.5)

        try:
            jobs.append(Job(**{k: raw.get(k, "") for k in Job.model_fields}))
        except Exception as e:
            logger.warning(f"Job model error (job_id={raw.get('job_id')}): {e}")

    logger.info(f"Crawl complete: {len(jobs)} jobs")
    return jobs
