"""
從 DGPA 職缺網站抓取並快取下拉選單選項（工作地點、人員區分）。
供 LINE 訂閱設定的 Quick Reply 選單使用。
"""
import requests
from bs4 import BeautifulSoup

from app.utils.config import CRAWLER_BASE_URL, CRAWLER_LIST_PAGE
from app.utils.logger import logger

LIST_URL = CRAWLER_BASE_URL + CRAWLER_LIST_PAGE
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

_cached: dict | None = None


def _extract_options(soup: BeautifulSoup, select_id: str) -> list[dict]:
    tag = soup.find("select", id=select_id)
    if not tag:
        return []
    return [
        {"value": opt.get("value", ""), "text": opt.get_text(strip=True)}
        for opt in tag.find_all("option")
        if opt.get("value", "")  # 略過空白 placeholder
    ]


def get_form_options() -> dict:
    """
    回傳 {work_place, person_kind} 選單選項。
    首次呼叫時從 DGPA 網站抓取，之後使用快取。
    """
    global _cached
    if _cached is not None:
        return _cached

    try:
        r = requests.get(LIST_URL, headers=HEADERS, timeout=30)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "lxml")

        _cached = {
            "work_place": _extract_options(
                soup, "ctl00_ContentPlaceHolder1_drpWORK_PLACE"
            ),
            "person_kind": _extract_options(
                soup, "ctl00_ContentPlaceHolder1_drpPERSON_KIND"
            ),
        }
        logger.info(
            f"選單選項已載入：{len(_cached['work_place'])} 個地點、"
            f"{len(_cached['person_kind'])} 個人員類別"
        )
    except Exception as e:
        logger.error(f"無法取得選單選項：{e}")
        _cached = {"work_place": [], "person_kind": []}

    return _cached


def clear_cache() -> None:
    """強制在下次呼叫時重新抓取（例如網站更新後）。"""
    global _cached
    _cached = None
