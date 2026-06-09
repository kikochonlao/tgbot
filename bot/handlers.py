import re
import csv
import io
import asyncio
import random
import logging
from typing import Any

from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, Document
from aiogram.fsm.context import FSMContext

from config import DAILY_READ_LIMIT, COMMENT_INTERVAL_MIN
from mangabuff import MangabuffClient
from database import Database
from core import AccountManager
from mangabuff.proxy_manager import ProxyManager
from .keyboard import main_menu, settings_menu, account_menu, back_button, confirm_mine
from .states import AutoRead, AddComment, Settings, AddAccount, ImportCSV

router = Router()
logger = logging.getLogger(__name__)

user_manga: dict[int, list[dict[str, Any]]] = {}
user_settings: dict[int, dict[str, Any]] = {}

_db: Database | None = None
_account_manager: AccountManager | None = None
_proxy_manager: ProxyManager | None = None


def init_services(db: Database, am: AccountManager, pm: ProxyManager) -> None:
    global _db, _account_manager, _proxy_manager
    _db = db
    _account_manager = am
    _proxy_manager = pm


def get_client() -> MangabuffClient:
    return MangabuffClient()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 <b>MangaBuff Multi-Account Bot</b>\n\n"
        "Многоаккаунтный бот для автоматического чтения манхвы, "
        "комментариев и майнинга алмазов на mangabuff.ru\n\n"
        "Используй меню ниже или команды:\n"
        "/stats — общая статистика\n"
        "/menu — главное меню\n"
        "/add slug — добавить тайтл",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "total_stats")
async def show_total_stats(cb: CallbackQuery) -> None:
    if not _db or not _account_manager or not _proxy_manager:
        await cb.answer("❌ Сервисы не инициализированы")
        return

    today = await _db.get_today_stats()
    all_accounts = await _account_manager.get_status()
    proxy_stats = await _proxy_manager.get_stats()
    total_read_all = sum(a.get("total_read", 0) for a in all_accounts)
    total_comments_all = sum(a.get("total_comments", 0) for a in all_accounts)
    active = sum(1 for a in all_accounts if a.get("is_active"))
    banned = sum(1 for a in all_accounts if a.get("status") == "banned")

    lines = [
        "📊 <b>Общая статистика</b>\n",
        f"👤 <b>Аккаунты:</b> {len(all_accounts)} всего, {active} активны, {banned} забанено",
        f"📖 <b>Прочитано глав:</b> {today['reads']} сегодня / {total_read_all} всего",
        f"💬 <b>Комментариев:</b> {today['comments']} сегодня / {total_comments_all} всего",
        f"🖥 <b>Прокси:</b> {proxy_stats['alive']} живых / {proxy_stats['total']} всего",
    ]
    await cb.message.edit_text("\n".join(lines), reply_markup=back_button())
    await cb.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _db or not _account_manager or not _proxy_manager:
        await message.answer("❌ Сервисы не инициализированы")
        return

    today = await _db.get_today_stats()
    all_accounts = await _account_manager.get_status()
    proxy_stats = await _proxy_manager.get_stats()
    total_read_all = sum(a.get("total_read", 0) for a in all_accounts)
    total_comments_all = sum(a.get("total_comments", 0) for a in all_accounts)
    active = sum(1 for a in all_accounts if a.get("is_active"))
    banned = sum(1 for a in all_accounts if a.get("status") == "banned")

    lines = [
        "📊 <b>Общая статистика</b>\n",
        f"👤 <b>Аккаунты:</b> {len(all_accounts)} всего, {active} активны, {banned} забанено",
        f"📖 <b>Прочитано глав:</b> {today['reads']} сегодня / {total_read_all} всего",
        f"💬 <b>Комментариев:</b> {today['comments']} сегодня / {total_comments_all} всего",
        f"🖥 <b>Прокси:</b> {proxy_stats['alive']} живых / {proxy_stats['total']} всего\n",
        "▸ /menu — главное меню",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer("Главное меню:", reply_markup=main_menu())


@router.callback_query(F.data == "back_main")
async def back_to_main(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("Главное меню:", reply_markup=main_menu())
    await cb.answer()


# ── Account status ──

@router.callback_query(F.data == "account_status")
async def show_account_status(cb: CallbackQuery) -> None:
    if not _account_manager:
        await cb.answer("❌ Менеджер аккаунтов не инициализирован")
        return

    accounts = await _account_manager.get_status()
    lines = ["📊 <b>Аккаунты:</b>\n"]
    for a in accounts:
        status_icon = "🟢" if a["is_active"] else "🔴"
        lines.append(
            f"{status_icon} {a['email'][:20]}... — {a['status']}"
            f" (ошибок: {a['error_count']})"
            f" [чтение: {a['total_read']}, комм: {a['total_comments']}]"
        )

    if not accounts:
        lines.append("Нет аккаунтов. Добавь через настройки.")

    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=account_menu(),
    )
    await cb.answer()


@router.callback_query(F.data == "account_detail")
async def show_account_detail(cb: CallbackQuery) -> None:
    if not _account_manager:
        await cb.answer("❌ Менеджер аккаунтов не инициализирован")
        return

    accounts = await _account_manager.get_status()
    lines = ["📊 <b>Детальный статус аккаунтов:</b>\n"]
    for a in accounts:
        lines.append(
            f"ID: {a['id']} | {a['email'][:25]}...\n"
            f"├ Статус: {a['status']} | {'🟢 Активен' if a['is_active'] else '🔴 Неактивен'}\n"
            f"├ Прочитано: {a['total_read']} глав всего\n"
            f"├ Комментариев: {a['total_comments']}\n"
            f"├ Ошибок: {a['error_count']}"
        )

    if len(lines) == 1:
        lines.append("Нет аккаунтов в системе.")

    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=back_button(),
    )
    await cb.answer()


