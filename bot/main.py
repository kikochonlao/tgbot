import asyncio
import logging
import signal

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import config
from database.models import init_db
from core.proxy_manager import ProxyManager
from core.scheduler import AccountScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return

    session_factory = await init_db()
    proxy_manager = ProxyManager(session_factory)
    scheduler = AccountScheduler(session_factory, proxy_manager)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    from bot.handlers import start, accounts, actions, settings, stats
    accounts.setup(session_factory, scheduler)
    actions.setup(session_factory, scheduler)
    settings.setup(session_factory)
    stats.setup(session_factory)

    dp.include_router(start.router)
    dp.include_router(accounts.router)
    dp.include_router(actions.router)
    dp.include_router(settings.router)
    dp.include_router(stats.router)

    bg_tasks = [
        asyncio.create_task(scheduler.schedule_periodic_tasks()),
        asyncio.create_task(scheduler.schedule_hourly_manga()),
        asyncio.create_task(scheduler.schedule_daily_dailies()),
    ]

    try:
        await dp.start_polling(bot)
    finally:
        for t in bg_tasks:
            t.cancel()
        await asyncio.gather(*bg_tasks, return_exceptions=True)
        await bot.session.close()
        await scheduler.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
