from aiogram.fsm.state import State, StatesGroup


class AddManga(StatesGroup):
    waiting_for_slug = State()


class AddComment(StatesGroup):
    waiting_for_chapter = State()
    waiting_for_text = State()


class AutoRead(StatesGroup):
    waiting_for_slug = State()
    waiting_for_count = State()


class Settings(StatesGroup):
    waiting_for_value = State()


class AddAccount(StatesGroup):
    waiting_for_credentials = State()


class ImportCSV(StatesGroup):
    waiting_for_file = State()
