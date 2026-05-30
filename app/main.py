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
    yield
    logger.info("關閉完成")


app = FastAPI(title="Gov Job LINE Bot", version="2.0.0", lifespan=lifespan)
app.include_router(router)
