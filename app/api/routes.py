from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from linebot.v3.exceptions import InvalidSignatureError

from app.db.database import get_job_count
from app.services.crawler_service import run_crawl_and_index
from app.services.line_service import handler
from app.utils.logger import logger

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok", "job_count": get_job_count()}


@router.post("/webhook")
async def line_webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("Invalid LINE webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Webhook handler error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return JSONResponse(content={"status": "ok"})


@router.post("/crawl")
async def manual_crawl():
    logger.info("Manual crawl triggered via API")
    return run_crawl_and_index()
