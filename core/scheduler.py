import asyncio
import logging
import random
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import config
from database.repository import Repository
from database.models import Account
from core.worker import AccountWorker
from core.proxy_manager import ProxyManager
from core.task_registry import get_periodic_tasks, get_task

logger = logging.getLogger(__name__)


class AccountScheduler:
    def __init__(self, session_factory, proxy_manager: ProxyManager):
        self.session_factory = session_factory
        self.proxy_manager = proxy_manager
        self._workers: dict[int, AccountWorker] = {}
        self._tasks: dict[int, asyncio.Task] = {}

    async def start_account(self, account_id: int) -> bool:
        if account_id in self._workers and self._workers[account_id].is_running:
            return True

        async with self.session_factory() as session:
            repo = Repository(session)
            acc = await repo.get_account_by_id(account_id)
            if not acc or not acc.is_active:
                return False

            proxy = acc.proxy
            if not proxy:
                proxy = await self.proxy_manager.allocate_proxy(account_id)
                if proxy:
                    await repo.update_account(account_id, proxy=proxy)

            if not proxy:
                logger.warning(f"No proxy for account {account_id}, running without it")

        worker = AccountWorker(
            account_id=account_id,
            login=acc.login,
            password=acc.password,
            proxy=proxy,
            session_factory=self.session_factory,
            proxy_manager=self.proxy_manager,
        )
        worker._running = True
        self._workers[account_id] = worker
        await self._update_status(account_id, "running")
        return True

    async def stop_account(self, account_id: int):
        if account_id in self._tasks:
            self._tasks[account_id].cancel()
            del self._tasks[account_id]
        if account_id in self._workers:
            await self._workers[account_id].release()
            del self._workers[account_id]
        await self._update_status(account_id, "idle")

    async def run_account_dailies(self, account_id: int, progress_callback=None) -> Optional[dict]:
        worker = self._workers.get(account_id)
        if not worker or not worker.is_running:
            ok = await self.start_account(account_id)
            if not ok:
                return None
            worker = self._workers.get(account_id)

        result = await worker.run_all_dailies(progress_callback=progress_callback)
        await worker.update_stats()
        await self._update_status(account_id, "running")
        return result

    async def run_single_task(self, account_id: int, task_name: str) -> Optional[dict]:
        worker = self._workers.get(account_id)
        if not worker or not worker.is_running:
            ok = await self.start_account(account_id)
            if not ok:
                return None
            worker = self._workers.get(account_id)

        task_def = get_task(task_name)
        if not task_def:
            return None
        method = getattr(worker, task_def.worker_method, None)
        if method is None:
            return None
        if task_def.requires_chapters is not None:
            result = await method(task_def.requires_chapters)
        else:
            result = await method()
        await worker.update_stats()
        return result

    async def schedule_periodic_tasks(self):
        while True:
            try:
                async with self.session_factory() as session:
                    repo = Repository(session)
                    active_accounts = await repo.get_all_active_accounts()
                periodic_tasks = get_periodic_tasks()

                for acc in active_accounts:
                    account_id = acc.id
                    if account_id not in self._workers or not self._workers[account_id].is_running:
                        continue

                    worker = self._workers[account_id]
                    for ptask in periodic_tasks:
                        enabled = getattr(acc, ptask.toggle_field, ptask.default_enabled)
                        if not enabled:
                            continue
                        try:
                            method = getattr(worker, ptask.worker_method, None)
                            if method:
                                await method()
                                await asyncio.sleep(random.uniform(1, 3))
                        except Exception as e:
                            logger.error(f"Error in periodic {ptask.name} for {account_id}: {e}")
            except Exception as e:
                logger.error(f"Error in schedule_periodic_tasks: {e}")

            await asyncio.sleep(900)

    async def schedule_hourly_manga(self):
        while True:
            await asyncio.sleep(3600)
            try:
                async with self.session_factory() as session:
                    repo = Repository(session)
                    active_accounts = await repo.get_all_active_accounts()

                for acc in active_accounts:
                    account_id = acc.id
                    if account_id not in self._workers or not self._workers[account_id].is_running:
                        continue
                    if not acc.do_read_manga:
                        continue

                    worker = self._workers[account_id]
                    try:
                        await worker.run_read_manga(5)
                        await asyncio.sleep(5)
                    except Exception as e:
                        logger.error(f"Error in manga reading for {account_id}: {e}")
            except Exception as e:
                logger.error(f"Error in schedule_hourly_manga: {e}")

    async def schedule_daily_dailies(self):
        while True:
            await asyncio.sleep(86400)
            try:
                async with self.session_factory() as session:
                    repo = Repository(session)
                    active_accounts = await repo.get_all_active_accounts()

                for acc in active_accounts:
                    account_id = acc.id
                    if account_id not in self._workers or not self._workers[account_id].is_running:
                        continue

                    worker = self._workers[account_id]
                    try:
                        await worker.run_all_dailies()
                        await worker.update_stats()
                        await asyncio.sleep(random.uniform(5, 15))
                    except Exception as e:
                        logger.error(f"Error in daily for {account_id}: {e}")
            except Exception as e:
                logger.error(f"Error in schedule_daily_dailies: {e}")

    async def _update_status(self, account_id: int, status: str):
        try:
            async with self.session_factory() as session:
                repo = Repository(session)
                await repo.update_account(account_id, status=status)
        except Exception:
            pass

    async def stop_all(self):
        for account_id in list(self._workers.keys()):
            await self.stop_account(account_id)
