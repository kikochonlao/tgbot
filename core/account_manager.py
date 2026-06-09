import asyncio
import random
import logging
from typing import Any
from datetime import datetime, timezone, timedelta

from database import Database
from mangabuff.client import MangabuffClient
from mangabuff.proxy_manager import ProxyManager
from config import UTC_OFFSET

logger = logging.getLogger(__name__)

DAILY_WINDOW_START = 10
DAILY_WINDOW_END = 16
DAILY_LIMIT = 50
MIN_DELAY = 4.0
MAX_DELAY = 12.0
MAX_ERRORS = 3
MAX_CONCURRENT = 5


class AccountManager:
    def __init__(self, db: Database, proxy_manager: ProxyManager) -> None:
        self.db = db
        self.proxy_manager = proxy_manager
        self._clients: dict[int, MangabuffClient] = {}
        self._running = False
        self._sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def start(self) -> None:
        self._running = True
        accounts = await self.db.get_all_accounts(active_only=True)
        logger.info(f"Starting {len(accounts)} accounts")
        staggered = [a for a in accounts]
        random.shuffle(staggered)
        for acc in staggered:
            asyncio.create_task(self._run_account_cycle(acc))
            delay = random.uniform(60, 1800)
            logger.info(f"Account {acc['email']} starts in {delay:.0f}s")
            await asyncio.sleep(delay)

    async def stop(self) -> None:
        self._running = False
        for client in self._clients.values():
            await client.close()
        self._clients.clear()

    async def add_account(self, email: str, password: str) -> int:
        acc_id = await self.db.add_account(email, password)
        if acc_id:
            acc = await self.db.get_account(acc_id)
            if acc and self._running:
                asyncio.create_task(self._run_account_cycle(acc))
        return acc_id

    async def remove_account(self, account_id: int) -> None:
        await self.db.update_account(account_id, is_active=0, status="removed")
        if account_id in self._clients:
            await self._clients[account_id].close()
            del self._clients[account_id]

    async def get_client(self, account_id: int) -> MangabuffClient | None:
        return self._clients.get(account_id)

    async def get_status(self) -> list[dict[str, Any]]:
        accounts = await self.db.get_all_accounts()
        result = []
        for acc in accounts:
            acc["has_session"] = acc["id"] in self._clients
            result.append(acc)
        return result

    async def _run_account_cycle(self, acc: dict) -> None:
        account_id = acc["id"]
        email = acc["email"]
        password = acc["password"]
        consecutive_errors = 0

        while self._running and consecutive_errors < MAX_ERRORS:
            try:
                is_active = acc.get("is_active", 1)
                if not is_active:
                    await asyncio.sleep(60)
                    acc = await self.db.get_account(account_id) or acc
                    continue

                now_utc = datetime.now(timezone.utc).hour
                now_local = (now_utc + UTC_OFFSET) % 24
                if not (DAILY_WINDOW_START <= now_local < DAILY_WINDOW_END):
                    await asyncio.sleep(3600)
                    continue

                await self.db.set_account_status(account_id, "active")
                proxy = await self.proxy_manager.get_proxy()
                client = MangabuffClient(
                    email=email,
                    password=password,
                    account_id=account_id,
                    proxy_url=proxy,
                )
                self._clients[account_id] = client

                ok = await client.login()
                if not ok:
                    consecutive_errors += 1
                    await self.db.increment_error(account_id)
                    await client.close()
                    if proxy:
                        await self.proxy_manager.return_proxy(proxy)
                    await asyncio.sleep(random.uniform(60, 120))
                    continue

                await self.db.set_account_status(account_id, "working")
                consecutive_errors = 0
                await self._do_work(account_id, client)
                await client.close()
                if proxy:
                    await self.proxy_manager.return_proxy(proxy)

                remaining = max(0, DAILY_WINDOW_END - now)
                sleep_min = remaining * 3600 if remaining > 1 else random.uniform(300, 600)
                await asyncio.sleep(random.uniform(sleep_min, sleep_min + 3600))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Account {email} cycle error: {e}")
                consecutive_errors += 1
                await self.db.increment_error(account_id)
                await asyncio.sleep(random.uniform(60, 120))

        if consecutive_errors >= MAX_ERRORS:
            await self.db.update_account(account_id, is_active=0, status="banned")
            logger.warning(f"Account {email} deactivated after {MAX_ERRORS} errors")
        await self.db.set_account_status(account_id, "idle")

    async def _do_work(self, account_id: int, client: MangabuffClient) -> None:
        conn_data = random.choice([
            {"slug": "fermerstvo-v-odinochku"},
            {"slug": "podnyatie-urovnya-v-odinochku"},
            {"slug": "vselennaya-starshego-brata"},
        ])
        slug = conn_data["slug"]

        try:
            info = await client.get_manga_info(slug)
            if not info or not info.get("chapters"):
                return
            chapters = info["chapters"]
            daily_read = await self.db.get_daily_read_count(account_id)
            if daily_read >= DAILY_LIMIT:
                return
            to_read = min(3, DAILY_LIMIT - daily_read)
            sample = random.sample(chapters, min(to_read, len(chapters)))

            for ch in sample:
                page = await client.get_chapter_page(slug, ch["volume"], ch["chapter"])
                if page and page.get("chapter_id"):
                    ok = await client.mark_chapter_read(
                        page["manga_id"], page["chapter_id"]
                    )
                    if ok:
                        await self.db.add_read_history(
                            account_id, page["manga_id"], ch["chapter"]
                        )
                        logger.info(f"Account {account_id} read ch.{ch['chapter']}")

                await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

                if random.random() < 0.3:
                    comment_ok = await client.post_comment(
                        page["chapter_id"],
                        random.choice(["интересно", "отлично", "спасибо"]),
                    )
                    if comment_ok:
                        await self.db.add_comment_history(
                            account_id, page["commentable_id"], ""
                        )
                        logger.info(f"Account {account_id} posted comment")

        except Exception as e:
            logger.error(f"Work error for account {account_id}: {e}")
