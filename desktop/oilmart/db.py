from __future__ import annotations

import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .migrations import migrate


def default_url() -> str:
    root = Path.home() / ".oilmart"
    root.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(root / 'oilmart.db').as_posix()}"


def make_engine(url: str | None = None):
    database_url = url or os.getenv("OILMART_DB_URL", default_url())
    engine = create_engine(database_url, future=True, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _sqlite_settings(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    return engine


def initialize(engine) -> sessionmaker[Session]:
    migrate(engine)
    return sessionmaker(engine, expire_on_commit=False)
