from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.keyboards import main_kb
from database.repository import Repository
from core.proxy_scraper import scrape_free_proxies, scrape_proxies_from_webshare, check_proxy, check_proxy_for_site

router = Router()
session_factory = None


def setup(sf):
    global session_factory
    session_factory = sf


@router.message(Command("add_proxy"))
async def cmd_add_proxy(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Формат: /add_proxy http://user:pass@ip:port")
        return
    proxy_str = args[1]
    async with session_factory() as session:
        repo = Repository(session)
        await repo.add_proxy(proxy_str)
    await message.answer(f"✅ Прокси добавлен: {proxy_str}", reply_markup=main_kb())


@router.message(Command("scrape_proxies"))
async def cmd_scrape_proxies(message: Message):
    msg = await message.answer("🔍 Парсю бесплатные прокси...")
    raw = await scrape_free_proxies()
    typed = await scrape_proxies_from_webshare()
    proxy_type_map = dict(typed)

    valid = []
    for p in raw[:100]:
        ptype = proxy_type_map.get(p, "http")
        ok = await check_proxy(p)
        if ok:
            ok2 = await check_proxy_for_site(p)
            if ok2:
                valid.append((p, ptype))

    for p, ptype in typed:
        if p not in raw:
            ok = await check_proxy(p)
            if ok:
                ok2 = await check_proxy_for_site(p)
                if ok2:
                    valid.append((p, ptype))

    async with session_factory() as session:
        repo = Repository(session)
        await repo.add_proxies_bulk([v[0] for v in valid])

    await msg.edit_text(
        f"✅ Найдено {len(valid)} рабочих прокси.\n"
        f"Добавлено в пул. Используй /proxy_status для проверки."
    )


@router.message(Command("proxy_status"))
async def cmd_proxy_status(message: Message):
    from core.proxy_manager import ProxyManager
    pm = ProxyManager(session_factory)
    stats = await pm.get_proxy_stats()
    text = (
        f"🌐 <b>Прокси статус</b>\n"
        f"Всего: {stats['total']}\n"
        f"Живые: {stats['alive']}\n"
        f"В использовании: {stats['in_use']}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_kb())


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    async with session_factory() as session:
        repo = Repository(session)
        accounts = await repo.get_user_accounts(message.from_user.id)
    if not accounts:
        await message.answer("Нет аккаунтов")
        return
    total_diamonds = sum(a.diamonds for a in accounts)
    total_cards = sum(a.cards for a in accounts)
    running = sum(1 for a in accounts if a.status == "running")
    text = (
        f"📊 <b>Общая статистика</b>\n"
        f"Аккаунтов: {len(accounts)}\n"
        f"Запущено: {running}\n"
        f"💎 Всего алмазов: {total_diamonds}\n"
        f"🃏 Всего карт: {total_cards}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_kb())
