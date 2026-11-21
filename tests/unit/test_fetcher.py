"""The public-web guard: what the server refuses to fetch."""

import pytest

from shelfmark.clients.fetcher import (
    BlockedURLError,
    PublicWebFetcher,
    check_public_hostname,
    is_public_address,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "224.0.0.1",
        "ff02::1",
    ],
)
def test_private_and_special_addresses_are_not_public(address):
    assert not is_public_address(address)


@pytest.mark.parametrize(
    "address", ["93.184.215.14", "2606:4700::6810:84e5", "::ffff:8.8.8.8"]
)
def test_public_addresses_are_public(address):
    assert is_public_address(address)


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "[::1]",
        "localhost",
        "intranet",
        "db.internal",
        "printer.local",
        "x.localhost.",
    ],
)
def test_hosts_that_are_never_public_websites(host):
    with pytest.raises(BlockedURLError):
        check_public_hostname(host)


async def test_fetch_refuses_loopback_before_connecting():
    with pytest.raises(BlockedURLError):
        await PublicWebFetcher().fetch("http://127.0.0.1/")
    with pytest.raises(BlockedURLError):
        await PublicWebFetcher().fetch("http://localhost/")
