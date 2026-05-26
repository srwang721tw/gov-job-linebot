import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET", "")

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
SQLITE_PATH = str(DATA_DIR / "sqlite" / "jobs.db")
CHROMA_PATH = str(DATA_DIR / "chroma")

CRAWLER_BASE_URL = "https://web3.dgpa.gov.tw/want03front/AP"
CRAWLER_LIST_PAGE = "/WANTF00001.ASPX"

TOP_K_RESULTS = int(os.getenv("TOP_K_RESULTS", "3"))
# Multilingual model — handles Traditional Chinese + mixed queries well
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
CHROMA_COLLECTION = "jobs"

# Limit pages per crawl run (15 jobs/page). 0 = unlimited.
MAX_CRAWL_PAGES = int(os.getenv("MAX_CRAWL_PAGES", "0"))
