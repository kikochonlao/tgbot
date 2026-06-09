from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.keyboards import main_kb, accounts_list_kb, account_kb
from services.account_service import get_user_accounts, get_account

router = Router()

session_factory = None
scheduler = None


def setup(sf, sch=None):
    global session_factory, scheduler
    session_factory = sf
    scheduler = sch


@router.message(Command("add_account"))
async def cmd_add_account(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Формат: /add_account логин пароль")
        return
    login, password = args[1], args[2]
    async with session_factory() as session:
        from database.repository import Repository
        repo = Repository(session)
        acc = await repo.add_account(message.from_user.id, login, password)
    await message.answer(f"✅ <b>{login}</b> добавлен", parse_mode="HTML")


@router.message(Command("accounts"))
async def cmd_accounts(message: Message):
    accounts = await get_user_accounts(session_factory, message.from_user.id)
    if not accounts:
        await message.answer("Нет аккаунтов", reply_markup=main_kb())
        return
    text = f"📋 <b>Аккаунты</b> ({len(accounts)}):"
    await message.answer(text, reply_markup=accounts_list_kb(accounts, 0), parse_mode="HTML")


@router.callback_query(F.data == "my_accounts")
async def cb_my_accounts(callback: CallbackQuery):
    accounts = await get_user_accounts(session_factory, callback.from_user.id)
    if not accounts:
        await callback.message.edit_text("Нет аккаунтов", reply_markup=main_kb())
    else:
        text = f"📋 <b>Аккаунты</b> ({len(accounts)}):"
        await callback.message.edit_text(text, reply_markup=accounts_list_kb(accounts, 0), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("acc_page_"))
async def cb_acc_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[2])
    accounts = await get_user_accounts(session_factory, callback.from_user.id)
    if accounts:
        await callback.message.edit_reply_markup(reply_markup=accounts_list_kb(accounts, page))
    await callback.answer()


@router.callback_query(F.data.startswith("sel_acc_"))
async def cb_sel_account(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    acc = await get_account(session_factory, account_id)
    if acc:
        from services.account_service import format_account_text
        text = format_account_text(acc)
        await callback.message.edit_text(text, reply_markup=account_kb(account_id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "back_to_list")
async def cb_back_to_list(callback: CallbackQuery):
    accounts = await get_user_accounts(session_factory, callback.from_user.id)
    if accounts:
        text = f"📋 <b>Аккаунты</b> ({len(accounts)}):"
        await callback.message.edit_text(text, reply_markup=accounts_list_kb(accounts, 0), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "🤖 <b>MangaBuff Bot</b>\n\nВыбери действие:",
        reply_markup=main_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("back_"))
async def cb_back(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])
    acc = await get_account(session_factory, account_id)
    if acc:
        from services.account_service import format_account_text
        text = format_account_text(acc)
        await callback.message.edit_text(text, reply_markup=account_kb(account_id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("delete_"))
async def cb_delete(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])
    if scheduler:
        await scheduler.stop_account(account_id)
    async with session_factory() as session:
        from database.repository import Repository
        repo = Repository(session)
        acc = await repo.get_account_by_id(account_id)
        nick = acc.login.split("@")[0] if acc else account_id
        await repo.delete_account(account_id)
    await callback.message.edit_text(f"🗑 {nick} удалён")
    await callback.answer()


@router.message(Command("import"))
async def cmd_import(message: Message):
    text = message.text.removeprefix("/import").strip()
    if not text and message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    if not text:
        await message.answer(
            "Пришли список аккаунтов (3 строки на каждый):\n"
            "<code>Никнейм\nemail@domain.com\nпароль</code>",
            parse_mode="HTML",
        )
        return

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    accounts = []
    i = 0
    while i < len(lines):
        name = lines[i].split("  X")[0].split(" X")[0].strip()
        i += 1
        if i < len(lines) and "@" in lines[i]:
            email = lines[i].strip()
            i += 1
            password = "555555"
            if i < len(lines) and lines[i].isdigit():
                password = lines[i].strip()
                i += 1
            accounts.append((name, email, password))
        else:
            break

    if not accounts:
        await message.answer("Ничего не распознано")
        return

    added = 0
    errors = []
    async with session_factory() as session:
        from database.repository import Repository
        repo = Repository(session)
        for name, email, pw in accounts:
            try:
                await repo.add_account(message.from_user.id, email, pw)
                added += 1
            except Exception as e:
                errors.append(f"{name}: {e}")

    text = f"✅ Импортировано: {added}"
    if errors:
        text += f"\n❌ Ошибок: {len(errors)}"
    await message.answer(text)
