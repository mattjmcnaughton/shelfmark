"""Sign in with Amp (OAuth 2.0 authorization code + PKCE, OpenID Connect).

Follows Amp's reference implementation (the ``deploying-boxes`` skill template's
``oauth.ts``): issuer ``https://auth.ampcode.com``, PKCE S256, ``resource`` set to
the Amp API, an RS256 ID token verified against the issuer's JWKS with nonce,
audience, ``azp``, and expiry checks, and server data kept in AES-GCM sealed
HttpOnly cookies.

Shelfmark only needs who the user is, never Amp API access, so the session cookie
holds the verified identity and no tokens; there is nothing to refresh.
"""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

import aiohttp
import jwt
import structlog
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from jwt import PyJWK

from shelfmark.auth import Identity

log = structlog.get_logger()

ISSUER = "https://auth.ampcode.com"
RESOURCE = "https://ampcode.com/api/v2"
SCOPES = "openid profile email"
SESSION_COOKIE = "shelfmark_session"
TRANSACTION_COOKIE = "shelfmark_oauth"
SESSION_MAX_AGE = 30 * 24 * 3600
TRANSACTION_MAX_AGE = 10 * 60


class OAuthError(Exception):
    pass


class AmpOAuthClient(Protocol):
    """The two network calls the flow makes; faked in tests."""

    async def exchange_code(self, form: dict[str, str]) -> dict[str, Any]: ...

    async def jwks(self) -> dict[str, Any]: ...


class HttpAmpOAuthClient:
    def __init__(self, issuer: str = ISSUER) -> None:
        self.issuer = issuer

    async def exchange_code(self, form: dict[str, str]) -> dict[str, Any]:
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http,
            http.post(
                f"{self.issuer}/oauth2/token",
                data=form,
                headers={"Accept": "application/json"},
            ) as response,
        ):
            payload = await response.json(content_type=None)
            if response.status != 200 or not isinstance(payload, dict):
                code = payload.get("error") if isinstance(payload, dict) else None
                raise OAuthError(
                    f"token exchange failed: HTTP {response.status} {code}"
                )
            return payload

    async def jwks(self) -> dict[str, Any]:
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http,
            http.get(f"{self.issuer}/oauth2/jwks") as response,
        ):
            if response.status != 200:
                raise OAuthError(f"JWKS fetch failed: HTTP {response.status}")
            return await response.json(content_type=None)


@dataclass(frozen=True)
class AmpAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    session_secret: str
    issuer: str = ISSUER


def configuration_problem(config: AmpAuthConfig) -> str | None:
    if not config.client_id:
        return "Missing AMP_OAUTH_CLIENT_ID"
    if not config.client_secret:
        return "Missing AMP_OAUTH_CLIENT_SECRET"
    if len(config.session_secret) < 32:
        return "APP_SESSION_SECRET must contain at least 32 characters"
    if not config.redirect_uri:
        return "Missing AMP_OAUTH_REDIRECT_URI (or AMP_DEPLOYMENT_URL)"
    parts = urlsplit(config.redirect_uri)
    loopback = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if (
        parts.path != "/auth/callback"
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
        or not (parts.scheme == "https" or (parts.scheme == "http" and loopback))
    ):
        return "The redirect URI must be an exact HTTPS /auth/callback URI"
    return None


class Sealer:
    """AES-256-GCM authenticated encryption for cookie payloads."""

    def __init__(self, secret: str) -> None:
        self._aead = AESGCM(hashlib.sha256(secret.encode()).digest())

    def seal(self, payload: dict[str, Any]) -> str:
        nonce = secrets.token_bytes(12)
        data = self._aead.encrypt(nonce, json.dumps(payload).encode(), b"shelfmark")
        return base64.urlsafe_b64encode(b"\x01" + nonce + data).decode().rstrip("=")

    def unseal(self, value: str | None) -> dict[str, Any] | None:
        if not value:
            return None
        try:
            raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
            if len(raw) < 30 or raw[0] != 1:
                return None
            payload = json.loads(self._aead.decrypt(raw[1:13], raw[13:], b"shelfmark"))
        except (ValueError, InvalidTag):
            return None
        return payload if isinstance(payload, dict) else None


