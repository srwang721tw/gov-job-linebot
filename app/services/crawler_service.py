from app.crawler.scraper import crawl_all_jobs
from app.db.database import get_job_count, upsert_jobs
from app.rag.vector_store import rebuild_index
from app.utils.logger import logger


def run_crawl_and_index() -> dict:
    logger.info("Crawl job started")
    try:
        jobs = crawl_all_jobs()
        if not jobs:
            logger.warning("Crawl returned no jobs")
            return {"status": "warning", "message": "No jobs crawled", "count": 0}

        saved = upsert_jobs(jobs)
        logger.info(f"Saved {saved}/{len(jobs)} jobs to SQLite")

        rebuild_index(jobs)

        total = get_job_count()
        logger.info(f"Crawl done — DB total: {total}")
        return {"status": "ok", "crawled": len(jobs), "saved": saved, "total_in_db": total}

    except Exception as e:
        logger.error(f"Crawl job error: {e}")
        return {"status": "error", "message": str(e)}
