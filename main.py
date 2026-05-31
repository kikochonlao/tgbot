import asyncio
import logging
import os
import csv
from datetime import datetime, timezone

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, DATABASE_URL, ADMIN_CHAT_ID
from database import Database
from bot.handlers import router, init_services
from mangabuff.proxy_manager import ProxyManager
from core import AccountManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def health_check(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def run_http_server() -> None:
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8080)
    await site.start()
    logger.info("Health check server on :8080")


async def auto_import_accounts(db: Database) -> None:
    csv_path = os.path.join(os.path.dirname(__file__), "proxies", "accounts.csv")
    if not os.path.exists(csv_path):
        logger.info("accounts.csv не найден, пропускаю импорт")
        return
    count = await db.get_accounts_count()
    if count > 0:
        logger.info(f"Аккаунтов уже {count}, пропускаю импорт")
        return
    added = 0
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row.get("email", "").strip()
            password = row.get("password", "").strip()
            if email and password:
                acc_id = await db.add_account(email, password)
                if acc_id:
                    added += 1
    logger.info(f"Импортировано {added} аккаунтов из accounts.csv")


async def daily_report(bot: Bot, db: Database) -> None:
    if not ADMIN_CHAT_ID:
        return
    while True:
        now = datetime.now(timezone.utc)
        next_run = now.replace(hour=16, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run = next_run.replace(day=next_run.day + 1)
        wait = (next_run - now).total_seconds()
        await asyncio.sleep(wait)
        try:
            stats = await db.get_today_stats()
            text = (
                f"Дневной отчёт\n\n"
                f"Прочитано глав: {stats['reads']}\n"
                f"Комментариев: {stats['comments']}\n"
                f"Активно аккаунтов: {stats['active']}/{stats['total']}"
            )
            await bot.send_message(ADMIN_CHAT_ID, text)
        except Exception as e:
            logger.error(f"Daily report error: {e}")


async def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "your_telegram_bot_token_here":
        logger.error("BOT_TOKEN не указан в .env файле!")
        print("Ошибка: BOT_TOKEN не указан в .env")
        return

    db = Database(dsn=DATABASE_URL)
    await db.connect()
    if DATABASE_URL:
        logger.info("Database connected (PostgreSQL)")
    else:
        logger.info("Database connected (SQLite)")

    await auto_import_accounts(db)

    proxy_manager = ProxyManager(db)
    await proxy_manager.start()
    logger.info("Proxy manager started")

    account_manager = AccountManager(db, proxy_manager)
    await account_manager.start()
    logger.info("Account manager started")

    init_services(db, account_manager, proxy_manager)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    asyncio.create_task(run_http_server())

    if ADMIN_CHAT_ID:
        asyncio.create_task(daily_report(bot, db))

    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Бот запущен!")
    print("Бот запущен! Напиши /start в Telegram.")

    try:
        await dp.start_polling(bot)
    finally:
        await account_manager.stop()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
