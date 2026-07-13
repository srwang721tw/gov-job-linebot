"""Application configuration loaded from environment variables.

When ``DATABASE_URL`` is set the app connects to Neon PostgreSQL;
otherwise it falls back to a local SQLite file at ``SQLITE_PATH``.
All other settings have sensible defaults for local development.

On Railway, ``RAILWAY_PUBLIC_DOMAIN`` is injected automatically (e.g.
``gov-job-linebot.up.railway.app``).  Set ``APP_BASE_URL`` to override
for other hosting platforms or local tunnels (e.g. ngrok).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET", "")

# 設定後使用 Neon PostgreSQL；未設定則 fallback 到本機 SQLite（本機開發用）
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# Telegram Bot Token（從 @BotFather 取得）；未設定則停用 Telegram 功能
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
# Webhook URL（正式環境）；未設定則由 RAILWAY_PUBLIC_DOMAIN 自動組合
# 或可手動設定 TELEGRAM_WEBHOOK_URL 覆蓋（含 scheme）
TELEGRAM_WEBHOOK_URL: str = os.getenv("TELEGRAM_WEBHOOK_URL", "")


BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
SQLITE_PATH = str(DATA_DIR / "sqlite" / "jobs.db")

CRAWLER_BASE_URL = "https://web3.dgpa.gov.tw/want03front/AP"
CRAWLER_LIST_PAGE = "/WANTF00001.ASPX"

# 每次查詢最多爬幾頁（15筆/頁）。建議 3~5，0 = 不限
MAX_CRAWL_PAGES = int(os.getenv("MAX_CRAWL_PAGES", "3"))

# 排程爬蟲每頁最多爬幾頁（0 = 不限，抓全部）
MAX_CRAWL_PAGES_SCHEDULED = int(os.getenv("MAX_CRAWL_PAGES_SCHEDULED", "0"))

# 回傳給使用者的最大職缺數
TOP_K_RESULTS = int(os.getenv("TOP_K_RESULTS", "10"))

# 職缺詳細頁 URL
# Railway 自動提供 RAILWAY_PUBLIC_DOMAIN（e.g. "gov-job-linebot.up.railway.app"）
# 也可手動設定 APP_BASE_URL 覆蓋（含 scheme，e.g. "https://custom.domain.com"）
_public_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
_base_url = (f"https://{_public_domain}" if _public_domain
             else os.getenv("APP_BASE_URL", "http://localhost:8000"))
DETAIL_PAGE_URL = f"{_base_url}/detail"

# 詳細頁爬取間隔秒數（本機爬蟲用）
CRAWL_DETAIL_DELAY: float = float(os.getenv("CRAWL_DETAIL_DELAY", "0.3"))

# 保護 Telegram webhook 的 secret token（設定後需重新部署）
TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
