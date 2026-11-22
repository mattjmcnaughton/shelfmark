"""Sign in with Auth0 through the real routes, with a fake Auth0 tenant."""

import time
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from shelfmark.app import create_app, select_auth
from shelfmark.auth.auth0 import Auth0Auth, Auth0Config
from shelfmark.config import Settings
from shelfmark.db import Database
from tests.fakes import FakeFetcher

pytestmark = pytest.mark.anyio
DOMAIN = "tenant.us.auth0.com"
ISSUER = f"https://{DOMAIN}/"
CLIENT_ID = "client-123"
REDIRECT = "https://shelf.test/auth/callback"


class FakeAuth0:
    """Issues RS256 ID tokens for the nonce it is told about."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.claims: dict = {}
        self.forms: list[dict] = []

    def token(self, **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "google-oauth2|1234",
            "name": "Matt",
            "email": "m@example.com",
            "exp": now + 300,
            "iat": now,
            **self.claims,
            **overrides,
        }
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "k1"})

    async def exchange_code(self, form):
        self.forms.append(form)
        return {"access_token": "at", "token_type": "Bearer", "id_token": self.token()}

    async def jwks(self):
        jwk = RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}


def app_with(url: str, auth, allowed: str = ""):
    return create_app(
        Settings(_env_file=None, allowed_user_ids=allowed),
        database=Database(url),
        fetcher=FakeFetcher(),
        auth=auth,
        background_refresh=False,
        serve_frontend=False,
    )


def auth0(fake: FakeAuth0) -> Auth0Auth:
    config = Auth0Config(DOMAIN, CLIENT_ID, "secret", REDIRECT, "s" * 40)
    return Auth0Auth(config, client=fake)


@asynccontextmanager
async def client(app):
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://shelf.test"
        ) as c,
    ):
        yield c


async def sign_in(c: httpx.AsyncClient, fake: FakeAuth0) -> httpx.Response:
    start = await c.get("/auth/signin", params={"returnTo": "/?view=saved"})
    assert start.status_code == 302
    location = urlsplit(start.headers["location"])
    params = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert (
        f"{location.scheme}://{location.netloc}{location.path}"
        == f"https://{DOMAIN}/authorize"
    )
    assert params["client_id"] == CLIENT_ID and params["redirect_uri"] == REDIRECT
    assert params["code_challenge_method"] == "S256"
    assert "resource" not in params and params["scope"] == "openid profile email"
    fake.claims["nonce"] = params["nonce"]
    return await c.get(
        "/auth/callback", params={"code": "abc", "state": params["state"]}
    )


async def test_sign_in_flow_creates_session(make_database_url):
    fake = FakeAuth0()
    async with client(app_with(make_database_url(), auth0(fake))) as c:
        r = await c.get("/api/library")
        assert r.status_code == 401 and r.json()["sign_in_url"] == "/auth/signin"
        done = await sign_in(c, fake)
        assert done.status_code == 303 and done.headers["location"] == "/?view=saved"
        assert (
            fake.forms[0]["code_verifier"] and fake.forms[0]["redirect_uri"] == REDIRECT
        )
        assert "client_secret" not in fake.forms[0]  # sent as HTTP Basic instead
        lib = await c.get("/api/library")
        assert lib.status_code == 200
        assert lib.json()["user"] == {"name": "Matt", "can_sign_out": True}
        assert (
            f"form-action 'self' https://{DOMAIN}"
            in lib.headers["content-security-policy"]
        )
        out = await c.post("/auth/signout")
        assert out.status_code == 303
        assert out.headers["location"] == (
            f"https://{DOMAIN}/v2/logout?client_id={CLIENT_ID}"
            "&returnTo=https%3A%2F%2Fshelf.test%2F"
        )
        assert (await c.get("/api/library")).status_code == 401


async def test_rejects_forged_state_and_bad_tokens(make_database_url):
    fake = FakeAuth0()
    async with client(app_with(make_database_url(), auth0(fake))) as c:
        r = await c.get("/auth/callback", params={"code": "abc", "state": "forged"})
        assert r.headers["location"] == "/?auth_error=invalid_state"

        for bad in ({"aud": "someone-else"}, {"iss": f"https://{DOMAIN}"}):
            fake.claims = dict(bad)
            r = await sign_in(c, fake)
            assert r.headers["location"] == "/?auth_error=oauth_failed"
        assert (await c.get("/api/library")).status_code == 401

    fake = FakeAuth0()
    async with client(app_with(make_database_url(), auth0(fake))) as c:
        start = await c.get("/auth/signin")
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        fake.claims["nonce"] = "replayed-nonce"
        r = await c.get("/auth/callback", params={"code": "abc", "state": state})
        assert r.headers["location"] == "/?auth_error=oauth_failed"

    # A tampered session cookie is ignored.
    async with client(app_with(make_database_url(), auth0(FakeAuth0()))) as c:
        c.cookies.set("shelfmark_session", "AQ" + "A" * 60)
        assert (await c.get("/api/library")).status_code == 401


async def test_allowlist_blocks_other_accounts(make_database_url):
    fake = FakeAuth0()
    async with client(
        app_with(make_database_url(), auth0(fake), allowed="auth0|someone-else")
    ) as c:
        await sign_in(c, fake)
        r = await c.get("/api/library")
        assert r.status_code == 403 and "google-oauth2|1234" in r.json()["detail"]


async def test_production_fails_closed_without_configuration(make_database_url):
    auth = select_auth(Settings(_env_file=None))  # production default, no secrets
    assert auth.configuration_error()
    async with client(app_with(make_database_url(), auth)) as c:
        assert (await c.get("/api/library")).status_code == 503
        assert (await c.get("/auth/signin")).status_code == 503
        signout = await c.post("/auth/signout")
        assert signout.headers["location"] == "/"
        assert (await c.get("/healthz")).status_code == 200
    with pytest.raises(RuntimeError):
        select_auth(Settings(_env_file=None, auth_provider="local"))
