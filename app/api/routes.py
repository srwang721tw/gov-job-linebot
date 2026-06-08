from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from linebot.v3.exceptions import InvalidSignatureError

from app.db.database import get_jobs_count, get_subscription_count
from app.services.line_service import handler
from app.utils.logger import logger

router = APIRouter()


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "subscription_count": get_subscription_count(),
        "jobs_count": get_jobs_count(),
    }


# ── LINE webhook ──────────────────────────────────────────────────────────────

@router.post("/webhook")
async def line_webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("LINE webhook 簽章驗證失敗")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"LINE webhook 處理錯誤：{e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return JSONResponse(content={"status": "ok"})


# ── Telegram webhook ──────────────────────────────────────────────────────────

@router.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    from app.services.telegram_service import get_telegram_app
    tg = get_telegram_app()
    if tg is None:
        raise HTTPException(status_code=503, detail="Telegram bot 未啟用")

    from telegram import Update
    data = await request.json()
    update = Update.de_json(data, tg.bot)
    await tg.process_update(update)
    return JSONResponse(content={"ok": True})
