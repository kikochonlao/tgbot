import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
MANGABUFF_EMAIL: str = os.getenv("MANGABUFF_EMAIL", "")
MANGABUFF_PASSWORD: str = os.getenv("MANGABUFF_PASSWORD", "")
DAILY_READ_LIMIT: int = int(os.getenv("DAILY_READ_LIMIT", "50"))
COMMENT_INTERVAL_MIN: int = int(os.getenv("COMMENT_INTERVAL_MIN", "5"))
UTC_OFFSET: int = int(os.getenv("UTC_OFFSET", "5"))

MANGABUFF_BASE: str = "https://mangabuff.ru"
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
ADMIN_CHAT_ID: int = int(os.getenv("ADMIN_CHAT_ID", "0"))
