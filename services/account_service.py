from typing import Optional

from database.repository import Repository
from core.task_registry import get_task


async def get_user_accounts(session_factory, tg_id: int) -> list:
    async with session_factory() as session:
        repo = Repository(session)
        return await repo.get_user_accounts(tg_id)


async def get_account(session_factory, account_id: int):
    async with session_factory() as session:
        repo = Repository(session)
        return await repo.get_account_by_id(account_id)


def format_account_text(acc) -> str:
    status_emoji = {"idle": "💤", "running": "▶", "paused": "⏸", "error": "❌"}
    se = status_emoji.get(acc.status, "💤")
    nick = acc.login.split("@")[0] if "@" in acc.login else acc.login
    return (
        f"{se} <b>{nick}</b>\n"
        f"Статус: {acc.status}\n"
        f"💎 {acc.diamonds} | 🃏 {acc.cards} | Ур. {acc.level}\n"
        f"Прокси: {acc.proxy or 'не назначен'}"
    )


def format_results_text(results: dict) -> str:
    done = sum(1 for r in results.values() if r.get("success"))
    total = len(results)
    lines = [f"▶ <b>Выполнено {done}/{total}</b>:"]
    for task, res in results.items():
        emoji = "✅" if res.get("success") else "❌"
        lines.append(f"  {emoji} {task}: {res.get('message', '')}")
    return "\n".join(lines)


async def toggle_task(session_factory, account_id: int, task_name: str) -> None:
    task = get_task(task_name)
    if not task:
        return
    async with session_factory() as session:
        repo = Repository(session)
        acc = await repo.get_account_by_id(account_id)
        if acc:
            current = getattr(acc, task.toggle_field, task.default_enabled)
            await repo.update_account(account_id, **{task.toggle_field: not current})
