from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="📖 Читать манхву", callback_data="read_manga"),
        InlineKeyboardButton(text="💬 Комментировать", callback_data="add_comment"),
    )
    b.row(
        InlineKeyboardButton(text="⛏ Майнить алмазы", callback_data="mine_diamonds"),
        InlineKeyboardButton(text="📊 Аккаунты", callback_data="account_status"),
    )
    b.row(
        InlineKeyboardButton(text="📋 Мои тайтлы", callback_data="my_manga"),
        InlineKeyboardButton(text="⚙ Настройки", callback_data="settings"),
    )
    b.row(
        InlineKeyboardButton(text="📈 Общая статистика", callback_data="total_stats"),
    )
    return b.as_markup()


def settings_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🔑 Сменить аккаунт", callback_data="change_account"),
    )
    b.row(
        InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_account"),
    )
    b.row(
        InlineKeyboardButton(text="📥 Импорт CSV", callback_data="import_csv"),
    )
    b.row(
        InlineKeyboardButton(text="📊 Дневной лимит глав", callback_data="set_daily_limit"),
    )
    b.row(
        InlineKeyboardButton(text="⬅ Назад", callback_data="back_main"),
    )
    return b.as_markup()


def account_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🔄 Детальный статус", callback_data="account_detail"),
    )
    b.row(
        InlineKeyboardButton(text="📊 Статистика за день", callback_data="today_stats"),
    )
    b.row(
        InlineKeyboardButton(text="🖥 Статус прокси", callback_data="proxy_stats"),
    )
    b.row(
        InlineKeyboardButton(text="⬅ Назад", callback_data="back_main"),
    )
    return b.as_markup()


def back_button(callback: str = "back_main") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅ Назад", callback_data=callback))
    return b.as_markup()


def confirm_mine() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Запустить", callback_data="mine_start"),
        InlineKeyboardButton(text="⬅ Назад", callback_data="back_main"),
    )
    return b.as_markup()
