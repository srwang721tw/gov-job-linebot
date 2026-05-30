import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET", "")

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
SQLITE_PATH = str(DATA_DIR / "sqlite" / "subscriptions.db")

CRAWLER_BASE_URL = "https://web3.dgpa.gov.tw/want03front/AP"
CRAWLER_LIST_PAGE = "/WANTF00001.ASPX"

# 每次查詢最多爬幾頁（15筆/頁）。建議 3~5，0 = 不限（僅供測試）
MAX_CRAWL_PAGES = int(os.getenv("MAX_CRAWL_PAGES", "3"))

# 回傳給使用者的最大職缺數
TOP_K_RESULTS = int(os.getenv("TOP_K_RESULTS", "5"))
