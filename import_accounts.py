import asyncio
import csv
import os

import asyncpg


async def main() -> None:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("Ошибка: укажи DATABASE_URL (например: DATABASE_URL=... python import_accounts.py)")
        return

    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=1)
    if not pool:
        return

    async with pool.acquire() as conn:
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

    csv_path = os.path.join(os.path.dirname(__file__), "proxies", "accounts.csv")
    if not os.path.exists(csv_path):
        print(f"Файл не найден: {csv_path}")
        await pool.close()
        return

    added = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            with open(csv_path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    email = row.get("email", "").strip()
                    password = row.get("password", "").strip()
                    if email and password:
                        result = await conn.fetchrow(
                            "INSERT INTO accounts (email, password) VALUES ($1, $2) "
                            "ON CONFLICT (email) DO NOTHING RETURNING id",
                            email, password,
                        )
                        if result:
                            added += 1

    await pool.close()
    print(f"Импортировано {added} аккаунтов")


if __name__ == "__main__":
    asyncio.run(main())
