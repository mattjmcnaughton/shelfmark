"""Library API: everything under /api requires a signed-in, allowed user."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from shelfmark.auth import AuthProvider
from shelfmark.dtos.library import (
    Counts,
    FeedList,
    FeedOut,
    ItemDetail,
    ItemList,
    ItemPatch,
    ItemSummary,
    LibraryOut,
    LinkIn,
    UserOut,
)
from shelfmark.models import User
from shelfmark.repositories.library import LibraryRepository
from shelfmark.services.library import LibraryError, LibraryService


class ApiError(Exception):
    def __init__(self, status: int, detail: str, **extra: str) -> None:
        self.status, self.detail, self.extra = status, detail, extra


async def api_error_handler(_request: Request, error: Exception) -> Response:
    assert isinstance(error, ApiError | LibraryError)
    if isinstance(error, LibraryError):
        return JSONResponse({"detail": str(error)}, status_code=error.status)
    return JSONResponse(
        {"detail": error.detail, **error.extra}, status_code=error.status
    )


@dataclass
class Context:
    user: User
    service: LibraryService
    auth: AuthProvider


def check_same_site(request: Request) -> None:
    """Reject cross-site writes; cookies are SameSite=Lax but be explicit."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise ApiError(403, "Use a same-site request.")
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise ApiError(403, "Use a same-site request.")
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise ApiError(415, "Send JSON.")


async def context(request: Request) -> AsyncIterator[Context]:
    state = request.app.state
    auth: AuthProvider = state.auth
    problem = auth.configuration_error()
    if problem:
        # Fail closed: a misconfigured deployment serves no library data.
        raise ApiError(503, "Sign-in is not configured on this server.")
    identity = await auth.identify(request)
    if identity is None:
        raise ApiError(401, "Sign in to continue.", sign_in_url=auth.sign_in_url or "")
    allowed = state.settings.allowed_user_id_set
    if allowed and identity.subject not in allowed:
        raise ApiError(403, f"The account {identity.subject} is not allowed here.")
    check_same_site(request)
    async with state.database.session() as session:
        repo = LibraryRepository(session)
        user = await repo.get_or_create_user(
            identity.provider,
            identity.subject,
            identity.name,
            identity.email,
            state.clock(),
        )
        await repo.commit()
        yield Context(user, LibraryService(repo, state.fetcher, state.clock), auth)


Ctx = Annotated[Context, Depends(context)]
router = APIRouter(prefix="/api", tags=["library"])


@router.get("/library")
async def library(ctx: Ctx) -> LibraryOut:
    repo = ctx.service.repo
    return LibraryOut(
        user=UserOut(name=ctx.user.display_name, can_sign_out=ctx.auth.can_sign_out),
        feeds=[FeedOut.of(f) for f in await repo.feeds(ctx.user.id)],
        tags=await repo.tag_names(ctx.user.id),
        counts=Counts(**await repo.counts(ctx.user.id)),
    )


@router.get("/items", response_model_by_alias=True)
async def items(
    ctx: Ctx,
    view: Literal["inbox", "saved", "archive", "feed", "tag"] = "inbox",
    feed_id: Annotated[int | None, Query()] = None,
    tag: Annotated[str | None, Query(max_length=50)] = None,
) -> ItemList:
    found = await ctx.service.items(ctx.user.id, view, feed_id, tag)
    return ItemList(items=[ItemSummary.of(i) for i in found])


@router.get("/items/{item_id}", response_model_by_alias=True)
async def item(ctx: Ctx, item_id: int) -> ItemDetail:
    return ItemDetail.of(await ctx.service.item(ctx.user.id, item_id))


@router.post("/items", response_model_by_alias=True)
async def save_link(ctx: Ctx, body: LinkIn, response: Response) -> ItemDetail:
    result = await ctx.service.save_link(ctx.user.id, body.url, body.title)
    response.status_code = 201 if result.created else 200
    return ItemDetail.of(result.item)


@router.patch("/items/{item_id}", response_model_by_alias=True)
async def update_item(ctx: Ctx, item_id: int, body: ItemPatch) -> ItemDetail:
    updated = await ctx.service.update(
        ctx.user.id, item_id, saved=body.saved, archived=body.archived, tags=body.tags
    )
    return ItemDetail.of(updated)


@router.post("/feeds", status_code=201)
async def follow(ctx: Ctx, body: LinkIn) -> FeedOut:
    return FeedOut.of(await ctx.service.follow(ctx.user.id, body.url, body.title))


@router.post("/feeds/refresh")
async def refresh(ctx: Ctx) -> FeedList:
    return FeedList(
        feeds=[FeedOut.of(f) for f in await ctx.service.refresh_user(ctx.user.id)]
    )
