from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from linebot.v3.exceptions import InvalidSignatureError

from app.db.database import get_jobs_count, get_subscription_count
from app.services.line_service import handler
from app.utils.config import CRAWL_SECRET
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


# ── 管理用爬取觸發（cron-job.org 每日打一次）─────────────────────────────────

@router.post("/admin/trigger-crawl")
async def trigger_crawl(request: Request, background: BackgroundTasks):
    """
    觸發每日職缺爬取。
    需在 Header 帶 X-Crawl-Secret: <CRAWL_SECRET>。
    若未設定 CRAWL_SECRET 則拒絕（避免未設定時任何人都可觸發）。
    """
    if not CRAWL_SECRET:
        raise HTTPException(status_code=403, detail="CRAWL_SECRET 未設定")

    secret = request.headers.get("X-Crawl-Secret", "")
    if secret != CRAWL_SECRET:
        raise HTTPException(status_code=403, detail="Invalid crawl secret")

    from app.scheduler.crawl_scheduler import daily_crawl_task
    background.add_task(daily_crawl_task)
    logger.info("手動觸發爬取任務（/admin/trigger-crawl）")
    return JSONResponse(content={"status": "triggered"})
