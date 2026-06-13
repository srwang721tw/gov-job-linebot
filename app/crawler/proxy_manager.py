"""動態 proxy pool：從 proxynova.com 取得台灣 proxy 並測試可用性。"""
import re
import logging

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_PROXYNOVA_URL = "https://www.proxynova.com/proxy-server-list/country-tw/"
_TEST_URL = "https://web3.dgpa.gov.tw/want03front/AP/WANTF00001.ASPX"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _scrape_proxynova() -> list[str]:
    """回傳 ['IP:PORT', ...] 清單。"""
    try:
        r = requests.get(_PROXYNOVA_URL, headers=_HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
    except Exception as e:
        log.warning(f"proxynova 抓取失敗: {e}")
        return []

    proxies = []
    for row in soup.select("tr"):
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        abbr = tds[0].find("abbr")
        if not abbr:
            continue
        # IP 從 title 屬性解析（格式 NNN-NNN-NNN-NNN.hostname）
        m = re.search(r"(\d{1,3})-(\d{1,3})-(\d{1,3})-(\d{1,3})\.", abbr.get("title", ""))
        if not m:
            continue
        ip = ".".join(m.groups())
        port_text = re.sub(r"<[^>]+>", "", str(tds[1])).strip()
        m_port = re.search(r"\d{2,5}", port_text)
        if not m_port:
            continue
        proxies.append(f"{ip}:{m_port.group()}")
    return proxies


def _test_proxy(proxy_str: str, timeout: int = 15) -> bool:
    """測試 proxy 能否取得 DGPA 的 __VIEWSTATE（確認為真實頁面）。"""
    proxy_dict = {"http": f"http://{proxy_str}", "https": f"http://{proxy_str}"}
    try:
        r = requests.get(_TEST_URL, proxies=proxy_dict, timeout=timeout)
        return "__VIEWSTATE" in r.text
    except Exception:
        return False


def get_working_proxy() -> dict | None:
    """
    回傳第一個可用 proxy 的 requests proxies dict，
    例：{"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}
    若無可用 proxy 則回傳 None。
    """
    proxies = _scrape_proxynova()
    log.info(f"取得 {len(proxies)} 個台灣 proxy，開始測試…")
    for p in proxies:
        log.info(f"測試 {p}…")
        if _test_proxy(p):
            log.info(f"proxy 可用：{p}")
            return {"http": f"http://{p}", "https": f"http://{p}"}
        log.info(f"proxy 不可用：{p}")
    log.error("所有 proxy 均不可用")
    return None
