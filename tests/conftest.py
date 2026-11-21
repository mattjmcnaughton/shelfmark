from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from shelfmark.db import Database, migrate


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """A real, migrated SQLite database file per test."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}"
    migrate(url)
    db = Database(url)
    yield db
    await db.dispose()
