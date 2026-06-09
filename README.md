mangabuff_bot/
├── bot/                    # Telegram bot
│   ├── __init__.py
│   ├── main.py             # Entry point
│   ├── keyboards.py        # Inline keyboards
│   └── handlers/
│       ├── __init__.py
│       ├── start.py        # /start command
│       ├── accounts.py     # Account management
│       └── stats.py        # Statistics + proxy commands
├── automation/             # MangaBuff browser automation
│   ├── __init__.py
│   └── client.py           # Playwright client
├── core/                   # Core logic
│   ├── __init__.py
│   ├── worker.py           # Per-account worker
│   ├── scheduler.py        # Task scheduling
│   ├── proxy_manager.py    # Proxy pool management
│   └── proxy_scraper.py    # Free proxy scraping
├── database/               # Database layer
│   ├── __init__.py
│   ├── models.py           # SQLAlchemy models
│   └── repository.py       # CRUD operations
├── config.py               # Configuration
└── requirements.txt
