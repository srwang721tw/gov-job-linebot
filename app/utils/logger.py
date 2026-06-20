"""Application-wide loguru logger configuration.

Replaces the loguru default handler with a single ``stdout`` sink that
emits ISO-timestamp structured lines with colorised level labels::

    2026-06-20 04:00:01 | INFO     | app.crawler.scraper:536 - Crawl complete
"""
import sys
from loguru import logger

logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} - {message}",
    level="INFO",
    colorize=True,
)
