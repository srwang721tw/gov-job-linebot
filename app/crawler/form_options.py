"""
從 DGPA 職缺網站抓取並快取下拉選單選項。
供訂閱設定的 Quick Reply / InlineKeyboard 使用。

快取：工作地點、人員區分、職系（sysnam）
"""
import socket

import requests
import urllib3.util.connection as _urllib3_cn
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.utils.config import CRAWLER_BASE_URL, CRAWLER_LIST_PAGE
from app.utils.logger import logger

# ── 強制 IPv4（與 scraper.py 相同，確保 Render 環境也能連到 DGPA）──────────────
# DGPA 只支援 IPv4；Render 等雲端環境預設嘗試 IPv6 → errno 101 Network unreachable
_urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

_RETRY = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
)


def _new_session() -> requests.Session:
    s = requests.Session()
    adapter = HTTPAdapter(max_retries=_RETRY)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

LIST_URL = CRAWLER_BASE_URL + CRAWLER_LIST_PAGE
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

_cached: dict | None = None

# 職系大分類（硬編碼，與 DGPA drpSYSNAM_grp 對應）
SYSNAM_GRP_OPTIONS = [
    {"value": "",  "text": "不限"},
    {"value": "A", "text": "行政類"},
    {"value": "B", "text": "技術類"},
]


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
    回傳選單選項字典：
      {
        "work_place":  [{value, text}, ...],   # 工作地點
        "person_kind": [{value, text}, ...],   # 人員區分
        "sysnam":      [{value, text}, ...],   # 職系細項（A101=綜合行政, B101=電機工程, ...）
      }
    首次呼叫時從 DGPA 網站抓取，之後使用快取。
    """
    global _cached
    if _cached is not None:
        return _cached

    try:
        r = _new_session().get(LIST_URL, headers=HEADERS, timeout=30)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "lxml")

        result = {
            "work_place": _extract_options(
                soup, "ctl00_ContentPlaceHolder1_drpWORK_PLACE"
            ),
            "person_kind": _extract_options(
                soup, "ctl00_ContentPlaceHolder1_drpPERSON_KIND"
            ),
            "sysnam": _extract_options(
                soup, "ctl00_ContentPlaceHolder1_drpSYSNAM"
            ),
        }
        # 只有成功取得有效資料才快取（避免把空結果永久快取）
        if result["work_place"] or result["sysnam"]:
            _cached = result
            logger.info(
                f"選單選項已載入：{len(_cached['work_place'])} 個地點、"
                f"{len(_cached['person_kind'])} 個人員類別、"
                f"{len(_cached['sysnam'])} 個職系"
            )
        else:
            logger.warning("選單選項回應為空，將在下次呼叫時重試")
            return result
    except Exception as e:
        logger.error(f"無法取得選單選項（將在下次呼叫時重試）：{e}")
        # 失敗時不快取，確保下次呼叫會重試
        return {"work_place": [], "person_kind": [], "sysnam": []}

    return _cached


def get_sysnam_names_for_grp(grp: str) -> list[str]:
    """
    取得指定職系大分類下的所有職系名稱清單，供 DB search_jobs 的 IN 子句使用。

    grp='A' → ['綜合行政', '社勞行政', '人事行政', ...]
    grp='B' → ['電機工程', '土木工程', ...]
    grp=''  → [] (不過濾)
    """
    if not grp:
        return []
    opts = get_form_options().get("sysnam", [])
    return [o["text"] for o in opts if o["value"].startswith(grp)]


def text_to_code(category: str, text: str) -> str:
    """
    依顯示文字反查代碼。
    text_to_code('person_kind', '聘用人員') → '12'
    """
    for opt in get_form_options().get(category, []):
        if opt["text"] == text:
            return opt["value"]
    return ""


def code_to_sysnam_grp(sysnam_code: str) -> str:
    """
    職系代碼 → 大分類：'A101' → 'A', 'B102' → 'B', '0100' → ''
    """
    if sysnam_code and sysnam_code[0].isalpha():
        return sysnam_code[0].upper()
    return ""


def clear_cache() -> None:
    """強制在下次呼叫時重新抓取（例如網站更新後）。"""
    global _cached
    _cached = None
