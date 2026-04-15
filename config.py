"""
Configuration module for Fanatec Stock Searcher.
Loads settings from environment variables (or .env file).
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(Path(__file__).parent / ".env")

# ── Telegram ─────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_USER_ID: int = int(os.getenv("TELEGRAM_ADMIN_USER_ID", "0"))

# ── Fanatec ──────────────────────────────────────────────────────────
FANATEC_URL: str = os.getenv(
    "FANATEC_URL",
    "https://www.fanatec.com/eu/en/c/certified-refurbished",
)
FANATEC_BASE_URL: str = "https://www.fanatec.com"

# ── Scheduling ───────────────────────────────────────────────────────
CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "10"))

# ── Database ─────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", str(Path(__file__).parent / "products.db"))

# ── Scraper settings ─────────────────────────────────────────────────
SCRAPER_TIMEOUT: int = int(os.getenv("SCRAPER_TIMEOUT", "30"))
USE_PLAYWRIGHT_ONLY: bool = os.getenv("USE_PLAYWRIGHT_ONLY", "false").lower() == "true"

# ── Logging ──────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    format="%(asctime)s | %(name)-18s | %(levelname)-7s | %(message)s",
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
)
logger = logging.getLogger("fanatec_bot")


def validate_config() -> bool:
    """Validate that all required configuration is present."""
    errors: list[str] = []

    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN is not set.")
    if TELEGRAM_ADMIN_USER_ID == 0:
        errors.append("TELEGRAM_ADMIN_USER_ID is not set.")

    if errors:
        for err in errors:
            logger.error(f"Config error: {err}")
        return False

    logger.info("Configuration validated successfully.")
    logger.info(f"  Target URL  : {FANATEC_URL}")
    logger.info(f"  Check every : {CHECK_INTERVAL_MINUTES} minutes")
    logger.info(f"  DB path     : {DB_PATH}")
    return True
