import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.db.database import init_db
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("啟動 gov-job-linebot...")
    os.makedirs("data/sqlite", exist_ok=True)
    init_db()

    # ── Telegram Bot 初始化（選用）────────────────────────────────────────────
    from app.utils.config import TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_URL
    if TELEGRAM_BOT_TOKEN:
        from app.services.telegram_service import init_telegram

        # 決定 webhook URL
        # 優先使用明確設定的 TELEGRAM_WEBHOOK_URL
        # 其次自動從 Render 提供的 RENDER_EXTERNAL_URL 組合
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


app = FastAPI(title="Gov Job LINE Bot", version="2.1.0", lifespan=lifespan)
app.include_router(router)
