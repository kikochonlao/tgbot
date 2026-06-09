from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from core.task_registry import get_settings_tasks

ITEMS_PER_PAGE = 8


def account_kb(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="▶ Запустить", callback_data=f"start_{account_id}"),
            InlineKeyboardButton(text="⏹ Стоп", callback_data=f"stop_{account_id}"),
        ],
        [
            InlineKeyboardButton(text="📊 Стат.", callback_data=f"stats_{account_id}"),
            InlineKeyboardButton(text="📋 Логи", callback_data=f"logs_{account_id}"),
        ],
        [
            InlineKeyboardButton(text="⚙ Настройки", callback_data=f"settings_{account_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{account_id}"),
        ],
        [
            InlineKeyboardButton(text="🔙 К списку", callback_data="back_to_list"),
        ],
    ])


def accounts_list_kb(accounts: list, page: int = 0) -> InlineKeyboardMarkup:
    buttons = []
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_accounts = accounts[start:end]

    for acc in page_accounts:
        status_emoji = {"idle": "💤", "running": "▶", "paused": "⏸", "error": "❌"}
        se = status_emoji.get(acc.status, "💤")
        nick = acc.login.split("@")[0][:12] if "@" in acc.login else acc.login[:12]
        buttons.append([
            InlineKeyboardButton(
                text=f"{se} {nick} | 💎{acc.diamonds}",
                callback_data=f"sel_acc_{acc.id}",
            )
        ])

    nav = []
    total_pages = (len(accounts) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"acc_page_{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if end < len(accounts):
        nav.append(InlineKeyboardButton(text="Вперёд ▶", callback_data=f"acc_page_{page + 1}"))
    if nav:
        buttons.append(nav)

    if len(accounts) > 0:
        buttons.append([
            InlineKeyboardButton(text="▶ Запустить все", callback_data="start_all"),
            InlineKeyboardButton(text="⏹ Стоп все", callback_data="stop_all"),
        ])

    buttons.append([InlineKeyboardButton(text="🔙 В меню", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def settings_kb(account_id: int, acc=None) -> InlineKeyboardMarkup:
    buttons = []
    if acc:
        for task in get_settings_tasks():
            enabled = getattr(acc, task.toggle_field, task.default_enabled)
            status = "✅" if enabled else "❌"
            buttons.append([
                InlineKeyboardButton(
                    text=f"{status} {task.label}",
                    callback_data=f"toggle_{account_id}_{task.name}",
                )
            ])
    buttons.append([
        InlineKeyboardButton(text="⛏ Стратегия шахты", callback_data=f"mine_menu_{account_id}"),
    ])
    buttons.append([
        InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_{account_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def mine_strategy_kb(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💎 Копить", callback_data=f"mine_none_{account_id}"),
            InlineKeyboardButton(text="🔄 Обмен", callback_data=f"mine_exchange_{account_id}"),
            InlineKeyboardButton(text="⬆ Улучшать", callback_data=f"mine_upgrade_{account_id}"),
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"settings_{account_id}")],
    ])


def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои аккаунты", callback_data="my_accounts")],
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_account")],
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="global_stats")],
        [InlineKeyboardButton(text="🌐 Прокси статус", callback_data="proxy_status")],
    ])
