import itertools
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import NullPool, create_engine, text
from sqlalchemy.engine import make_url

from shelfmark.db import Database, migrate

# A Postgres server URL such as postgresql+psycopg://user:pw@localhost/postgres.
# When set, every test database is a fresh Postgres database instead of SQLite.
TEST_POSTGRES_URL = os.environ.get("SHELFMARK_TEST_DATABASE_URL")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def make_database_url(tmp_path: Path) -> Iterator[Callable[[], str]]:
    """A factory for URLs of new, empty databases, dropped after the test."""
    counter = itertools.count()
    created: list[str] = []

    def make() -> str:
        if not TEST_POSTGRES_URL:
            return f"sqlite+aiosqlite:///{tmp_path / f'test{next(counter)}.sqlite3'}"
        name = f"shelfmark_test_{uuid.uuid4().hex[:12]}"
        with _admin() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        created.append(name)
        return make_url(TEST_POSTGRES_URL).set(database=name).render_as_string(False)

    yield make
    if created:
        with _admin() as conn:
            for name in created:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _admin():
    assert TEST_POSTGRES_URL
    engine = create_engine(
        TEST_POSTGRES_URL, isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    return engine.connect()


@pytest.fixture
async def database(make_database_url) -> AsyncIterator[Database]:
    """A real, migrated database per test: SQLite by default, or Postgres."""
    url = make_database_url()
    migrate(url)
    db = Database(url)
    yield db
    await db.dispose()
