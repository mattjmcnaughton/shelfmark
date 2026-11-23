"""Hand-written fakes for the app's external boundaries."""

from datetime import UTC, datetime, timedelta

from shelfmark.clients.fetcher import FetchedPage, FetchError


class FakeFetcher:
    """Serves canned pages by URL; unknown URLs fail like an unreachable site."""

    def __init__(self, pages: dict[str, str | FetchError] | None = None) -> None:
        self.pages: dict[str, str | FetchError] = dict(pages or {})
        self.content_types: dict[str, str] = {}
        self.fetched: list[str] = []

    async def fetch(self, url: str) -> FetchedPage:
        self.fetched.append(url)
        page = self.pages.get(url)
        if page is None:
            raise FetchError("Could not reach the site.")
        if isinstance(page, FetchError):
            raise page
        kind = self.content_types.get(url) or (
            "text/html"
            if page.lstrip().lower().startswith("<!doctype html")
            else "application/xml"
        )
        return FetchedPage(url=url, text=page, content_type=kind)


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 11, 21, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def rss(title: str, *entries: tuple[str, str, str, str]) -> str:
    """entries: (title, link, pubDate, html description)"""
    items = "".join(
        f"<item><title>{t}</title><link>{link}</link><pubDate>{d}</pubDate>"
        f"<description><![CDATA[{html}]]></description></item>"
        for t, link, d, html in entries
    )
    channel = f"<channel><title>{title}</title>{items}</channel>"
    return f'<?xml version="1.0"?><rss version="2.0">{channel}</rss>'


ARTICLE = (
    "<!doctype html><html><head><title>Slow Reading - Example</title>"
    '<meta name="author" content="Ada Lovelace"></head><body>'
    "<nav>Home | About</nav><article><h1>Slow Reading</h1>"
    + "<p>Reading slowly is a practice worth keeping in a hurried world. </p>"
    * 12
    + "<h2>Why</h2><p>Because attention compounds.</p>"
    '<script>steal()</script><img src=x onerror="alert(1)"></article></body></html>'
)
