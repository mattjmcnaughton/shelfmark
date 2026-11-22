"""Identity boundary.

The rest of the app sees only ``Identity`` and the ``AuthProvider`` protocol. A
provider says who made a request (or nobody), optionally contributes its own routes
(sign-in, callback, sign-out), and reports whether it is correctly configured. The
app factory picks one provider; swapping Auth0 for another IdP or a
reverse-proxy header means writing another provider, not touching the library.
"""

from dataclasses import dataclass
from typing import Protocol

from fastapi import APIRouter, Request


@dataclass(frozen=True)
class Identity:
    provider: str
    subject: str
    name: str
    email: str | None = None


class AuthProvider(Protocol):
    name: str
    can_sign_out: bool
    sign_in_url: str | None
    # Origin the browser is redirected to after a form post (sign-out), for CSP.
    external_origin: str | None

    def configuration_error(self) -> str | None:
        """Why the provider cannot authenticate anyone, or None when ready."""
        ...

    async def identify(self, request: Request) -> Identity | None: ...

    def router(self) -> APIRouter | None: ...


class LocalAuth:
    """One fixed local user, for development and tests only."""

    name: str = "local"
    can_sign_out: bool = False
    sign_in_url: str | None = None
    external_origin: str | None = None

    def __init__(self, identity: Identity | None = None) -> None:
        self.identity = identity or Identity("local", "local", "Local reader")

    def configuration_error(self) -> str | None:
        return None

    async def identify(self, request: Request) -> Identity | None:
        return self.identity

    def router(self) -> APIRouter | None:
        return None


__all__ = ["AuthProvider", "Identity", "LocalAuth"]
