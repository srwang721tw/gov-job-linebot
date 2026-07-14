"""Dynamic proxy pool for DGPA access from non-Taiwan cloud hosts.

Scrapes Taiwan HTTPS proxies from proxynova.com, then validates each
candidate by confirming the DGPA page returns a real ``__VIEWSTATE``
hidden field — not just an HTTP 200 from a proxy error page.

Typical usage:
    proxy_dict = get_working_proxy()
    if proxy_dict:
        session.proxies.update(proxy_dict)
"""
import re
import time
import logging

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_PROXYNOVA_URL = "https://www.proxynova.com/proxy-server-list/country-tw/"
_TEST_URL = "https://web3.dgpa.gov.tw/want03front/AP/WANTF00001.ASPX"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _scrape_proxynova() -> list[str]:
    """Scrape Taiwan proxy list from proxynova.com.

    Parses each table row: IP is extracted from the ``<abbr title>``
    attribute (format ``NNN-NNN-NNN-NNN.hostname``); port is extracted
    from the second ``<td>`` as the first 2-to-5-digit number.

    Returns:
        List of proxy strings in ``"IP:PORT"`` format.  Empty list if
        the page cannot be fetched or contains no valid rows.
    """
    try:
        r = requests.get(_PROXYNOVA_URL, headers=_HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
    except Exception as e:
        log.warning(f"proxynova fetch failed: {e}")
        return []

    proxies = []
    for row in soup.select("tr"):
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        abbr = tds[0].find("abbr")
        if not abbr:
            continue
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


def _test_proxy(proxy_str: str, read_timeout: int = 15) -> bool:
    """Test whether a proxy can reach the DGPA job board.

    Validates by checking for ``__VIEWSTATE`` in the response body,
    which confirms the proxy returned the real ASP.NET page rather
    than its own error or redirect page.

    Uses a tuple timeout ``(5, read_timeout)`` so a slow proxy that
    cannot establish a TCP connection is abandoned within 5 seconds
    rather than waiting the full read timeout.

    Args:
        proxy_str: Proxy address in ``"IP:PORT"`` format.
        read_timeout: Read timeout in seconds. Defaults to 15.

    Returns:
        True if the DGPA page was successfully retrieved through this
        proxy, False otherwise.
    """
    proxy_dict = {"http": f"http://{proxy_str}", "https": f"http://{proxy_str}"}
    try:
        r = requests.get(_TEST_URL, proxies=proxy_dict, timeout=(5, read_timeout))
        return "__VIEWSTATE" in r.text
    except Exception:
        return False


def get_working_proxy(max_seconds: int = 300) -> dict | None:
    """Return the first validated Taiwan proxy as a requests proxy dict.

    Fetches the current proxy list from proxynova.com and tests each
    entry sequentially against the DGPA site.  Returns as soon as a
    working proxy is found, or ``None`` if the time budget is exhausted.

    Args:
        max_seconds: Maximum total seconds to spend testing proxies.
            Defaults to 300 (5 minutes).

    Returns:
        A ``requests``-compatible proxy dict, e.g.::

            {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}

        Returns ``None`` if no working proxy is found within ``max_seconds``.
    """
    proxies = _scrape_proxynova()
    log.info(f"Found {len(proxies)} Taiwan proxies, testing (budget: {max_seconds}s)...")
    deadline = time.time() + max_seconds
    for p in proxies:
        if time.time() > deadline:
            log.error(f"Proxy testing exceeded {max_seconds}s budget, giving up")
            return None
        log.info(f"Testing {p}...")
        if _test_proxy(p):
            log.info(f"Proxy working: {p}")
            return {"http": f"http://{p}", "https": f"http://{p}"}
        log.info(f"Proxy failed: {p}")
    log.error("No working proxy found")
    return None