def safe_return_to(value: str | None) -> str:
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
    ):
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return "/"
    return value


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class AmpAuth:
    name: str = "amp"
    can_sign_out: bool = True
    sign_in_url: str | None = "/auth/signin"

    def __init__(
        self,
        config: AmpAuthConfig,
        client: AmpOAuthClient | None = None,
        clock=time.time,
    ) -> None:
        self.config = config
        self.client = client or HttpAmpOAuthClient(config.issuer)
        self.clock = clock
        self._problem = configuration_problem(config)
        self._sealer = Sealer(config.session_secret) if not self._problem else None
        self.secure_cookies = not config.redirect_uri.startswith("http://")

    def configuration_error(self) -> str | None:
        return self._problem

    async def identify(self, request: Request) -> Identity | None:
        if self._sealer is None:
            return None
        payload = self._sealer.unseal(request.cookies.get(SESSION_COOKIE))
        if (
            not payload
            or payload.get("v") != 1
            or not isinstance(payload.get("exp"), int | float)
            or payload["exp"] <= self.clock()
            or not isinstance(payload.get("sub"), str)
            or not isinstance(payload.get("name"), str)
        ):
            return None
        email = payload.get("email")
        return Identity(
            "amp",
            payload["sub"],
            payload["name"],
            email if isinstance(email, str) else None,
        )

    # Flow

    def start(self, return_to: str) -> tuple[str, str]:
        """Return (authorization URL, sealed transaction cookie)."""
        assert self._sealer is not None
        verifier = _b64(secrets.token_bytes(32))
        transaction = {
            "state": _b64(secrets.token_bytes(32)),
            "nonce": _b64(secrets.token_bytes(32)),
            "verifier": verifier,
            "return_to": safe_return_to(return_to),
            "exp": self.clock() + TRANSACTION_MAX_AGE,
        }
        query = urlencode(
            {
                "client_id": self.config.client_id,
                "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
                "code_challenge_method": "S256",
                "nonce": transaction["nonce"],
                "redirect_uri": self.config.redirect_uri,
                "resource": RESOURCE,
                "response_type": "code",
                "scope": SCOPES,
                "state": transaction["state"],
            }
        )
        url = f"{self.config.issuer}/oauth2/authorize?{query}"
        return url, self._sealer.seal(transaction)

    def read_transaction(self, value: str | None) -> dict[str, Any] | None:
        assert self._sealer is not None
        t = self._sealer.unseal(value)
        if (
            not t
            or not all(
                isinstance(t.get(k), str) for k in ("state", "nonce", "verifier")
            )
            or not isinstance(t.get("exp"), int | float)
            or t["exp"] <= self.clock()
        ):
            return None
        return t

    async def finish(
        self, code: str, transaction: dict[str, Any]
    ) -> tuple[Identity, str]:
        """Exchange the code, verify the ID token, and return the session cookie."""
        assert self._sealer is not None
        tokens = await self.client.exchange_code(
            {
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": transaction["verifier"],
                "redirect_uri": self.config.redirect_uri,
                "resource": RESOURCE,
            }
        )
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise OAuthError("no ID token")
        claims = await self._verify(id_token, transaction["nonce"])
        name = next(
            (
                v
                for v in (
                    claims.get("name"),
                    " ".join(
                        p
                        for p in (claims.get("given_name"), claims.get("family_name"))
                        if p
                    ),
                    claims.get("email"),
                )
                if isinstance(v, str) and v.strip()
            ),
            "Amp user",
        )
        email = claims.get("email") if isinstance(claims.get("email"), str) else None
        identity = Identity("amp", claims["sub"], name[:200], email)
        cookie = self._sealer.seal(
            {
                "v": 1,
                "sub": identity.subject,
                "name": identity.name,
                "email": email,
                "exp": self.clock() + SESSION_MAX_AGE,
            }
        )
        return identity, cookie

    async def _verify(self, id_token: str, nonce: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as error:
            raise OAuthError("malformed ID token") from error
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise OAuthError("unexpected ID token header")
        keys = (await self.client.jwks()).get("keys") or []
        jwk = next(
            (
                k
                for k in keys
                if isinstance(k, dict)
                and k.get("kid") == header["kid"]
                and k.get("kty") == "RSA"
                and k.get("use", "sig") == "sig"
                and k.get("alg", "RS256") == "RS256"
            ),
            None,
        )
        if jwk is None:
            raise OAuthError("signing key unavailable")
        try:
            claims = jwt.decode(
                id_token,
                key=PyJWK(jwk, algorithm="RS256").key,
                algorithms=["RS256"],
                audience=self.config.client_id,
                issuer=self.config.issuer,
                leeway=60,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as error:
            raise OAuthError(f"invalid ID token: {type(error).__name__}") from error
        aud = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
        azp = claims.get("azp")
        if (len(aud) > 1 and azp != self.config.client_id) or (
            azp is not None and azp != self.config.client_id
        ):
            raise OAuthError("ID token azp mismatch")
        if claims.get("nonce") != nonce or not isinstance(claims.get("sub"), str):
            raise OAuthError("ID token nonce or subject invalid")
        return claims

    # Routes

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/auth", tags=["auth"])

        def cookie_kwargs(max_age: int) -> dict[str, Any]:
            return {
                "max_age": max_age,
                "httponly": True,
                "secure": self.secure_cookies,
                "samesite": "lax",
                "path": "/",
            }

        def unavailable() -> None:
            if self._problem:
                raise HTTPException(503, "Sign in with Amp is not configured.")

        @router.get("/signin")
        async def signin(returnTo: str = "/") -> RedirectResponse:  # noqa: N803
            unavailable()
            url, transaction = self.start(returnTo)
            response = RedirectResponse(url, status_code=302)
            response.set_cookie(
                TRANSACTION_COOKIE, transaction, **cookie_kwargs(TRANSACTION_MAX_AGE)
            )
            return response

        @router.get("/callback")
        async def callback(request: Request) -> RedirectResponse:
            unavailable()
            transaction = self.read_transaction(request.cookies.get(TRANSACTION_COOKIE))
            params = request.query_params
            target = "/"
            if not transaction or params.get("state") != transaction["state"]:
                target = "/?auth_error=invalid_state"
            elif "error" in params:
                target = "/?auth_error=access_denied"
            elif not params.get("code"):
                target = "/?auth_error=missing_code"
            else:
                try:
                    _identity, cookie = await self.finish(params["code"], transaction)
                except (OAuthError, aiohttp.ClientError, ValueError) as error:
                    log.warning("amp_sign_in_failed", reason=str(error))
                    target = "/?auth_error=oauth_failed"
                else:
                    response = RedirectResponse(
                        safe_return_to(transaction.get("return_to")), status_code=303
                    )
                    response.set_cookie(
                        SESSION_COOKIE, cookie, **cookie_kwargs(SESSION_MAX_AGE)
                    )
                    response.delete_cookie(TRANSACTION_COOKIE, path="/")
                    return response
            response = RedirectResponse(target, status_code=303)
            response.delete_cookie(TRANSACTION_COOKIE, path="/")
            return response

        @router.post("/signout")
        async def signout() -> RedirectResponse:
            response = RedirectResponse("/", status_code=303)
            response.delete_cookie(SESSION_COOKIE, path="/", secure=self.secure_cookies)
            return response

        return router
