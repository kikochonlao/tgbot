from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import TelegramUser, Account, AccountLog, Proxy


class Repository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Users ──

    async def get_or_create_user(self, telegram_id: int, username: Optional[str] = None) -> TelegramUser:
        result = await self.session.execute(
            select(TelegramUser).where(TelegramUser.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = TelegramUser(telegram_id=telegram_id, username=username)
            self.session.add(user)
            await self.session.commit()
        elif username and user.username != username:
            user.username = username
            await self.session.commit()
        return user

    # ── Accounts ──

    async def add_account(self, telegram_id: int, login: str, password: str, proxy: Optional[str] = None) -> Account:
        user = await self.get_or_create_user(telegram_id)
        account = Account(
            telegram_user_id=user.id,
            login=login,
            password=password,
            proxy=proxy,
        )
        self.session.add(account)
        await self.session.commit()
        return account

    async def get_user_accounts(self, telegram_id: int) -> list[Account]:
        user = await self.get_or_create_user(telegram_id)
        result = await self.session.execute(
            select(Account).where(Account.telegram_user_id == user.id)
        )
        return list(result.scalars().all())

    async def get_account_by_id(self, account_id: int) -> Optional[Account]:
        result = await self.session.execute(
            select(Account).where(Account.id == account_id)
        )
        return result.scalar_one_or_none()

    async def update_account(self, account_id: int, **kwargs) -> Optional[Account]:
        await self.session.execute(
            update(Account).where(Account.id == account_id).values(**kwargs)
        )
        await self.session.commit()
        return await self.get_account_by_id(account_id)

    async def delete_account(self, account_id: int):
        await self.session.execute(
            delete(Account).where(Account.id == account_id)
        )
        await self.session.commit()

    async def update_account_stats(self, account_id: int, diamonds: int, cards: int, level: int, exp: int):
        await self.session.execute(
            update(Account).where(Account.id == account_id).values(
                diamonds=diamonds,
                cards=cards,
                level=level,
                exp=exp,
                last_stats_update=datetime.now(timezone.utc),
            )
        )
        await self.session.commit()

    async def get_all_active_accounts(self) -> list[Account]:
        result = await self.session.execute(
            select(Account).where(Account.is_active == True)
        )
        return list(result.scalars().all())

    # ── Logs ──

    async def add_log(self, account_id: int, action: str, message: Optional[str] = None, success: bool = True):
        log = AccountLog(account_id=account_id, action=action, message=message, success=success)
        self.session.add(log)
        await self.session.commit()

    async def get_today_completed_actions(self, account_id: int) -> set[str]:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.session.execute(
            select(AccountLog.action)
            .where(
                AccountLog.account_id == account_id,
                AccountLog.success == True,
                AccountLog.created_at >= today_start,
            )
        )
        return {row[0] for row in result.all()}

    async def get_account_logs(self, account_id: int, limit: int = 10) -> list[AccountLog]:
        result = await self.session.execute(
            select(AccountLog)
            .where(AccountLog.account_id == account_id)
            .order_by(AccountLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # ── Proxies ──

    async def add_proxy(self, proxy_string: str, proxy_type: str = "http") -> Proxy:
        existing = await self.session.execute(
            select(Proxy).where(Proxy.proxy_string == proxy_string)
        )
        if existing.scalar_one_or_none() is None:
            proxy = Proxy(proxy_string=proxy_string, proxy_type=proxy_type)
            self.session.add(proxy)
            await self.session.commit()
            return proxy
        return existing.scalar_one_or_none()

    async def add_proxies_bulk(self, proxies: list[str], proxy_type: str = "http"):
        for p in proxies:
            existing = await self.session.execute(
                select(Proxy).where(Proxy.proxy_string == p)
            )
            if existing.scalar_one_or_none() is None:
                self.session.add(Proxy(proxy_string=p, proxy_type=proxy_type))
        await self.session.commit()

    async def get_alive_proxy(self) -> Optional[Proxy]:
        result = await self.session.execute(
            select(Proxy)
            .where(Proxy.is_alive == True, Proxy.in_use_by.is_(None))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_proxy_dead(self, proxy_id: int):
        await self.session.execute(
            update(Proxy).where(Proxy.id == proxy_id).values(is_alive=False)
        )
        await self.session.commit()

    async def assign_proxy(self, proxy_id: int, account_id: int):
        await self.session.execute(
            update(Proxy).where(Proxy.id == proxy_id).values(in_use_by=account_id)
        )
        await self.session.commit()

    async def release_proxy(self, proxy_id: int):
        await self.session.execute(
            update(Proxy).where(Proxy.id == proxy_id).values(in_use_by=None)
        )
        await self.session.commit()

    async def count_available_proxies(self) -> int:
        result = await self.session.execute(
            select(Proxy).where(Proxy.is_alive == True, Proxy.in_use_by.is_(None))
        )
        return len(list(result.scalars().all()))
