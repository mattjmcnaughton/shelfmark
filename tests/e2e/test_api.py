"""The HTTP API end to end: app factory, real database, fake fetcher, local auth."""

import httpx
import pytest

from shelfmark.app import create_app
from shelfmark.auth import LocalAuth
from shelfmark.config import Settings
from shelfmark.db import Database, migrate
from tests.fakes import ARTICLE, FakeClock, FakeFetcher, rss

pytestmark = pytest.mark.anyio
JSON = {"Content-Type": "application/json"}
FEED = "https://blog.example.com/feed"


def make_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://shelf.test"
    )


@pytest.fixture
async def client(make_database_url):
    url = make_database_url()
    migrate(url)
    fetcher = FakeFetcher(
        {
            FEED: rss(
                "Example",
                (
                    "First",
                    "https://blog.example.com/1",
                    "Fri, 20 Nov 2026 09:00:00 GMT",
                    "<p>Hello <script>x()</script></p>",
                ),
            ),
            "https://news.example.org/a": ARTICLE,
        }
    )
    app = create_app(
        Settings(_env_file=None, env="development"),
        database=Database(url),
        fetcher=fetcher,
        auth=LocalAuth(),
        clock=FakeClock(),
        background_refresh=False,
        serve_frontend=False,
    )
    async with app.router.lifespan_context(app), make_client(app) as c:
        yield c


async def test_reading_workflow(client):
    r = await client.post("/api/feeds", json={"url": FEED}, headers=JSON)
    assert r.status_code == 201, r.text
    feed_id = r.json()["id"]
    assert (await client.post("/api/feeds", json={"url": FEED})).status_code == 409

    inbox = (await client.get("/api/items?view=inbox")).json()["items"]
    assert [i["title"] for i in inbox] == ["First"] and inbox[0]["copy"] == "feed"
    assert inbox[0]["feed_ids"] == [feed_id] and "body" not in inbox[0]
    detail = (await client.get(f"/api/items/{inbox[0]['id']}")).json()
    assert detail["body"] == [{"text": "Hello", "heading": False}]

    r = await client.post("/api/items", json={"url": "https://news.example.org/a"})
    assert (
        r.status_code == 201 and r.json()["copy"] == "extracted" and r.json()["saved"]
    )
    saved_id = r.json()["id"]

    r = await client.patch(
        f"/api/items/{saved_id}", json={"tags": ["Ideas"], "archived": True}
    )
    assert r.json()["tags"] == ["ideas"] and r.json()["archived"]

    lib = (await client.get("/api/library")).json()
    assert lib["counts"] == {"inbox": 1, "saved": 0, "try": 0, "archive": 1}
    assert lib["tags"] == ["ideas"] and lib["user"] == {
        "name": "Local reader",
        "can_sign_out": False,
    }
    tagged = (
        await client.get("/api/items", params={"view": "tag", "tag": "ideas"})
    ).json()
    assert [i["id"] for i in tagged["items"]] == [saved_id]

    r = await client.post(
        "/api/items", json={"queue": "try", "title": "omnigent", "note": "why: agents"}
    )
    assert r.status_code == 201, r.text
    thing = r.json()
    assert thing["url"] is None and thing["kind"] == "thing" and thing["trying"]
    r = await client.patch(f"/api/items/{thing['id']}", json={"note": "edited"})
    assert r.json()["note"] == "edited"
    tries = (await client.get("/api/items?view=try")).json()["items"]
    assert [i["title"] for i in tries] == ["omnigent"]
    assert (await client.get("/api/library")).json()["counts"]["try"] == 1
    r = await client.post("/api/items", json={"queue": "try"})
    assert r.status_code == 400

    refreshed = (await client.post("/api/feeds/refresh", json={})).json()
    assert refreshed["feeds"][0]["error"] is None


async def test_rejects_bad_input_and_cross_site_writes(client):
    r = await client.post("/api/items", json={"url": "javascript:alert(1)"})
    assert r.status_code == 400 and "HTTP" in r.json()["detail"]
    r = await client.post("/api/items", json={"url": "http://127.0.0.1/"})
    assert (
        r.status_code in (200, 201) and r.json()["copy"] == "link"
    )  # fake fetcher; real one blocks
    assert (await client.get("/api/items/999")).status_code == 404
    assert (await client.get("/api/items?view=feed&feed_id=42")).status_code == 404
    assert (await client.get("/api/nope")).status_code == 404
    r = await client.post(
        "/api/items",
        json={"url": "https://x.example.com/"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/items",
        content="url=https://x.example.com/",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 415


async def test_same_site_writes_behind_tls_proxy(make_database_url):
    # The Box router terminates TLS and forwards plain http with no
    # X-Forwarded-Proto; the browser's Origin is still the public https URL.
    url = make_database_url()
    migrate(url)
    app = create_app(
        Settings(
            _env_file=None, env="development", deployment_url="https://shelf.test/"
        ),
        database=Database(url),
        fetcher=FakeFetcher({"https://news.example.org/a": ARTICLE}),
        auth=LocalAuth(),
        clock=FakeClock(),
        background_refresh=False,
        serve_frontend=False,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://shelf.test"
        ) as c,
    ):
        body = {"url": "https://news.example.org/a"}
        r = await c.post(
            "/api/items", json=body, headers={"Origin": "https://shelf.test"}
        )
        assert r.status_code == 201, r.text
        r = await c.post(
            "/api/items", json=body, headers={"Origin": "https://evil.example"}
        )
        assert r.status_code == 403


async def test_security_headers_and_health(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert (
        "frame-src https://www.youtube-nocookie.com"
        in r.headers["content-security-policy"]
    )
    assert r.headers["x-content-type-options"] == "nosniff"
    assert (await client.get("/readyz")).json() == {"status": "ready"}
