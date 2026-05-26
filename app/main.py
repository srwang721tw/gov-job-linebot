import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.api.routes import router
from app.db.database import init_db
from app.services.crawler_service import run_crawl_and_index
from app.utils.logger import logger

_scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up gov-job-linebot...")
    os.makedirs("data/sqlite", exist_ok=True)
    os.makedirs("data/chroma", exist_ok=True)

    init_db()

    _scheduler.add_job(
        run_crawl_and_index,
        trigger=CronTrigger(hour=2, minute=0),
        id="daily_crawl",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler started — daily crawl at 02:00 UTC")

    yield

    _scheduler.shutdown()
    logger.info("Shutdown complete")


app = FastAPI(title="Gov Job LINE Bot", version="1.0.0", lifespan=lifespan)
app.include_router(router)
