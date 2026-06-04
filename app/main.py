import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.db.database import init_db
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("啟動 gov-job-linebot v3...")

    # ── 確保 SQLite 資料目錄存在 ───────────────────────────────────────────────
    os.makedirs("data/sqlite", exist_ok=True)

    # ── 初始化資料庫（建立資料表）─────────────────────────────────────────────
    init_db()

    # ── 排程器（APScheduler）─────────────────────────────────────────────────
    from app.scheduler.crawl_scheduler import start_scheduler
    start_scheduler()

    # ── Telegram Bot 初始化（選用）────────────────────────────────────────────
    from app.utils.config import TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_URL
    if TELEGRAM_BOT_TOKEN:
        from app.services.telegram_service import init_telegram

        webhook_url = TELEGRAM_WEBHOOK_URL
        if not webhook_url:
            render_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
            if render_url:
                webhook_url = f"{render_url}/telegram-webhook"

        await init_telegram(webhook_url)

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    from app.scheduler.crawl_scheduler import stop_scheduler
    stop_scheduler()

    if TELEGRAM_BOT_TOKEN:
        from app.services.telegram_service import shutdown_telegram
        await shutdown_telegram()

    logger.info("關閉完成")


app = FastAPI(title="Gov Job Bot", version="3.0.0", lifespan=lifespan)
app.include_router(router)
