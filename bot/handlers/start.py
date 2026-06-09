from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from bot.keyboards import main_kb

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "🤖 <b>MangaBuff Bot</b>\n\n"
        "Этот бот автоматизирует ежедневные задачи на MangaBuff.\n\n"
        "<b>Команды:</b>\n"
        "/add_account <code>логин пароль</code> — добавить аккаунт\n"
        "/accounts — список аккаунтов\n"
        "/stats — общая статистика\n"
        "/add_proxy <code>http://user:pass@ip:port</code> — добавить прокси\n\n"
        "<i>P.S. Для работы нужны разные IP. Можно добавить свои прокси "
        "или бот попробует найти бесплатные.</i>",
        reply_markup=main_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "add_account")
async def cb_add_account(callback: CallbackQuery):
    await callback.message.edit_text(
        "Отправь логин и пароль через пробел:\n"
        "<code>/add_account ваш_логин ваш_пароль</code>",
        parse_mode="HTML",
    )
    await callback.answer()
