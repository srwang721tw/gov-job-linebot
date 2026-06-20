"""FastAPI application entry point for the Taiwan Government Job Bot.

Startup sequence (managed by the async ``lifespan`` context manager):
    1. Ensure the SQLite data directory exists (local-dev fallback).
    2. Call ``init_db()`` to create / migrate database tables.
    3. If ``TELEGRAM_BOT_TOKEN`` is set, initialise the Telegram bot and
       register the webhook URL (auto-derived from ``RENDER_EXTERNAL_URL``
       when ``TELEGRAM_WEBHOOK_URL`` is not explicitly set).

Shutdown: ``shutdown_telegram()`` is called if the Telegram bot is active.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.db.database import init_db
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle.

    Args:
        app: The FastAPI application instance (injected by FastAPI).

    Yields:
        Control to the running application after startup completes.
    """
    logger.info("Starting gov-job-linebot v3.3...")

    # ── 確保 SQLite 資料目錄存在（本機開發 fallback 用）──────────────────────────
    os.makedirs("data/sqlite", exist_ok=True)

    # ── 初始化資料庫（建立資料表）─────────────────────────────────────────────
    init_db()

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
    if TELEGRAM_BOT_TOKEN:
        from app.services.telegram_service import shutdown_telegram
        await shutdown_telegram()

    logger.info("關閉完成")


app = FastAPI(title="Gov Job Bot", version="3.2.0", lifespan=lifespan)
app.include_router(router)
