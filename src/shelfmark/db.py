"""Database engine and session factory.

The app factory creates one ``Database`` and injects it; nothing here reads global
settings, so tests can point it at a temporary SQLite file.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        # Neon suspends idle compute and drops its connections; check before reuse.
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine.sync_engine, "connect", _sqlite_pragmas)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        async with self._sessions() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def sync_url(url: str) -> str:
    """The synchronous driver URL Alembic uses for the same database.

    psycopg serves both the app and Alembic, so ``postgresql+psycopg`` URLs pass
    through unchanged.
    """
    parsed = make_url(url)
    driver = {"sqlite+aiosqlite": "sqlite", "postgresql": "postgresql+psycopg"}
    return parsed.set(
        drivername=driver.get(parsed.drivername, parsed.drivername)
    ).render_as_string(hide_password=False)


def migrate(url: str) -> None:
    """Upgrade the database at ``url`` to the latest schema."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database:
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", sync_url(url).replace("%", "%%"))
    command.upgrade(config, "head")
