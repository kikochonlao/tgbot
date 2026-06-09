import asyncio
import json
import logging
import os
import aiohttp
import random
from typing import Any

from database import Database

logger = logging.getLogger(__name__)

PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/As207111/Free-Proxy-Collection/main/http.txt",
    "https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/http/http.txt",
]

TEST_URL = "https://mangabuff.ru"
TEST_TIMEOUT = 10
MIN_PROXY_POOL = 10
HEALTH_CHECK_INTERVAL = 300

PROXY_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "proxies", "alive.json")


class ProxyManager:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._alive_cache: list[str] = []
        self._lock = asyncio.Lock()
        self._collecting = False

    async def start(self) -> None:
        loaded = self._load_cache()
        if loaded:
            logger.info(f"Загружено {len(loaded)} прокси из файла, проверка не нужна")
            async with self._lock:
                self._alive_cache = loaded
                for url in loaded:
                    await self._queue.put(url)
        else:
            logger.info("Файл прокси пуст, собираю и проверяю...")
            await self._collect_and_fill()
            self._save_cache()
        asyncio.create_task(self._health_loop())

    def _load_cache(self) -> list[str]:
        try:
            if os.path.exists(PROXY_CACHE_FILE):
                with open(PROXY_CACHE_FILE) as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) >= MIN_PROXY_POOL:
                    return data
        except Exception as e:
            logger.warning(f"Ошибка загрузки кэша прокси: {e}")
        return []

    def _save_cache(self) -> None:
        try:
            with open(PROXY_CACHE_FILE, "w") as f:
                json.dump(self._alive_cache, f, indent=2)
            logger.info(f"Сохранено {len(self._alive_cache)} живых прокси в {PROXY_CACHE_FILE}")
        except Exception as e:
            logger.warning(f"Ошибка сохранения кэша прокси: {e}")

    async def get_proxy(self) -> str | None:
        if not self._queue.empty():
            return await self._queue.get()
        async with self._lock:
            if self._alive_cache:
                proxy = random.choice(self._alive_cache)
                return proxy
        return None

    async def return_proxy(self, proxy: str) -> None:
        if proxy:
            await self._queue.put(proxy)

    async def _collect_and_fill(self) -> None:
        if self._collecting:
            return
        self._collecting = True
        try:
            count = await self._fetch_proxies()
            if count > 0:
                logger.info(f"Collected {count} new proxies")
            await self._validate_all()
            await self._fill_queue()
        finally:
            self._collecting = False

    async def _fetch_proxies(self) -> int:
        total = 0
        max_per_source = 500
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            for source in PROXY_SOURCES:
                try:
                    async with session.get(source) as resp:
                        if resp.status != 200:
                            continue
                        text = await resp.text()
                        count = 0
                        for line in text.splitlines():
                            if count >= max_per_source:
                                break
                            line = line.strip()
                            if not line or ":" not in line:
                                continue
                            parts = line.split(":")
                            if len(parts) == 2:
                                ip, port = parts[0].strip(), parts[1].strip()
                                if ip.count(".") == 3 and port.isdigit():
                                    url = f"http://{ip}:{port}"
                                    await self.db.add_proxy(url, "http")
                                    total += 1
                                    count += 1
                except Exception as e:
                    logger.debug(f"Source {source} error: {e}")
        return total

    async def _validate_all(self) -> None:
        proxies = await self.db.get_dead_proxies()
        alive_db = await self.db.get_alive_proxies(limit=100)
        to_check = proxies[:200] + alive_db
        if not to_check:
            return

        total = len(to_check)
        done = 0
        alive_count = 0
        logger.info(f"Начинаю проверку {total} прокси...")

        sem = asyncio.Semaphore(20)

        async def check(p: dict) -> None:
            nonlocal done, alive_count
            async with sem:
                alive, latency = await self._check_proxy(p["url"])
                await self.db.update_proxy_status(p["id"], alive, latency)
                done += 1
                if alive:
                    alive_count += 1
                if done % 100 == 0 or done == total:
                    logger.info(f"Проверено {done}/{total} (живых: {alive_count})")

        tasks = [check(p) for p in to_check]
        await asyncio.gather(*tasks)
        logger.info(f"Проверка завершена: {done}/{total}, живых: {alive_count}")

    async def _check_proxy(self, proxy_url: str) -> tuple[bool, int]:
        import time
        start = time.monotonic()
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=TEST_TIMEOUT)
            ) as session:
                async with session.get(
                    TEST_URL,
                    proxy=proxy_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                ) as resp:
                    latency = int((time.monotonic() - start) * 1000)
                    if resp.status < 400:
                        logger.info(f"Прокси {proxy_url} — живой ({latency}ms)")
                        return True, latency
                    logger.warning(f"Прокси {proxy_url} — мертвый (статус {resp.status})")
                    return False, 0
        except Exception as e:
            logger.warning(f"Прокси {proxy_url} — мертвый ({e})")
            return False, 0

    async def _fill_queue(self) -> None:
        alive = await self.db.get_alive_proxies(limit=30)
        async with self._lock:
            self._alive_cache = [p["url"] for p in alive]
            for url in self._alive_cache:
                await self._queue.put(url)
        logger.info(f"Proxy queue filled: {len(self._alive_cache)} alive")

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
            try:
                if self._queue.qsize() < MIN_PROXY_POOL:
                    await self._collect_and_fill()
                    self._save_cache()
                await self.db.clean_dead_proxies()
            except Exception as e:
                logger.error(f"Health check error: {e}")

    async def get_stats(self) -> dict[str, int]:
        stats = await self.db.proxy_pool_stats()
        stats["queue"] = self._queue.qsize()
        return stats

    async def get_random_proxy(self) -> str | None:
        return await self.get_proxy()

    async def report_bad(self, proxy_url: str) -> None:
        pass  # will be handled by health check
