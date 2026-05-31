import json
import os
from typing import Any
from datetime import datetime, timezone

import aiosqlite
import asyncpg


DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "bot.db")


class Database:
    def __init__(self, dsn: str = "") -> None:
        self._dsn = dsn
        self._pg_pool: asyncpg.Pool | None = None
        self._sqlite: aiosqlite.Connection | None = None
        self._is_pg = bool(dsn and dsn.startswith("postgresql"))

    async def connect(self) -> None:
        if self._is_pg:
            self._pg_pool = await asyncpg.create_pool(
                dsn=self._dsn, min_size=2, max_size=10, command_timeout=30,
            )
        else:
            os.makedirs(DB_DIR, exist_ok=True)
            self._sqlite = await aiosqlite.connect(DB_PATH)
            self._sqlite.row_factory = aiosqlite.Row
        await self._migrate()

    async def _migrate(self) -> None:
        sql = """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY {auto},
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                proxy_id INTEGER,
                is_active INTEGER DEFAULT 1,
                status TEXT DEFAULT 'idle',
                last_error TEXT,
                error_count INTEGER DEFAULT 0,
                total_read INTEGER DEFAULT 0,
                total_comments INTEGER DEFAULT 0,
                daily_read INTEGER DEFAULT 0,
                daily_date TEXT,
                created_at TEXT DEFAULT ({now}),
                updated_at TEXT DEFAULT ({now})
            );
            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY {auto},
                url TEXT NOT NULL UNIQUE,
                type TEXT DEFAULT 'http',
                is_alive INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                last_checked TEXT,
                last_ok TEXT,
                fail_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT ({now})
            );
            CREATE TABLE IF NOT EXISTS manga_titles (
                id INTEGER PRIMARY KEY {auto},
                slug TEXT NOT NULL UNIQUE,
                title TEXT,
                chapters_json TEXT,
                created_at TEXT DEFAULT ({now})
            );
            CREATE TABLE IF NOT EXISTS read_history (
                id INTEGER PRIMARY KEY {auto},
                account_id INTEGER NOT NULL,
                manga_id INTEGER,
                chapter TEXT,
                read_at TEXT DEFAULT ({now}),
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            );
            CREATE TABLE IF NOT EXISTS comment_history (
                id INTEGER PRIMARY KEY {auto},
                account_id INTEGER NOT NULL,
                commentable_id INTEGER,
                text TEXT,
                posted_at TEXT DEFAULT ({now}),
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            );
            CREATE TABLE IF NOT EXISTS user_config (
                user_id INTEGER PRIMARY KEY,
                daily_limit INTEGER DEFAULT 50,
                comment_interval INTEGER DEFAULT 5,
                min_delay REAL DEFAULT 4.0,
                max_delay REAL DEFAULT 12.0
            );
        """.format(
            auto="AUTOINCREMENT" if not self._is_pg else "GENERATED ALWAYS AS IDENTITY",
            now="datetime('now')" if not self._is_pg else "NOW()",
        )
        if self._is_pg:
            async with self._pg_pool.acquire() as c:
                await c.execute(sql)
        else:
            await self._sqlite.executescript(sql)

    async def close(self) -> None:
        if self._pg_pool:
            await self._pg_pool.close()
        elif self._sqlite:
            await self._sqlite.close()

    # ── helpers ──

    def _p(self, i: int) -> str:
        return f"${i}" if self._is_pg else "?"

    def _now(self) -> str:
        return "NOW()" if self._is_pg else "datetime('now')"

    def _return_id(self) -> str:
        return " RETURNING id" if self._is_pg else ""

    async def _execute(self, sql: str, *args) -> Any:
        if self._is_pg:
            async with self._pg_pool.acquire() as c:
                return await c.execute(sql, *args)
        return await self._sqlite.execute(sql, args)

    async def _fetch(self, sql: str, *args) -> list[dict[str, Any]]:
        if self._is_pg:
            async with self._pg_pool.acquire() as c:
                rows = await c.fetch(sql, *args)
                return [dict(r) for r in rows]
        cur = await self._sqlite.execute(sql, args)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def _fetchrow(self, sql: str, *args) -> dict[str, Any] | None:
        if self._is_pg:
            async with self._pg_pool.acquire() as c:
                row = await c.fetchrow(sql, *args)
                return dict(row) if row else None
        cur = await self._sqlite.execute(sql, args)
        row = await cur.fetchone()
        return dict(row) if row else None

    async def _fetchval(self, sql: str, *args) -> Any:
        if self._is_pg:
            async with self._pg_pool.acquire() as c:
                return await c.fetchval(sql, *args)
        cur = await self._sqlite.execute(sql, args)
        row = await cur.fetchone()
        return row[0] if row else None

    async def _commit(self) -> None:
        if not self._is_pg and self._sqlite:
            await self._sqlite.commit()

    # ── Accounts ──

    async def add_account(self, email: str, password: str) -> int:
        sql = f"INSERT OR IGNORE INTO accounts (email, password) VALUES ({self._p(1)}, {self._p(2)}){self._return_id()}"
        if self._is_pg:
            row = await self._fetchrow(sql, email, password)
            return row["id"] if row else 0
        await self._execute(sql, email, password)
        await self._commit()
        return self._sqlite.total_changes if self._sqlite else 0

    async def get_account(self, account_id: int) -> dict[str, Any] | None:
        return await self._fetchrow(f"SELECT * FROM accounts WHERE id = {self._p(1)}", account_id)

    async def get_account_by_email(self, email: str) -> dict[str, Any] | None:
        return await self._fetchrow(f"SELECT * FROM accounts WHERE email = {self._p(1)}", email)

    async def get_all_accounts(self, active_only: bool = False) -> list[dict[str, Any]]:
        q = "SELECT * FROM accounts"
        if active_only:
            q += " WHERE is_active = 1"
        q += " ORDER BY id"
        return await self._fetch(q)

    async def get_accounts_count(self) -> int:
        return await self._fetchval("SELECT COUNT(*) FROM accounts") or 0

    async def update_account(self, account_id: int, **kwargs) -> None:
        if not kwargs:
            return
        sets = ", ".join(f"{k} = {self._p(i+1)}" for i, k in enumerate(kwargs))
        vals = list(kwargs.values()) + [account_id]
        sql = f"UPDATE accounts SET {sets}, updated_at = {self._now()} WHERE id = {self._p(len(kwargs)+1)}"
        await self._execute(sql, *vals)
        await self._commit()

    async def set_account_status(self, account_id: int, status: str) -> None:
        await self.update_account(account_id, status=status)

    async def increment_error(self, account_id: int) -> None:
        sql = f"UPDATE accounts SET error_count = error_count + 1, updated_at = {self._now()} WHERE id = {self._p(1)}"
        await self._execute(sql, account_id)
        await self._commit()

    async def reset_daily_counters(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sql = f"UPDATE accounts SET daily_read = 0, daily_date = {self._p(1)} WHERE daily_date != {self._p(1)} OR daily_date IS NULL"
        await self._execute(sql, today, today)
        await self._commit()

    # ── Proxies ──

    async def add_proxy(self, url: str, proxy_type: str = "http") -> int:
        sql = f"INSERT OR IGNORE INTO proxies (url, type) VALUES ({self._p(1)}, {self._p(2)}){self._return_id()}"
        if self._is_pg:
            row = await self._fetchrow(sql, url, proxy_type)
            return row["id"] if row else 0
        await self._execute(sql, url, proxy_type)
        await self._commit()
        return self._sqlite.total_changes if self._sqlite else 0

    async def get_alive_proxies(self, limit: int = 20) -> list[dict[str, Any]]:
        order = "RANDOM()" if not self._is_pg else "RANDOM()"
        return await self._fetch(
            f"SELECT * FROM proxies WHERE is_alive = 1 ORDER BY latency_ms ASC, {order} LIMIT {self._p(1)}",
            limit,
        )

    async def get_dead_proxies(self) -> list[dict[str, Any]]:
        return await self._fetch("SELECT * FROM proxies WHERE is_alive = 0 AND fail_count < 5")

    async def update_proxy_status(self, proxy_id: int, is_alive: bool, latency_ms: int = 0) -> None:
        sql = (
            f"UPDATE proxies SET is_alive = {self._p(1)}, latency_ms = {self._p(2)}, last_checked = {self._now()}, "
            f"last_ok = CASE WHEN {self._p(3)} THEN {self._now()} ELSE last_ok END, "
            f"fail_count = CASE WHEN {self._p(4)} THEN 0 ELSE fail_count + 1 END WHERE id = {self._p(5)}"
        )
        await self._execute(sql, int(is_alive), latency_ms, is_alive, is_alive, proxy_id)
        await self._commit()

    async def proxy_pool_stats(self) -> dict[str, int]:
        rows = await self._fetch("SELECT is_alive, COUNT(*) as cnt FROM proxies GROUP BY is_alive")
        alive = sum(r["cnt"] for r in rows if r["is_alive"] == 1)
        dead = sum(r["cnt"] for r in rows if r["is_alive"] == 0)
        return {"alive": alive, "dead": dead, "total": alive + dead}

    async def clean_dead_proxies(self) -> int:
        before = await self.get_accounts_count()
        await self._execute("DELETE FROM proxies WHERE is_alive = 0 AND fail_count >= 5")
        await self._commit()
        after = await self.get_accounts_count()
        return before - after

    # ── Manga titles ──

    async def add_manga_title(self, slug: str, title: str, chapters: list[dict]) -> None:
        conflict = "ON CONFLICT (slug) DO UPDATE SET title = $2, chapters_json = $3" if self._is_pg else "OR REPLACE"
        sql = f"INSERT {conflict} INTO manga_titles (slug, title, chapters_json) VALUES ({self._p(1)}, {self._p(2)}, {self._p(3)})"
        await self._execute(sql, slug, title, json.dumps(chapters))
        await self._commit()

    async def get_manga_title(self, slug: str) -> dict[str, Any] | None:
        row = await self._fetchrow(f"SELECT * FROM manga_titles WHERE slug = {self._p(1)}", slug)
        if row:
            row["chapters"] = json.loads(row.get("chapters_json", "[]"))
            return row
        return None

    # ── Read history ──

    async def add_read_history(self, account_id: int, manga_id: int, chapter: str) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await self._execute(
            "INSERT INTO read_history (account_id, manga_id, chapter) VALUES (?, ?, ?)" if not self._is_pg
            else "INSERT INTO read_history (account_id, manga_id, chapter) VALUES ($1, $2, $3)",
            account_id, manga_id, chapter,
        )
        sql = f"UPDATE accounts SET total_read = total_read + 1, daily_read = daily_read + 1, daily_date = {self._p(1)} WHERE id = {self._p(2)}"
        await self._execute(sql, today, account_id)
        await self._commit()

    async def get_daily_read_count(self, account_id: int) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return await self._fetchval(
            "SELECT COUNT(*) FROM read_history WHERE account_id = ? AND date(read_at) = ?" if not self._is_pg
            else "SELECT COUNT(*)::int FROM read_history WHERE account_id = $1 AND date(read_at) = $2",
            account_id, today,
        ) or 0

    async def get_today_stats(self) -> dict[str, int]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._is_pg:
            reads = await self._fetchval("SELECT COUNT(*)::int FROM read_history WHERE date(read_at) = $1", today) or 0
            comments = await self._fetchval("SELECT COUNT(*)::int FROM comment_history WHERE date(posted_at) = $1", today) or 0
        else:
            reads = await self._fetchval("SELECT COUNT(*) FROM read_history WHERE date(read_at) = ?", today) or 0
            comments = await self._fetchval("SELECT COUNT(*) FROM comment_history WHERE date(posted_at) = ?", today) or 0
        active = await self._fetchval("SELECT COUNT(*) FROM accounts WHERE status IN ('working','active')") or 0
        total = await self._fetchval("SELECT COUNT(*) FROM accounts") or 0
        return {"reads": reads, "comments": comments, "active": active, "total": total}

    # ── Comment history ──

    async def add_comment_history(self, account_id: int, commentable_id: int, text: str) -> None:
        await self._execute(
            "INSERT INTO comment_history (account_id, commentable_id, text) VALUES (?, ?, ?)" if not self._is_pg
            else "INSERT INTO comment_history (account_id, commentable_id, text) VALUES ($1, $2, $3)",
            account_id, commentable_id, text,
        )
        await self._execute(f"UPDATE accounts SET total_comments = total_comments + 1 WHERE id = {self._p(1)}", account_id)
        await self._commit()

    # ── User config ──

    async def get_user_config(self, user_id: int) -> dict[str, Any]:
        row = await self._fetchrow(f"SELECT * FROM user_config WHERE user_id = {self._p(1)}", user_id)
        if row:
            return dict(row)
        await self._execute(
            f"INSERT INTO user_config (user_id) VALUES ({self._p(1)}) ON CONFLICT DO NOTHING" if self._is_pg
            else "INSERT OR IGNORE INTO user_config (user_id) VALUES (?)",
            user_id,
        )
        await self._commit()
        return {"user_id": user_id, "daily_limit": 50, "comment_interval": 5,
                "min_delay": 4.0, "max_delay": 12.0}

    async def update_user_config(self, user_id: int, **kwargs) -> None:
        await self.get_user_config(user_id)
        if not kwargs:
            return
        sets = ", ".join(f"{k} = {self._p(i+1)}" for i, k in enumerate(kwargs))
        vals = list(kwargs.values()) + [user_id]
        await self._execute(f"UPDATE user_config SET {sets} WHERE user_id = {self._p(len(kwargs)+1)}", *vals)
        await self._commit()

    async def get_accounts_with_status(self, status: str) -> list[dict[str, Any]]:
        return await self._fetch(f"SELECT * FROM accounts WHERE status = {self._p(1)} ORDER BY id", status)
