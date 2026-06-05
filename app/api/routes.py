import asyncio

import requests as _requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from linebot.v3.exceptions import InvalidSignatureError

from app.db.database import get_jobs_count, get_subscription_count
from app.services.line_service import handler
from app.utils.config import CRAWL_SECRET, GITHUB_REPO, GITHUB_TOKEN
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


# ── 管理用爬取觸發 ────────────────────────────────────────────────────────────
# Render 伺服器無法連到 DGPA，改為透過 GitHub API 觸發 GitHub Actions workflow。
# cron-job.org 每日 18:00 UTC（台灣 02:00）打一次，或手動呼叫。

def _dispatch_github_workflow() -> tuple[bool, str]:
    """
    透過 GitHub repository_dispatch API 觸發 daily_crawl.yml workflow。
    回傳 (success, message)。
    """
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False, "GITHUB_TOKEN 或 GITHUB_REPO 未設定"

    url = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"event_type": "trigger-crawl"}
    try:
        r = _requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code == 204:
            return True, "GitHub Actions workflow 已觸發"
        return False, f"GitHub API 回應 {r.status_code}：{r.text[:200]}"
    except Exception as e:
        return False, f"GitHub API 呼叫失敗：{e}"


@router.post("/admin/trigger-crawl")
async def trigger_crawl(request: Request):
    """
    觸發每日職缺爬取（透過 GitHub Actions）。
    需在 Header 帶 X-Crawl-Secret: <CRAWL_SECRET>。
    若未設定 CRAWL_SECRET 則拒絕。
    """
    if not CRAWL_SECRET:
        raise HTTPException(status_code=403, detail="CRAWL_SECRET 未設定")

    secret = request.headers.get("X-Crawl-Secret", "")
    if secret != CRAWL_SECRET:
        raise HTTPException(status_code=403, detail="Invalid crawl secret")

    loop = asyncio.get_event_loop()
    success, message = await loop.run_in_executor(None, _dispatch_github_workflow)

    logger.info(f"trigger-crawl：{message}")
    if not success:
        raise HTTPException(status_code=500, detail=message)

    return JSONResponse(content={"status": "triggered", "detail": message})
