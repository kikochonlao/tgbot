from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.keyboards import settings_kb, mine_strategy_kb
from services.account_service import get_account, toggle_task

router = Router()

session_factory = None


def setup(sf):
    global session_factory
    session_factory = sf


@router.callback_query(F.data.startswith("settings_"))
async def cb_settings(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])
    acc = await get_account(session_factory, account_id)
    if acc:
        nick = acc.login.split("@")[0] if "@" in acc.login else acc.login
        await callback.message.edit_text(
            f"⚙ <b>{nick}</b>\nВкл/выкл задачи:",
            reply_markup=settings_kb(account_id, acc),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_"))
async def cb_toggle(callback: CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[1])
    task_name = parts[2]
    await toggle_task(session_factory, account_id, task_name)
    acc = await get_account(session_factory, account_id)
    if acc:
        await callback.message.edit_reply_markup(reply_markup=settings_kb(account_id, acc))
    await callback.answer()


@router.callback_query(F.data.startswith("mine_menu_"))
async def cb_mine_menu(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    await callback.message.edit_text(
        "⛏ Стратегия шахты:",
        reply_markup=mine_strategy_kb(account_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mine_"))
async def cb_mine_strategy(callback: CallbackQuery):
    parts = callback.data.split("_")
    strategy = parts[1]
    account_id = int(parts[2])
    db_strategy = None if strategy == "none" else strategy
    async with session_factory() as session:
        from database.repository import Repository
        repo = Repository(session)
        await repo.update_account(account_id, mine_strategy=db_strategy)
    await callback.message.edit_text("✅ Стратегия шахты изменена")
    await callback.answer()