@router.callback_query(F.data == "today_stats")
async def show_today_stats(cb: CallbackQuery) -> None:
    if not _db:
        await cb.answer("❌ База данных не инициализирована")
        return

    stats = await _db.get_today_stats()
    lines = [
        "📅 <b>Статистика за сегодня:</b>\n",
        f"📖 Прочитано глав: {stats['reads']}",
        f"💬 Комментариев: {stats['comments']}",
        f"🟢 Активных аккаунтов: {stats['active']}/{stats['total']}",
    ]
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=back_button(),
    )
    await cb.answer()


@router.callback_query(F.data == "proxy_stats")
async def show_proxy_stats(cb: CallbackQuery) -> None:
    if not _proxy_manager:
        await cb.answer("❌ Менеджер прокси не инициализирован")
        return

    stats = await _proxy_manager.get_stats()
    lines = [
        "🖥 <b>Статус прокси:</b>\n",
        f"🟢 Живых: {stats['alive']}",
        f"🔴 Мёртвых: {stats['dead']}",
        f"📊 Всего: {stats['total']}",
        f"📥 В очереди: {stats['queue']}",
    ]
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=back_button(),
    )
    await cb.answer()


# ── Settings ──

@router.callback_query(F.data == "settings")
async def show_settings(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        "⚙ <b>Настройки</b>\n\n"
        "Управляй аккаунтами и лимитами:",
        reply_markup=settings_menu(),
    )
    await cb.answer()


