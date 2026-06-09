from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TaskDef:
    name: str
    label: str
    toggle_field: str
    worker_method: str
    category: str  # "daily", "event", "periodic"
    log_action: Optional[str] = None  # defaults to name
    periodic_interval: Optional[int] = None
    default_enabled: bool = True
    requires_chapters: Optional[int] = None

    def get_log_action(self) -> str:
        return self.log_action or self.name


TASKS: list[TaskDef] = [
    TaskDef("daily", "Дейлики", "do_daily", "run_daily", "daily"),
    TaskDef("mine", "Шахта", "do_mine", "run_mine", "daily"),
    TaskDef("quiz", "Квиз", "do_quiz", "run_quiz", "daily"),
    TaskDef("comments", "Аукцион: коммент.", "do_comments", "run_comments", "daily", log_action="auction_comments"),
    TaskDef("read_manga", "Чтение манги", "do_read_manga", "run_read_manga", "daily", requires_chapters=75),
    TaskDef("ads", "Реклама", "do_ads", "run_ads", "daily", log_action="ad", periodic_interval=900),
    TaskDef("collect_chat", "Чат алмаз", "do_collect_chat", "run_collect_chat", "daily", periodic_interval=900),
    TaskDef("event_free_card", "Ивент: беспл. карта", "do_event_free_card", "run_event_free_card", "event"),
]


def get_task(name: str) -> Optional[TaskDef]:
    for t in TASKS:
        if t.name == name:
            return t
    return None


def get_tasks_by_category(category: str) -> list[TaskDef]:
    return [t for t in TASKS if t.category == category]


def get_settings_tasks() -> list[TaskDef]:
    return [t for t in TASKS if getattr(t, "toggle_field", None)]


def get_toggle_fields() -> list[str]:
    return [t.toggle_field for t in TASKS if t.toggle_field]


def get_worker_method(name: str) -> Optional[str]:
    t = get_task(name)
    return t.worker_method if t else None


def get_periodic_tasks() -> list[TaskDef]:
    return [t for t in TASKS if t.periodic_interval is not None]
