from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.keyboards import main_kb, account_kb
from services.account_service import get_user_accounts, get_account, format_results_text
from core.task_registry import get_task, TASKS
from database.repository import Repository

router = Router()

session_factory = None
scheduler = None


def setup(sf, sch):
    global session_factory, scheduler
    session_factory = sf
    scheduler = sch


@router.callback_query(F.data == "start_all")
async def cb_start_all(callback: CallbackQuery):
    accounts = await get_user_accounts(session_factory, callback.from_user.id)
    if not accounts:
        await callback.message.edit_text("Нет аккаунтов")
        await callback.answer()
        return

    msg = await callback.message.edit_text("🔄 Проверяю аккаунты...")
    chat_id = callback.message.chat.id
    summary = []

    for acc in accounts:
        nick = acc.login.split("@")[0] if "@" in acc.login else acc.login

        async with session_factory() as session:
            repo = Repository(session)
            completed = await repo.get_today_completed_actions(acc.id)
            repo_acc = await repo.get_account_by_id(acc.id)

        enabled_tasks = [t for t in TASKS if getattr(repo_acc, t.toggle_field, False)]
        remaining = [t for t in enabled_tasks if t.get_log_action() not in completed]

        if not remaining:
            summary.append(f"✅ {nick}: уже всё выполнено")
            continue

        ok = await scheduler.start_account(acc.id)
        if not ok:
            summary.append(f"❌ {nick}: не удалось запустить")
            continue

        try:
            await msg.edit_text(f"▶ {nick} — выполняю задачи...")

            async def on_progress(task_name: str, _nick=nick):
                task_def = get_task(task_name)
                label = task_def.label if task_def else task_name
                try:
                    await msg.edit_text(f"⏳ {_nick} — {label}...")
                except Exception:
                    pass

            result = await scheduler.run_account_dailies(acc.id, progress_callback=on_progress)

            done = sum(1 for r in result.values() if r.get("success")) if result else 0
            total = len(result) if result else 0
            icon = "✅" if done == total else "⚠"
            summary.append(f"{icon} {nick}: {done}/{total}")
        except Exception as e:
            summary.append(f"❌ {nick}: {e}")
        finally:
            await scheduler.stop_account(acc.id)

    text = "📋 <b>Результаты:</b>\n" + "\n".join(summary)
    try:
        await msg.edit_text(text, parse_mode="HTML")
    except Exception:
        await callback.bot.send_message(chat_id, text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "stop_all")
async def cb_stop_all(callback: CallbackQuery):
    accounts = await get_user_accounts(session_factory, callback.from_user.id)
    for acc in accounts:
        await scheduler.stop_account(acc.id)
    await callback.message.edit_text("⏹ Все остановлены")
    await callback.answer()


@router.callback_query(F.data.startswith("start_"))
async def cb_start_account(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])

    msg = await callback.message.edit_text("🔄 Запускаю...")
    chat_id = callback.message.chat.id

    ok = await scheduler.start_account(account_id)
    if not ok:
        await msg.edit_text("❌ Не удалось запустить (может нет прокси?)")
        await callback.answer()
        return

    last_msg = msg

    async def on_progress(task_name: str):
        nonlocal last_msg
        task_def = get_task(task_name)
        label = task_def.label if task_def else task_name
        try:
            await last_msg.delete()
        except Exception:
            pass
        try:
            last_msg = await callback.bot.send_message(chat_id, f"⏳ {label}...")
        except Exception:
            last_msg = None

    result = await scheduler.run_account_dailies(account_id, progress_callback=on_progress)

    if last_msg:
        try:
            await last_msg.delete()
        except Exception:
            pass

    if result:
        text = format_results_text(result)
        await callback.bot.send_message(chat_id, text, parse_mode="HTML")
    else:
        await callback.bot.send_message(chat_id, "⚠ Не удалось выполнить задачи")
    await callback.answer()


@router.callback_query(F.data.startswith("stop_"))
async def cb_stop_account(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])
    await scheduler.stop_account(account_id)
    await callback.message.edit_text("⏹ Остановлен")
    await callback.answer()


@router.callback_query(F.data.startswith("stats_"))
async def cb_stats(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])
    acc = await get_account(session_factory, account_id)
    if acc:
        from services.account_service import format_account_text
        text = format_account_text(acc)
        try:
            await callback.message.edit_text(text, reply_markup=account_kb(account_id), parse_mode="HTML")
        except Exception:
            pass
    await callback.answer()


@router.callback_query(F.data.startswith("logs_"))
async def cb_logs(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])
    async with session_factory() as session:
        from database.repository import Repository
        repo = Repository(session)
        logs = await repo.get_account_logs(account_id, 10)
    if not logs:
        text = f"📋 <b>Логов нет</b>\n<i>После запуска здесь появятся записи</i>"
    else:
        lines = []
        for log in logs:
            emoji = "✅" if log.success else "❌"
            time_str = log.created_at.strftime("%H:%M %d.%m")
            lines.append(f"{emoji} {time_str} - {log.action}: {log.message or ''}")
        text = "📋 <b>Логи:</b>\n" + "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=account_kb(account_id), parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "global_stats")
async def cb_global_stats(callback: CallbackQuery):
    accounts = await get_user_accounts(session_factory, callback.from_user.id)
    if not accounts:
        await callback.message.edit_text("Нет аккаунтов", reply_markup=main_kb())
    else:
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
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_kb())
    await callback.answer()


@router.callback_query(F.data == "proxy_status")
async def cb_proxy_status(callback: CallbackQuery):
    from core.proxy_manager import ProxyManager
    pm = ProxyManager(session_factory)
    stats = await pm.get_proxy_stats()
    text = (
        f"🌐 <b>Прокси</b>\n"
        f"Всего: {stats['total']}\n"
        f"Живые: {stats['alive']}\n"
        f"В использовании: {stats['in_use']}"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_kb())
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()
