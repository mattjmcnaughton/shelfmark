"""Server-side HTTP fetching restricted to public websites.

Everything Shelfmark fetches (feeds, articles, YouTube oEmbed) goes through a
``Fetcher``. The production ``PublicWebFetcher`` refuses URLs that could reach the
server's own network: it resolves the hostname once, rejects the request unless
every address is publicly routable, connects only to those checked addresses (so a
second DNS answer cannot redirect the connection), re-validates every redirect, and
caps the response size and total time.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult
from yarl import URL

from shelfmark.services.urls import WebURLError, parse_web_url

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 4
TIMEOUT_SECONDS = 12
USER_AGENT = "Mozilla/5.0 (compatible; Shelfmark/0.1; +https://ampcode.com/@mattjmcnaughton/shelfmark)"


class FetchError(Exception):
    """A fetch failed; the message is safe to show to the user."""


class BlockedURLError(FetchError):
    """The URL points somewhere other than a public website."""

    def __init__(self) -> None:
        super().__init__("Shelfmark only fetches from public websites.")


@dataclass(frozen=True)
class FetchedPage:
    url: str  # final URL after redirects
    text: str
    content_type: str


class Fetcher(Protocol):
    async def fetch(self, url: str, *, truncate: bool = False) -> FetchedPage:
        """Fetch ``url``. With ``truncate``, a response over the size cap is cut at
        the cap instead of failing (enough to read a large page's ``<head>``)."""
        ...


def is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_public_hostname(host: str) -> None:
    """Reject IP literals and names that are never public websites."""
    host = host.strip("[]").rstrip(".").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise BlockedURLError
    if "." not in host or host.endswith((".localhost", ".local", ".internal")):
        raise BlockedURLError


class _PinnedResolver(AbstractResolver):
    """Answers only with addresses that were already checked."""

    def __init__(self, host: str, results: list[ResolveResult]) -> None:
        self._host = host
        self._results = results

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        if host != self._host:
            raise OSError("unexpected host")
        return [{**r, "port": port} for r in self._results]  # type: ignore[typeddict-item]

    async def close(self) -> None:
        return None


class PublicWebFetcher:
    def __init__(
        self,
        *,
        max_bytes: int = MAX_BYTES,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._max_bytes = max_bytes
        self._timeout = timeout_seconds

    async def fetch(self, url: str, *, truncate: bool = False) -> FetchedPage:
        try:
            return await asyncio.wait_for(self._follow(url, truncate), self._timeout)
        except TimeoutError as error:
            raise FetchError("The site took too long to respond.") from error

    async def _follow(self, url: str, truncate: bool) -> FetchedPage:
        for _ in range(MAX_REDIRECTS + 1):
            result = await self._fetch_once(url, truncate)
            if isinstance(result, FetchedPage):
                return result
            try:
                url = parse_web_url(urljoin(url, result))
            except WebURLError as error:
                raise BlockedURLError from error
        raise FetchError("The site redirected too many times.")

    async def _fetch_once(self, url: str, truncate: bool) -> FetchedPage | str:
        host = URL(url).raw_host or ""
        check_public_hostname(host)
        results = await _resolve(host)
        connector = aiohttp.TCPConnector(
            resolver=_PinnedResolver(host, results), use_dns_cache=False
        )
        try:
            async with (
                aiohttp.ClientSession(
                    connector=connector,
                    headers={"User-Agent": USER_AGENT},
                    trust_env=False,
                ) as session,
                session.get(url, allow_redirects=False) as response,
            ):
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise FetchError("The site sent a redirect without a target.")
                    return location
                if response.status != 200:
                    raise FetchError(f"The site returned HTTP {response.status}.")
                body = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    body.extend(chunk)
                    if len(body) > self._max_bytes:
                        if not truncate:
                            raise FetchError("The response is larger than 2 MB.")
                        del body[self._max_bytes :]
                        break
                charset = response.charset or "utf-8"
                try:
                    text = body.decode(charset, errors="replace")
                except LookupError:
                    text = body.decode("utf-8", errors="replace")
                return FetchedPage(
                    url=url,
                    text=text,
                    content_type=response.content_type or "",
                )
        except aiohttp.ClientError as error:
            raise FetchError("Could not reach the site.") from error


async def _resolve(host: str) -> list[ResolveResult]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as error:
        raise FetchError("Could not find that site.") from error
    results: list[ResolveResult] = []
    for family, _type, proto, _canon, sockaddr in infos:
        address = str(sockaddr[0])
        if not is_public_address(address):
            raise BlockedURLError
        results.append(
            {
                "hostname": host,
                "host": address,
                "port": 0,
                "family": family,
                "proto": proto,
                "flags": socket.AI_NUMERICHOST,
            }
        )
    if not results:
        raise FetchError("Could not find that site.")
    return results
