from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float, Text, ForeignKey, JSON, text,
)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, relationship

from config import config


class Base(DeclarativeBase):
    pass


class TelegramUser(Base):
    __tablename__ = "telegram_users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    accounts = relationship("Account", back_populates="owner", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<TelegramUser {self.telegram_id}>"


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    telegram_user_id = Column(Integer, ForeignKey("telegram_users.id"), nullable=False)
    login = Column(String(255), nullable=False)
    password = Column(String(255), nullable=False)
    proxy = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)

    # Status
    status = Column(String(50), default="idle")  # idle, running, paused, error
    error_message = Column(Text, nullable=True)

    # Stats
    diamonds = Column(Integer, default=0)
    cards = Column(Integer, default=0)
    level = Column(Integer, default=0)
    exp = Column(Integer, default=0)
    last_stats_update = Column(DateTime, nullable=True)

    # Task flags
    do_daily = Column(Boolean, default=True)
    do_mine = Column(Boolean, default=True)
    do_quiz = Column(Boolean, default=True)
    do_comments = Column(Boolean, default=True)
    do_ads = Column(Boolean, default=True)
    do_read_manga = Column(Boolean, default=True)
    do_collect_chat = Column(Boolean, default=True)
    do_event_free_card = Column(Boolean, default=True)
    do_event_open_pack = Column(Boolean, default=True)
    do_event_open_donat = Column(Boolean, default=True)

    # Progress tracking
    last_read_chapter = Column(Integer, default=0)

    # Mine strategy: null=accumulate, "exchange", "upgrade"
    mine_strategy = Column(String(20), nullable=True)

    owner = relationship("TelegramUser", back_populates="accounts")
    logs = relationship("AccountLog", back_populates="account", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Account {self.login}>"


class AccountLog(Base):
    __tablename__ = "account_logs"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    action = Column(String(100), nullable=False)
    message = Column(Text, nullable=True)
    success = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    account = relationship("Account", back_populates="logs")


class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True)
    proxy_string = Column(String(255), unique=True, nullable=False)
    proxy_type = Column(String(10), default="http")  # http, socks4, socks5
    is_alive = Column(Boolean, default=True)
    last_checked = Column(DateTime, nullable=True)
    in_use_by = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


async def init_db():
    engine = create_async_engine(config.DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add new columns for existing SQLite DBs
        for col, col_type in [
            ("do_event_free_card", "BOOLEAN DEFAULT 1"),
            ("do_event_open_pack", "BOOLEAN DEFAULT 1"),
            ("do_event_open_donat", "BOOLEAN DEFAULT 1"),
            ("last_read_chapter", "INTEGER DEFAULT 0"),
        ]:
            try:
                await conn.execute(text(f"ALTER TABLE accounts ADD COLUMN {col} {col_type}"))
            except Exception:
                pass  # column already exists
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return session_factory