@router.callback_query(F.data == "change_account")
async def change_account(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.message.edit_text(
        "🔑 Введи email и пароль от mangabuff.ru в формате:\n"
        "<code>email:пароль</code>\n\n"
        "Или нажми Назад.",
        reply_markup=back_button(),
    )
    await state.set_state(Settings.waiting_for_value)
    await cb.answer()


@router.message(Settings.waiting_for_value)
async def process_account_change(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if ":" not in text:
        await message.answer("❌ Неверный формат. Используй <code>email:пароль</code>")
        return

    email, password = text.split(":", 1)
    if _account_manager:
        acc_id = await _account_manager.add_account(email.strip(), password.strip())
        if acc_id:
            await message.answer(
                f"✅ Аккаунт {email.strip()} добавлен (ID: {acc_id}).\n"
                "Он будет запущен автоматически."
            )
        else:
            await message.answer("⚠ Аккаунт уже существует в базе.")
    else:
        client = get_client()
        try:
            ok = await client.login(email.strip(), password.strip())
            if ok:
                await message.answer("✅ Успешно авторизован на mangabuff.ru!")
                user_settings[message.from_user.id] = {
                    "email": email.strip(),
                    "password": password.strip(),
                }
            else:
                await message.answer("❌ Ошибка входа. Проверь email и пароль.")
        finally:
            await client.close()
    await state.clear()


@router.callback_query(F.data == "add_account")
async def add_account_handler(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.message.edit_text(
        "➕ <b>Добавление аккаунта</b>\n\n"
        "Введи email и пароль в формате:\n"
        "<code>email:пароль</code>\n\n"
        "Или нажми Назад.",
        reply_markup=back_button(),
    )
    await state.set_state(AddAccount.waiting_for_credentials)
    await cb.answer()


@router.message(AddAccount.waiting_for_credentials)
async def process_add_account(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if ":" not in text:
        await message.answer("❌ Неверный формат. Используй <code>email:пароль</code>")
        return

    email, password = text.split(":", 1)
    if _account_manager:
        acc_id = await _account_manager.add_account(email.strip(), password.strip())
        if acc_id:
            await message.answer(f"✅ Аккаунт {email.strip()} добавлен (ID: {acc_id}).")
        else:
            await message.answer("⚠ Аккаунт уже существует.")
    else:
        await message.answer("❌ Менеджер аккаунтов не инициализирован.")
    await state.clear()


@router.callback_query(F.data == "import_csv")
async def import_csv_handler(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.message.edit_text(
        "📥 <b>Импорт аккаунтов из CSV</b>\n\n"
        "Пришли файл .csv с колонками: email,password\n"
        "Или используй формат: email:пароль (по одному на строку)",
        reply_markup=back_button(),
    )
    await state.set_state(ImportCSV.waiting_for_file)
    await cb.answer()


@router.message(ImportCSV.waiting_for_file)
async def process_import_csv(message: Message, state: FSMContext) -> None:
    if not _account_manager:
        await message.answer("❌ Менеджер аккаунтов не инициализирован.")
        await state.clear()
        return

    if message.document:
        doc = message.document
        if not doc.file_name.endswith(".csv"):
            await message.answer("❌ Пожалуйста, пришли файл с расширением .csv")
            return
        file = await message.bot.download(doc)
        content = file.read().decode("utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        added = 0
        skipped = 0
        for row in reader:
            if len(row) >= 2:
                email, password = row[0].strip(), row[1].strip()
                if email and password:
                    acc_id = await _account_manager.add_account(email, password)
                    if acc_id:
                        added += 1
                    else:
                        skipped += 1
        await message.answer(f"✅ Импортировано: {added}, пропущено: {skipped}")
    else:
        text = message.text.strip()
        added = 0
        skipped = 0
        for line in text.splitlines():
            line = line.strip()
            if ":" in line:
                email, password = line.split(":", 1)
                email, password = email.strip(), password.strip()
                if email and password:
                    acc_id = await _account_manager.add_account(email, password)
                    if acc_id:
                        added += 1
                    else:
                        skipped += 1
        await message.answer(f"✅ Добавлено: {added}, пропущено: {skipped}")
    await state.clear()


# ── Manga management ──

@router.callback_query(F.data == "my_manga")
async def show_my_manga(cb: CallbackQuery) -> None:
    uid = cb.from_user.id
    manga_list = user_manga.get(uid, [])
    if not manga_list:
        await cb.message.edit_text(
            "📋 Список тайтлов пуст.\n\n"
            "Чтобы добавить, используй /add <code>slug</code>\n"
            "Например: /add fermerstvo-v-odinochku",
            reply_markup=back_button(),
        )
        await cb.answer()
        return

    lines = ["📋 <b>Мои тайтлы:</b>\n"]
    for m in manga_list:
        lines.append(f"• {m.get('title', m['slug'])} — {m.get('chapters', 0)} глав")
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=back_button(),
    )
    await cb.answer()


@router.message(Command("add"))
async def add_manga(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Укажи slug тайтла.\nПример: /add fermerstvo-v-odinochku")
        return

    slug = args[1].strip().rstrip("/")
    if slug.startswith("https://"):
        m = re.search(r"/manga/([^/]+)", slug)
        if m:
            slug = m.group(1)

    client = get_client()
    try:
        info = await client.get_manga_info(slug)
        uid = message.from_user.id
        if uid not in user_manga:
            user_manga[uid] = []
        user_manga[uid].append({
            "slug": slug,
            "title": info["title"],
            "chapters": len(info["chapters"]),
            "chapter_list": info["chapters"],
        })
        await message.answer(
            f"✅ Добавлен тайтл: <b>{info['title']}</b>\n"
            f"📖 Всего глав: {len(info['chapters'])}"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    finally:
        await client.close()


# ── Read & Comment (single session) ──

@router.callback_query(F.data == "read_manga")
async def read_manga_menu(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id
    manga_list = user_manga.get(uid, [])
    if not manga_list:
        await cb.message.edit_text(
            "❌ Сначала добавь тайтл через /add <code>slug</code>",
            reply_markup=back_button(),
        )
        await cb.answer()
        return

    lines = ["📖 <b>Выбери тайтл для чтения:</b>\n"]
    for i, m in enumerate(manga_list, 1):
        lines.append(f"{i}. {m.get('title', m['slug'])}")
    await cb.message.edit_text(
        "\n".join(lines) + "\n\nОтправь номер тайтла:",
        reply_markup=back_button(),
    )
    await state.set_state(AutoRead.waiting_for_slug)
    await cb.answer()


@router.message(AutoRead.waiting_for_slug)
async def process_read_manga(message: Message, state: FSMContext) -> None:
    try:
        idx = int(message.text.strip()) - 1
    except ValueError:
        await message.answer("❌ Введи число.")
        return

    uid = message.from_user.id
    manga_list = user_manga.get(uid, [])
    if idx < 0 or idx >= len(manga_list):
        await message.answer("❌ Неверный номер.")
        return

    manga = manga_list[idx]
    await state.update_data(selected_manga=manga)
    await message.answer(
        f"Сколько глав прочитать из <b>{manga.get('title', manga['slug'])}</b>?\n"
        f"(максимум {DAILY_READ_LIMIT})",
        reply_markup=back_button(),
    )
    await state.set_state(AutoRead.waiting_for_count)


@router.message(AutoRead.waiting_for_count)
async def process_read_count(message: Message, state: FSMContext) -> None:
    try:
        count = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи число.")
        return

    if count > DAILY_READ_LIMIT:
        count = DAILY_READ_LIMIT

    data = await state.get_data()
    manga = data["selected_manga"]
    chapters = manga.get("chapter_list", [])
    if not chapters:
        await message.answer("❌ Нет глав для чтения.")
        await state.clear()
        return

    to_read = chapters[-count:] if count <= len(chapters) else chapters
    msg = await message.answer(f"📖 Начинаю чтение {len(to_read)} глав...")

    client = get_client()
    try:
        ok = await login_if_needed(client, message.from_user.id)
        if not ok:
            await message.answer("❌ Авторизуйся в настройках.")
            await state.clear()
            return

        read_count = 0
        for ch in to_read:
            ch_info = await client.get_chapter_page(
                manga["slug"], ch["volume"], ch["chapter"]
            )
            if ch_info:
                await client.mark_chapter_read(
                    ch_info["manga_id"], ch_info["chapter_id"]
                )
                read_count += 1

            await asyncio.sleep(random.uniform(3, 7))

        await msg.edit_text(
            f"✅ Прочитано <b>{read_count}</b> глав из <b>{manga.get('title', manga['slug'])}</b>"
        )
    finally:
        await client.close()
    await state.clear()


@router.callback_query(F.data == "add_comment")
async def comment_menu(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id
    manga_list = user_manga.get(uid, [])
    if not manga_list:
        await cb.message.edit_text(
            "❌ Сначала добавь тайтл через /add <code>slug</code>",
            reply_markup=back_button(),
        )
        await cb.answer()
        return

    lines = ["💬 <b>Выбери тайтл для комментария:</b>\n"]
    for i, m in enumerate(manga_list, 1):
        lines.append(f"{i}. {m.get('title', m['slug'])}")
    await cb.message.edit_text(
        "\n".join(lines) + "\n\nОтправь номер тайтла:",
        reply_markup=back_button(),
    )
    await state.set_state(AddComment.waiting_for_chapter)
    await cb.answer()


@router.message(AddComment.waiting_for_chapter)
async def process_comment_chapter(message: Message, state: FSMContext) -> None:
    try:
        idx = int(message.text.strip()) - 1
    except ValueError:
        await message.answer("❌ Введи число.")
        return

    uid = message.from_user.id
    manga_list = user_manga.get(uid, [])
    if idx < 0 or idx >= len(manga_list):
        await message.answer("❌ Неверный номер.")
        return

    await state.update_data(comment_manga=manga_list[idx])
    await message.answer(
        "💬 Введи текст комментария (или несколько через разделитель |):",
        reply_markup=back_button(),
    )
    await state.set_state(AddComment.waiting_for_text)


@router.message(AddComment.waiting_for_text)
async def process_comment_text(message: Message, state: FSMContext) -> None:
    texts = [t.strip() for t in message.text.split("|") if t.strip()]
    if not texts:
        await message.answer("❌ Текст не может быть пустым.")
        return

    data = await state.get_data()
    manga = data["comment_manga"]
    chapters = manga.get("chapter_list", [])
    if not chapters:
        await message.answer("❌ Нет глав для комментирования.")
        await state.clear()
        return

    msg = await message.answer(f"💬 Оставляю {len(texts)} комментариев...")

    client = get_client()
    try:
        ok = await login_if_needed(client, message.from_user.id)
        if not ok:
            await message.answer("❌ Авторизуйся в настройках.")
            await state.clear()
            return

        posted = 0
        for i, text in enumerate(texts):
            idx = min(i, len(chapters) - 1)
            ch = chapters[idx]
            ch_info = await client.get_chapter_page(
                manga["slug"], ch["volume"], ch["chapter"]
            )
            if ch_info:
                ok = await client.post_comment(
                    commentable_id=ch_info["chapter_id"],
                    text=text,
                )
                if ok:
                    posted += 1

            await asyncio.sleep(random.uniform(COMMENT_INTERVAL_MIN, COMMENT_INTERVAL_MIN + 3))

        await msg.edit_text(
            f"✅ Оставлено <b>{posted}/{len(texts)}</b> комментариев"
        )
    finally:
        await client.close()
    await state.clear()


@router.callback_query(F.data == "mine_diamonds")
async def mine_menu(cb: CallbackQuery) -> None:
    uid = cb.from_user.id
    manga_list = user_manga.get(uid, [])
    if not manga_list:
        await cb.message.edit_text(
            "❌ Сначала добавь тайтл через /add <code>slug</code>",
            reply_markup=back_button(),
        )
        await cb.answer()
        return

    await cb.message.edit_text(
        "⛏ <b>Майнинг алмазов</b>\n\n"
        "Бот будет:\n"
        "1️⃣ Читать непрочитанные главы\n"
        "2️⃣ Оставлять комментарии\n"
        "3️⃣ Собирать алмазы\n\n"
        "Готов начать?",
        reply_markup=confirm_mine(),
    )
    await cb.answer()


@router.callback_query(F.data == "mine_start")
async def mine_start(cb: CallbackQuery) -> None:
    await cb.message.edit_text("⛏ Запускаю майнинг...")

    uid = cb.from_user.id
    manga_list = user_manga.get(uid, [])

    client = get_client()
    try:
        ok = await login_if_needed(client, uid)
        if not ok:
            await cb.message.answer("❌ Авторизуйся в настройках.")
            return

        total_read = 0
        total_comments = 0
        comments_pool = [
            "Класс!", "Интересная глава", "Жду продолжения", "Круто!",
            "Отлично", "Неплохо", "Хорошая глава", "Спасибо за перевод",
            "Ждём следующую главу", "Топ",
        ]

        for manga in manga_list:
            chapters = manga.get("chapter_list", [])
            for ch in chapters:
                if total_read >= DAILY_READ_LIMIT:
                    break

                ch_info = await client.get_chapter_page(
                    manga["slug"], ch["volume"], ch["chapter"]
                )
                if ch_info:
                    await client.mark_chapter_read(
                        ch_info["manga_id"], ch_info["chapter_id"]
                    )
                    total_read += 1

                    if total_read % 5 == 0:
                        text = random.choice(comments_pool)
                        ok = await client.post_comment(
                            commentable_id=ch_info["chapter_id"],
                            text=text,
                        )
                        if ok:
                            total_comments += 1

                await asyncio.sleep(random.uniform(2, 5))

            if total_read >= DAILY_READ_LIMIT:
                break

        await cb.message.edit_text(
            f"✅ <b>Майнинг завершён!</b>\n\n"
            f"📖 Прочитано глав: {total_read}\n"
            f"💬 Оставлено комментариев: {total_comments}\n"
            f"⛏ Алмазы начислены автоматически!",
            reply_markup=main_menu(),
        )
    finally:
        await client.close()


async def login_if_needed(client: MangabuffClient, user_id: int) -> bool:
    settings = user_settings.get(user_id)
    if not settings:
        return False
    client.email = settings["email"]
    client.password = settings["password"]
    ok = await client.login()
    return ok
