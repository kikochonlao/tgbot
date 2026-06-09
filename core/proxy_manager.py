import asyncio
import random
from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from database.models import Proxy as ProxyModel
from database.repository import Repository
from core.proxy_scraper import (
    check_proxy,
    scrape_free_proxies,
    scrape_proxies_from_webshare,
    check_proxy_for_site,
)


class ProxyManager:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def ensure_proxies(self, min_count: int = 20):
        async with self.session_factory() as session:
            repo = Repository(session)
            available = await repo.count_available_proxies()
            if available >= min_count:
                return
            raw = await scrape_free_proxies()
            typed = await scrape_proxies_from_webshare()
            proxy_type_map = dict(typed)

            valid = []
            for p in raw:
                ptype = proxy_type_map.get(p, "http")
                ok = await check_proxy(p)
                if ok:
                    ok2 = await check_proxy_for_site(p)
                    if ok2:
                        valid.append((p, ptype))

            if valid:
                await repo.add_proxies_bulk(
                    [p for p, _ in valid],
                    proxy_type="mixed",
                )

            for p, ptype in typed:
                if p not in raw:
                    ok = await check_proxy(p)
                    if ok:
                        ok2 = await check_proxy_for_site(p)
                        if ok2:
                            await repo.add_proxy(p, proxy_type=ptype)

    async def allocate_proxy(self, account_id: int) -> Optional[str]:
        async with self.session_factory() as session:
            repo = Repository(session)
            proxy = await repo.get_alive_proxy()
            if proxy is None:
                await self.ensure_proxies(5)
                proxy = await repo.get_alive_proxy()
            if proxy:
                await repo.assign_proxy(proxy.id, account_id)
                return proxy.proxy_string
            return None

    async def release_proxy(self, proxy_string: str):
        async with self.session_factory() as session:
            result = await session.execute(
                select(ProxyModel).where(ProxyModel.proxy_string == proxy_string)
            )
            proxy = result.scalar_one_or_none()
            if proxy:
                proxy.in_use_by = None
                await session.commit()

    async def mark_proxy_dead(self, proxy_string: str):
        async with self.session_factory() as session:
            result = await session.execute(
                select(ProxyModel).where(ProxyModel.proxy_string == proxy_string)
            )
            proxy = result.scalar_one_or_none()
            if proxy:
                proxy.is_alive = False
                proxy.in_use_by = None
                await session.commit()

    async def get_proxy_stats(self) -> dict:
        async with self.session_factory() as session:
            alive = await session.execute(
                select(func.count(ProxyModel.id)).where(ProxyModel.is_alive == True)
            )
            total = await session.execute(select(func.count(ProxyModel.id)))
            in_use = await session.execute(
                select(func.count(ProxyModel.id)).where(ProxyModel.in_use_by.isnot(None))
            )
            return {
                "total": total.scalar() or 0,
                "alive": alive.scalar() or 0,
                "in_use": in_use.scalar() or 0,
            }
