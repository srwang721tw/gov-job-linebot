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
# Webhook URL（正式環境）；未設定則 Telegram 不接收訊息（本機開發用 ngrok）
# Render 會自動提供 RENDER_EXTERNAL_URL，程式會自動組合 /telegram-webhook 路徑
TELEGRAM_WEBHOOK_URL: str = os.getenv("TELEGRAM_WEBHOOK_URL", "")

# 保護 /admin/trigger-crawl 端點的 secret key
# 設定後須在請求 header 帶上 X-Crawl-Secret: <此值>，cron-job.org 每日觸發用
CRAWL_SECRET: str = os.getenv("CRAWL_SECRET", "")

# GitHub Actions 觸發爬蟲（Render 無法連到 DGPA，改由 GitHub Actions 執行）
# GITHUB_TOKEN：Personal Access Token（需有 repo 或 actions:write 權限）
# GITHUB_REPO：格式 "owner/repo"，例如 "srwang721tw/gov-job-linebot"
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO:  str = os.getenv("GITHUB_REPO", "")

# 設為 true 可停用 APScheduler（Render 上不需要排程，由 GitHub Actions 負責）
DISABLE_SCHEDULER: bool = os.getenv("DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes")

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
SQLITE_PATH = str(DATA_DIR / "sqlite" / "jobs.db")

CRAWLER_BASE_URL = "https://web3.dgpa.gov.tw/want03front/AP"
CRAWLER_LIST_PAGE = "/WANTF00001.ASPX"

# 每次查詢最多爬幾頁（15筆/頁）。建議 3~5，0 = 不限
MAX_CRAWL_PAGES = int(os.getenv("MAX_CRAWL_PAGES", "3"))

# 排程爬蟲每頁最多爬幾頁（0 = 不限，抓全部）
MAX_CRAWL_PAGES_SCHEDULED = int(os.getenv("MAX_CRAWL_PAGES_SCHEDULED", "0"))

# 詳細頁爬取間隔（秒），避免對 DGPA 造成過大負擔
CRAWL_DETAIL_DELAY = float(os.getenv("CRAWL_DETAIL_DELAY", "0.3"))

# 回傳給使用者的最大職缺數
TOP_K_RESULTS = int(os.getenv("TOP_K_RESULTS", "5"))
