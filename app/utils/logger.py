import sys
from loguru import logger

logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} - {message}",
    level="INFO",
    colorize=True,
)
