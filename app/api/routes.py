"""FastAPI route handlers for all public API endpoints.

Endpoints:
    - ``GET  /health``            — health check with subscriber and job counts
    - ``GET  /detail``            — serve the static RWD job-search HTML page
    - ``GET  /api/jobs``          — JSON array of all active job postings
    - ``POST /webhook``           — LINE webhook (HMAC-SHA256 validated)
    - ``POST /telegram-webhook``  — Telegram webhook (Secret-Token validated)
"""
import hmac
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from linebot.v3.exceptions import InvalidSignatureError

from app.db.database import get_jobs_count, get_subscription_count
from app.services.line_service import handler
from app.utils.config import TELEGRAM_WEBHOOK_SECRET
from app.utils.logger import logger

router = APIRouter()

_STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("/health")
async def health_check():
    """Return application health status with live counts.

    Returns:
        JSON with ``status``, ``subscription_count``, and ``jobs_count``.
    """
    return {
        "status": "ok",
        "subscription_count": get_subscription_count(),
        "jobs_count": get_jobs_count(),
    }


@router.get("/detail", response_class=HTMLResponse)
def detail_page():
    """Serve the static RWD job-search HTML page.

    Returns:
        Full HTML content of ``app/static/detail.html``.
    """
    return (_STATIC_DIR / "detail.html").read_text(encoding="utf-8")


@router.get("/api/jobs")
def api_jobs():
    """Return all active job postings as a JSON array.

    Used by the ``/detail`` page to load job data on the client side.
    Applies no filters; the client handles filtering, sorting, and
    pagination in JavaScript.

    Returns:
        JSON array of job objects (max 5,000 rows).
    """
    from app.db.database import search_jobs
    jobs = search_jobs(limit=5000)
    return [
        {
            "title":            j.title,
            "org_name":         j.org_name,
            "work_place":       j.work_place,
            "rank_type":        j.rank_type,
            "rank_type_codes":  j.rank_type_codes,
            "rank_grade_min":   j.rank_grade_min,
            "rank_grade_max":   j.rank_grade_max,
            "job_series":       j.job_series,
            "sysnam_grp":       j.sysnam_grp,
            "deadline_start":   j.deadline_start,
            "deadline_end":     j.deadline_end,
            "job_url":          j.job_url,
        }
        for j in jobs
    ]


# ── LINE webhook ──────────────────────────────────────────────────────────────

@router.post("/webhook")
async def line_webhook(request: Request):
    """Handle incoming LINE webhook events.

    Validates the ``X-Line-Signature`` HMAC-SHA256 header before
    dispatching the request body to the LINE SDK handler.

    Args:
        request: Raw FastAPI ``Request`` object.

    Returns:
        ``{"status": "ok"}`` on success.

    Raises:
        HTTPException(400): If the LINE signature is invalid.
        HTTPException(500): On unexpected processing errors.
    """
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("LINE webhook signature validation failed")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"LINE webhook error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    return JSONResponse(content={"status": "ok"})


@router.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram webhook updates.

    Validates the ``X-Telegram-Bot-Api-Secret-Token`` header when
    ``TELEGRAM_WEBHOOK_SECRET`` is configured.  Deserialises the JSON
    body into a ``telegram.Update`` and dispatches it to the bot app.

    Args:
        request: Raw FastAPI ``Request`` object.

    Returns:
        ``{"ok": True}`` on success.

    Raises:
        HTTPException(403): If the secret token is set but does not match.
        HTTPException(503): If the Telegram bot is not initialised.
    """
    if TELEGRAM_WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(token, TELEGRAM_WEBHOOK_SECRET):
            raise HTTPException(status_code=403, detail="Forbidden")

    from app.services.telegram_service import get_telegram_app
    tg = get_telegram_app()
    if tg is None:
        raise HTTPException(status_code=503, detail="Telegram bot 未啟用")

    from telegram import Update
    data = await request.json()
    update = Update.de_json(data, tg.bot)
    await tg.process_update(update)
    return JSONResponse(content={"ok": True})
