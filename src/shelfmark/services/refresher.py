"""Background feed refresh for every user."""

import asyncio

import structlog

from shelfmark.clients.fetcher import Fetcher
from shelfmark.db import Database
from shelfmark.repositories.library import LibraryRepository
from shelfmark.services.library import Clock, LibraryService

log = structlog.get_logger()


async def refresh_all(database: Database, fetcher: Fetcher, clock: Clock) -> None:
    async with database.session() as session:
        repo = LibraryRepository(session)
        service = LibraryService(repo, fetcher, clock)
        for user_id in await repo.all_user_ids():
            await service.refresh_user(user_id)


async def run_periodically(
    database: Database, fetcher: Fetcher, clock: Clock, minutes: int
) -> None:
    while True:
        await asyncio.sleep(minutes * 60)
        try:
            await refresh_all(database, fetcher, clock)
        except Exception:  # keep the loop alive; one bad pass must not stop refresh
            log.exception("feed_refresh_failed")
