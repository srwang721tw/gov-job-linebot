"""DGPA form-option cache for subscription setup widgets.

Provides work-location and job-series (sysnam) dropdown options used by
the LINE Quick Reply and Telegram InlineKeyboard subscription flows.

The cache (``_cached``) is **pre-populated at import time** with a
2026-06 static snapshot so that the Render web service (which cannot
reach the Taiwan-only DGPA site) works out of the box.  Call
``clear_cache()`` followed by ``get_form_options()`` on a machine with
Taiwan IP access to refresh from the live site.
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
    total=2,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)


def _new_session() -> requests.Session:
    """Create a lightweight requests Session for fetching form options.

    Returns:
        Session with a 2-retry HTTPAdapter and IPv4 enforcement.
    """
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

# 職系大分類（硬編碼，與 DGPA drpSYSNAM_grp 對應）
SYSNAM_GRP_OPTIONS = [
    {"value": "",  "text": "不限"},
    {"value": "A", "text": "行政類"},
    {"value": "B", "text": "技術類"},
]

# ── 靜態 fallback 資料（2026-06 從 DGPA 取得）─────────────────────────────────
# Render 等環境若無法連到 DGPA，訂閱流程仍可使用這些資料正常運作。
# 縣市代碼與職系幾乎不會改變（台灣行政區劃定、行政院人事局職系分類）。
_WORK_PLACE_STATIC: list[dict] = [
    {"value": "100", "text": "-----雙北地區-----"},
    {"value": "10",  "text": "10-臺北市"},
    {"value": "23",  "text": "23-新北市"},
    {"value": "200", "text": "---桃竹苗地區---"},
    {"value": "30",  "text": "30-新竹市"},
    {"value": "31",  "text": "31-新竹縣"},
    {"value": "33",  "text": "33-桃園市"},
    {"value": "35",  "text": "35-苗栗縣"},
    {"value": "300", "text": "---中彰投地區---"},
    {"value": "42",  "text": "42-臺中市"},
    {"value": "50",  "text": "50-彰化縣"},
    {"value": "54",  "text": "54-南投縣"},
    {"value": "400", "text": "---雲嘉南地區---"},
    {"value": "60",  "text": "60-嘉義市"},
    {"value": "61",  "text": "61-嘉義縣"},
    {"value": "63",  "text": "63-雲林縣"},
    {"value": "72",  "text": "72-臺南市"},
    {"value": "500", "text": "---高高屏地區---"},
    {"value": "82",  "text": "82-高雄市"},
    {"value": "90",  "text": "90-屏東縣"},
    {"value": "600", "text": "-----基宜地區-----"},
    {"value": "20",  "text": "20-基隆市"},
    {"value": "26",  "text": "26-宜蘭縣"},
    {"value": "700", "text": "-----花東地區-----"},
    {"value": "95",  "text": "95-臺東縣"},
    {"value": "97",  "text": "97-花蓮縣"},
    {"value": "800", "text": "-----離島地區-----"},
    {"value": "88",  "text": "88-澎湖縣"},
    {"value": "89",  "text": "89-金門縣"},
    {"value": "98",  "text": "98-連江縣"},
    {"value": "101", "text": "101-中興新村"},
]

_SYSNAM_STATIC: list[dict] = [
    {"value": "0100", "text": "無"},
    # 行政類
    {"value": "A101", "text": "綜合行政"},
    {"value": "A102", "text": "社勞行政"},
    {"value": "A103", "text": "社會工作"},
    {"value": "A104", "text": "文教行政"},
    {"value": "A105", "text": "新聞傳播"},
    {"value": "A106", "text": "圖書史料檔案"},
    {"value": "A107", "text": "人事行政"},
    {"value": "A201", "text": "財稅金融"},
    {"value": "A202", "text": "會計審計"},
    {"value": "A203", "text": "統計"},
    {"value": "A301", "text": "司法行政"},
    {"value": "A302", "text": "法制"},
    {"value": "A303", "text": "廉政"},
    {"value": "A401", "text": "安全保防"},
    {"value": "A402", "text": "情報行政"},
    {"value": "A403", "text": "移民行政"},
    {"value": "A404", "text": "海巡行政"},
    {"value": "A501", "text": "經建行政"},
    {"value": "A502", "text": "交通行政"},
    {"value": "A503", "text": "地政"},
    {"value": "A601", "text": "衛生行政"},
    {"value": "A602", "text": "環保行政"},
    {"value": "A701", "text": "外交事務"},
    {"value": "A801", "text": "消防與災害防救"},
    {"value": "A901", "text": "警察行政"},
    # 技術類
    {"value": "B101", "text": "農業技術"},
    {"value": "B102", "text": "林業技術"},
    {"value": "B103", "text": "水產技術"},
    {"value": "B104", "text": "動物技術"},
    {"value": "B105", "text": "獸醫"},
    {"value": "B106", "text": "自然保育"},
    {"value": "B201", "text": "土木工程"},
    {"value": "B202", "text": "建築工程"},
    {"value": "B203", "text": "地質礦冶"},
    {"value": "B301", "text": "測量製圖"},
    {"value": "B302", "text": "都市計畫"},
    {"value": "B303", "text": "景觀設計"},
    {"value": "B401", "text": "衛生技術"},
    {"value": "B402", "text": "藥事"},
    {"value": "B403", "text": "醫學工程"},
    {"value": "B501", "text": "交通技術"},
    {"value": "B502", "text": "航空管制"},
    {"value": "B503", "text": "航空駕駛"},
    {"value": "B601", "text": "工業工程"},
    {"value": "B602", "text": "職業安全衛生"},
    {"value": "B701", "text": "電機工程"},
    {"value": "B702", "text": "資訊處理"},
    {"value": "B801", "text": "法醫"},
    {"value": "B802", "text": "刑事鑑識"},
    {"value": "B901", "text": "機械工程"},
    {"value": "BA01", "text": "環資技術"},
    {"value": "BB01", "text": "化學工程"},
    {"value": "BC01", "text": "天文氣象地震"},
    {"value": "BD01", "text": "原子能"},
    {"value": "BE01", "text": "消防技術"},
    {"value": "BF01", "text": "海巡技術"},
    {"value": "BG01", "text": "技藝"},
]

_STATIC_OPTIONS: dict = {
    "work_place":  _WORK_PLACE_STATIC,
    "person_kind": [],   # 訂閱條件已移除人員類別，無需此欄位
    "sysnam":      _SYSNAM_STATIC,
}

# v3.2：以靜態資料初始化快取，完全跳過 DGPA HTTP 請求（Render 無法連到 DGPA）
# 若需要強制從 DGPA 重新抓取（本機開發用），呼叫 clear_cache() 後再 get_form_options()
_cached = _STATIC_OPTIONS


# ── 選單選項取得 ──────────────────────────────────────────────────────────────

def _extract_options(soup: BeautifulSoup, select_id: str) -> list[dict]:
    """Extract ``<option>`` elements from a ``<select>`` by its HTML id.

    Args:
        soup: Parsed page as a ``BeautifulSoup`` object.
        select_id: The ``id`` attribute of the target ``<select>`` element.

    Returns:
        List of dicts ``{"value": ..., "text": ...}`` for every option
        that has a non-empty ``value`` attribute.  Empty list if the
        ``<select>`` element is not found.
    """
    tag = soup.find("select", id=select_id)
    if not tag:
        return []
    return [
        {"value": opt.get("value", ""), "text": opt.get_text(strip=True)}
        for opt in tag.find_all("option")
        if opt.get("value", "")
    ]


def get_form_options() -> dict:
    """Return dropdown option lists for work location and job series.

    Lookup order:
        1. Module-level cache (``_cached``): returned immediately if set.
        2. Live DGPA site: parsed and cached on success.
        3. Static fallback (``_STATIC_OPTIONS``, 2026-06 snapshot): used
           when the live site is unreachable (e.g. from Render US servers).

    Returns:
        Dict with keys:

        - ``"work_place"``: list of ``{"value": code, "text": name}``
        - ``"person_kind"``: always ``[]`` (field removed from subscription)
        - ``"sysnam"``: list of ``{"value": code, "text": name}``
    """
    global _cached
    if _cached is not None:
        return _cached

    try:
        r = _new_session().get(LIST_URL, headers=HEADERS, timeout=10)
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
        # 只有成功取得有效資料才快取
        if result["work_place"] or result["sysnam"]:
            _cached = result
            logger.info(
                f"選單選項已從 DGPA 載入：{len(_cached['work_place'])} 個地點、"
                f"{len(_cached['sysnam'])} 個職系"
            )
            return _cached
        else:
            logger.warning("DGPA 回傳空選單，使用靜態 fallback 資料")
            return _STATIC_OPTIONS

    except Exception as e:
        logger.warning(f"無法連到 DGPA 取得選單（使用靜態 fallback）：{e}")
        return _STATIC_OPTIONS


def get_sysnam_names_for_grp(grp: str) -> list[str]:
    """Return all job-series names belonging to a series group.

    Used to build the ``job_series IN (...)`` clause in ``search_jobs``.

    Args:
        grp: Group code: ``"A"`` (行政類), ``"B"`` (技術類), or ``""``
            (no filter).

    Returns:
        List of series name strings for the given group, or an empty
        list when ``grp`` is ``""``.

    Example:
        >>> get_sysnam_names_for_grp("A")
        ['綜合行政', '社勞行政', '人事行政', ...]
    """
    if not grp:
        return []
    opts = get_form_options().get("sysnam", [])
    return [o["text"] for o in opts if o["value"].startswith(grp)]


def text_to_code(category: str, text: str) -> str:
    """Look up an option code by its display text.

    Args:
        category: Key in the options dict, e.g. ``"sysnam"`` or
            ``"work_place"``.
        text: Display text to look up, e.g. ``"綜合行政"``.

    Returns:
        Corresponding option value string (e.g. ``"A101"``), or ``""``
        if not found.
    """
    for opt in get_form_options().get(category, []):
        if opt["text"] == text:
            return opt["value"]
    return ""


def code_to_sysnam_grp(sysnam_code: str) -> str:
    """Derive the series-group letter from a sysnam option code.

    Args:
        sysnam_code: Option value from the ``sysnam`` dropdown, e.g.
            ``"A101"``.

    Returns:
        Uppercase group letter (``"A"`` or ``"B"``), or ``""`` if the
        code starts with a digit or is empty.

    Example:
        >>> code_to_sysnam_grp("A101")
        'A'
        >>> code_to_sysnam_grp("0100")
        ''
    """
    if sysnam_code and sysnam_code[0].isalpha():
        return sysnam_code[0].upper()
    return ""


def clear_cache() -> None:
    """Invalidate the option cache so the next call re-fetches from DGPA.

    Useful for local development after the DGPA site updates its dropdown
    contents.  Has no effect on deployments that cannot reach DGPA
    (Render servers), which will fall back to the static snapshot.
    """
    global _cached
    _cached = None
