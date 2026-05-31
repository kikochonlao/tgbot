import json
import asyncpg
from typing import Any
from datetime import datetime, timezone


class Database:
    def __init__(self, dsn: str = "") -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if not self._dsn:
            self._dsn = "postgresql://postgres:postgres@localhost:5432/tgbot"
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        await self._migrate()

    async def _migrate(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id SERIAL PRIMARY KEY,
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
                    created_at TEXT DEFAULT (NOW()),
                    updated_at TEXT DEFAULT (NOW())
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS proxies (
                    id SERIAL PRIMARY KEY,
                    url TEXT NOT NULL UNIQUE,
                    type TEXT DEFAULT 'http',
                    is_alive INTEGER DEFAULT 0,
                    latency_ms INTEGER DEFAULT 0,
                    last_checked TEXT,
                    last_ok TEXT,
                    fail_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (NOW())
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS manga_titles (
                    id SERIAL PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    title TEXT,
                    chapters_json TEXT,
                    created_at TEXT DEFAULT (NOW())
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS read_history (
                    id SERIAL PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    manga_id INTEGER,
                    chapter TEXT,
                    read_at TEXT DEFAULT (NOW()),
                    FOREIGN KEY (account_id) REFERENCES accounts(id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS comment_history (
                    id SERIAL PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    commentable_id INTEGER,
                    text TEXT,
                    posted_at TEXT DEFAULT (NOW()),
                    FOREIGN KEY (account_id) REFERENCES accounts(id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_config (
                    user_id INTEGER PRIMARY KEY,
                    daily_limit INTEGER DEFAULT 50,
                    comment_interval INTEGER DEFAULT 5,
                    min_delay REAL DEFAULT 4.0,
                    max_delay REAL DEFAULT 12.0
                )
            """)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    # ── Accounts ──

    async def add_account(self, email: str, password: str) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO accounts (email, password) VALUES ($1, $2) "
                "ON CONFLICT (email) DO NOTHING RETURNING id",
                email, password,
            )
            return row["id"] if row else 0

    async def get_account(self, account_id: int) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM accounts WHERE id = $1", account_id)
            return dict(row) if row else None

    async def get_account_by_email(self, email: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM accounts WHERE email = $1", email)
            return dict(row) if row else None

    async def get_all_accounts(self, active_only: bool = False) -> list[dict[str, Any]]:
        q = "SELECT * FROM accounts"
        args = []
        if active_only:
            q += " WHERE is_active = 1"
        q += " ORDER BY id"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(q, *args)
            return [dict(r) for r in rows]

    async def update_account(self, account_id: int, **kwargs) -> None:
        if not kwargs:
            return
        sets = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(kwargs))
        vals = list(kwargs.values()) + [account_id]
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE accounts SET {sets}, updated_at = NOW() WHERE id = ${len(kwargs)+1}",
                *vals,
            )

    async def set_account_status(self, account_id: int, status: str) -> None:
        await self.update_account(account_id, status=status)

    async def increment_error(self, account_id: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE accounts SET error_count = error_count + 1, updated_at = NOW() WHERE id = $1",
                account_id,
            )

    async def reset_daily_counters(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE accounts SET daily_read = 0, daily_date = $1 "
                "WHERE daily_date != $1 OR daily_date IS NULL",
                today,
            )

    # ── Proxies ──

    async def add_proxy(self, url: str, proxy_type: str = "http") -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO proxies (url, type) VALUES ($1, $2) "
                "ON CONFLICT (url) DO NOTHING RETURNING id",
                url, proxy_type,
            )
            return row["id"] if row else 0

    async def get_alive_proxies(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM proxies WHERE is_alive = 1 "
                "ORDER BY latency_ms ASC, RANDOM() LIMIT $1",
                limit,
            )
            return [dict(r) for r in rows]

    async def get_dead_proxies(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM proxies WHERE is_alive = 0 AND fail_count < 5"
            )
            return [dict(r) for r in rows]

    async def update_proxy_status(self, proxy_id: int, is_alive: bool, latency_ms: int = 0) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE proxies SET is_alive = $1, latency_ms = $2, last_checked = NOW(), "
                "last_ok = CASE WHEN $3 THEN NOW() ELSE last_ok END, "
                "fail_count = CASE WHEN $4 THEN 0 ELSE fail_count + 1 END WHERE id = $5",
                int(is_alive), latency_ms, is_alive, is_alive, proxy_id,
            )

    async def proxy_pool_stats(self) -> dict[str, int]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT is_alive, COUNT(*)::int as cnt FROM proxies GROUP BY is_alive"
            )
            alive = sum(r["cnt"] for r in rows if r["is_alive"] == 1)
            dead = sum(r["cnt"] for r in rows if r["is_alive"] == 0)
            return {"alive": alive, "dead": dead, "total": alive + dead}

    async def clean_dead_proxies(self) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM proxies WHERE is_alive = 0 AND fail_count >= 5"
            )
            parts = result.split()
            return int(parts[-1]) if parts else 0

    # ── Manga titles ──

    async def add_manga_title(self, slug: str, title: str, chapters: list[dict]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO manga_titles (slug, title, chapters_json) VALUES ($1, $2, $3) "
                "ON CONFLICT (slug) DO UPDATE SET title = $2, chapters_json = $3",
                slug, title, json.dumps(chapters),
            )

    async def get_manga_title(self, slug: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM manga_titles WHERE slug = $1", slug)
            if row:
                d = dict(row)
                d["chapters"] = json.loads(d.get("chapters_json", "[]"))
                return d
            return None

    # ── Read history ──

    async def add_read_history(self, account_id: int, manga_id: int, chapter: str) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO read_history (account_id, manga_id, chapter) VALUES ($1, $2, $3)",
                account_id, manga_id, chapter,
            )
            await conn.execute(
                "UPDATE accounts SET total_read = total_read + 1, daily_read = daily_read + 1, "
                "daily_date = $1 WHERE id = $2",
                today, account_id,
            )

    async def get_daily_read_count(self, account_id: int) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*)::int as cnt FROM read_history "
                "WHERE account_id = $1 AND date(read_at) = $2",
                account_id, today,
            )
            return row["cnt"] if row else 0

    async def get_today_stats(self) -> dict[str, int]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with self._pool.acquire() as conn:
            reads = await conn.fetchval(
                "SELECT COUNT(*)::int FROM read_history WHERE date(read_at) = $1", today
            )
            comments = await conn.fetchval(
                "SELECT COUNT(*)::int FROM comment_history WHERE date(posted_at) = $1", today
            )
            active = await conn.fetchval(
                "SELECT COUNT(*)::int FROM accounts WHERE status IN ('working','active')"
            )
            total = await conn.fetchval("SELECT COUNT(*)::int FROM accounts")
            return {"reads": reads, "comments": comments, "active": active, "total": total}

    # ── Comment history ──

    async def add_comment_history(self, account_id: int, commentable_id: int, text: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO comment_history (account_id, commentable_id, text) VALUES ($1, $2, $3)",
                account_id, commentable_id, text,
            )
            await conn.execute(
                "UPDATE accounts SET total_comments = total_comments + 1 WHERE id = $1",
                account_id,
            )

    # ── User config ──

    async def get_user_config(self, user_id: int) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM user_config WHERE user_id = $1", user_id)
            if row:
                return dict(row)
            await conn.execute(
                "INSERT INTO user_config (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id,
            )
            return {"user_id": user_id, "daily_limit": 50, "comment_interval": 5,
                    "min_delay": 4.0, "max_delay": 12.0}

    async def update_user_config(self, user_id: int, **kwargs) -> None:
        await self.get_user_config(user_id)
        if not kwargs:
            return
        sets = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(kwargs))
        vals = list(kwargs.values()) + [user_id]
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE user_config SET {sets} WHERE user_id = ${len(kwargs)+1}",
                *vals,
            )

    async def get_accounts_count(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*)::int FROM accounts")

    async def get_accounts_with_status(self, status: str) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM accounts WHERE status = $1 ORDER BY id", status,
            )
            return [dict(r) for r in rows]
