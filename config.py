import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("\"'")
                if key and not os.getenv(key):
                    os.environ[key] = val


_load_env()


@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    DB_URL: str = os.getenv("DB_URL", "sqlite+aiosqlite:///data/database.sqlite")
    MAX_CONCURRENT_ACCOUNTS: int = int(os.getenv("MAX_CONCURRENT", "10"))
    DATA_DIR: str = os.getenv("DATA_DIR", "data")
    PROXY_CHECK_TIMEOUT: int = 10

    ALLOWED_USERS: list[int] = field(default_factory=lambda: [
        int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x
    ])

    # MangaBuff URLs
    MANGA_BUFF_BASE: str = "https://mangabuff.ru"
    MANGA_BUFF_LOGIN: str = "https://mangabuff.ru/login"

    PROXY_SOURCES: list[str] = field(default_factory=lambda: [
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks4&timeout=10000&country=all",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=10000&country=all",
    ])


config = Config()
