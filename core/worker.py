import asyncio
import random
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from automation.client import MangaBuffClient
from database.repository import Repository
from core.proxy_manager import ProxyManager
from core.task_registry import TASKS


class AccountWorker:
    def __init__(
        self,
        account_id: int,
        login: str,
        password: str,
        proxy: Optional[str],
        session_factory,
        proxy_manager: ProxyManager,
    ):
        self.account_id = account_id
        self.login = login
        self.password = password
        self.proxy = proxy
        self.session_factory = session_factory
        self.proxy_manager = proxy_manager
        self.client: Optional[MangaBuffClient] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def ensure_client(self):
        if self.client is None or self.client.page is None:
            if self.client:
                await self.client.close()
            self.client = MangaBuffClient(self.login, self.password, self.proxy)
            self.client.email = self.login
            try:
                await self.client.start()
            except Exception as e:
                await self.client.close()
                self.client = None
                raise RuntimeError(f"Start failed: {e}")
            logged = await self.client.login()
            if not logged:
                await self.client.close()
                self.client = None
                raise RuntimeError("Login failed")

    async def run_daily(self) -> dict:
        await self.ensure_client()
        result = await self.client.collect_daily_reward()
        await self._log("daily", result.get("message", ""), result.get("success", False))
        return result

    async def run_mine(self) -> dict:
        await self.ensure_client()
        async with self.session_factory() as session:
            repo = Repository(session)
            acc = await repo.get_account_by_id(self.account_id)
            strategy = acc.mine_strategy if acc else None
        result = await self.client.click_mine(strategy)
        await self._log("mine", result.get("message", ""), result.get("success", False))
        return result

    async def run_quiz(self) -> dict:
        await self.ensure_client()
        result = await self.client.do_quiz()
        await self._log("quiz", result.get("message", ""), result.get("success", False))
        return result

    async def run_comments(self) -> dict:
        await self.ensure_client()
        result = await self.client.post_auction_comments(13)
        await self._log("auction_comments", result.get("message", ""), result.get("success", False))
        return result

    async def run_ads(self) -> dict:
        await self.ensure_client()
        result = {"success": False, "message": ""}
        ok = await self.client.watch_ad()
        result["success"] = ok
        result["message"] = "Реклама просмотрена" if ok else "Реклама не найдена"
        await self._log("ad", result["message"], ok)
        return result

    async def run_read_manga(self, chapters: int = 75) -> dict:
        await self.ensure_client()
        async with self.session_factory() as session:
            repo = Repository(session)
            acc = await repo.get_account_by_id(self.account_id)
            start_from = (acc.last_read_chapter or 0) + 1
        result = await self.client.read_manga_chapters("https://mangabuff.ru/manga/lukizm/1/", start_from, chapters)
        last_chapter = result.get("last_chapter", start_from - 1)
        if last_chapter >= start_from:
            async with self.session_factory() as session:
                repo = Repository(session)
                await repo.update_account(self.account_id, last_read_chapter=last_chapter)
        await self._log("read_manga", result.get("message", ""), result.get("success", False))
        return result

    async def run_collect_chat(self) -> dict:
        await self.ensure_client()
        result = await self.client.collect_chat_diamond()
        await self._log("collect_chat", result.get("message", ""), result.get("success", False))
        return result

    async def run_event_free_card(self) -> dict:
        await self.ensure_client()
        result = await self.client.do_event_free_card()
        await self._log("event_free_card", result.get("message", ""), result.get("success", False))
        return result

    async def run_event_open_pack(self) -> dict:
        await self.ensure_client()
        result = await self.client.do_event_open_pack()
        await self._log("event_open_pack", result.get("message", ""), result.get("success", False))
        return result

    async def run_event_open_donat(self) -> dict:
        await self.ensure_client()
        result = await self.client.do_event_open_donat()
        await self._log("event_open_donat", result.get("message", ""), result.get("success", False))
        return result

    async def update_stats(self):
        try:
            await self.ensure_client()
            stats = await self.client.get_profile_stats()
            async with self.session_factory() as session:
                repo = Repository(session)
                await repo.update_account_stats(
                    self.account_id,
                    stats["diamonds"],
                    stats["cards"],
                    stats["level"],
                    stats["exp"],
                )
        except Exception:
            pass

    async def _log(self, action: str, message: str, success: bool = True):
        try:
            async with self.session_factory() as session:
                repo = Repository(session)
                await repo.add_log(self.account_id, action, message, success)
        except Exception:
            pass

    async def release(self):
        self._running = False
        if self.client:
            try:
                await self.client.close()
            except Exception:
                pass
            self.client = None
        if self.proxy:
            await self.proxy_manager.release_proxy(self.proxy)

    async def run_all_dailies(self, progress_callback=None) -> dict:
        results = {}
        async with self.session_factory() as session:
            repo = Repository(session)
            acc = await repo.get_account_by_id(self.account_id)
        tasks_to_run = [t for t in TASKS if t.category in ("daily", "event")]
        for task in tasks_to_run:
            if not self._running:
                break
            if acc:
                enabled = getattr(acc, task.toggle_field, task.default_enabled)
            else:
                enabled = task.default_enabled
            if not enabled:
                results[task.name] = {"success": False, "message": "Отключено в настройках"}
                continue
            if progress_callback:
                await progress_callback(task.name)
            method = getattr(self, task.worker_method, None)
            if method is None:
                results[task.name] = {"success": False, "message": "Метод не найден"}
                continue
            try:
                if task.requires_chapters is not None:
                    results[task.name] = await method(task.requires_chapters)
                else:
                    results[task.name] = await method()
            except Exception as e:
                results[task.name] = {"success": False, "message": str(e)}
            await asyncio.sleep(random.uniform(2, 5))
        await self.update_stats()
        return results
