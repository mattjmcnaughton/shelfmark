"""URL validation and YouTube recognition."""

import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
# YouTube handles: 3 to 30 letters, digits, underscores, hyphens, and periods.
_HANDLE = re.compile(r"^@[A-Za-z0-9._-]{3,30}$")


class WebURLError(ValueError):
    """The value is not an acceptable web URL; the message is user-facing."""


def parse_web_url(value: str) -> str:
    """Return a normalized public-web URL or raise ``WebURLError``.

    Accepts only http(s) URLs on the default port with no credentials, and drops
    the fragment.
    """
    value = value.strip()
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise WebURLError("Enter a full HTTP or HTTPS URL.") from error
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise WebURLError("Enter a full HTTP or HTTPS URL.")
    if (
        parts.username
        or parts.password
        or port is not None
        and port != {"http": 80, "https": 443}[parts.scheme.lower()]
        or len(value) > MAX_URL_LENGTH
    ):
        raise WebURLError(
            "Use a public HTTP or HTTPS URL without credentials or a custom port."
        )
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))


def youtube_video_id(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.").removeprefix("m.")
    segments = parts.path.split("/")
    candidate: str | None = None
    if host == "youtu.be":
        candidate = segments[1] if len(segments) > 1 else None
    elif host in ("youtube.com", "youtube-nocookie.com"):
        if parts.path == "/watch":
            candidate = parse_qs(parts.query).get("v", [None])[0]
        elif len(segments) > 2 and segments[1] in ("shorts", "live", "embed"):
            candidate = segments[2]
    return candidate if candidate and _VIDEO_ID.match(candidate) else None


def _youtube_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").removeprefix("www.").removeprefix("m.")
    return host == "youtube.com"


def subscription_url(value: str) -> str:
    """What to fetch to follow ``value``: a feed or page URL, or a YouTube @handle.

    A YouTube channel ID URL maps straight to the channel's feed. Other channel
    pages (``/@handle``, ``/c/name``, ``/user/name``) advertise their feed, which
    the caller discovers from the page.
    """
    value = value.strip()
    if _HANDLE.match(value):
        return f"https://www.youtube.com/{value}"
    url = parse_web_url(value)
    parts = urlsplit(url)
    if not _youtube_host(url):
        return url
    url = urlunsplit(("https", "www.youtube.com", parts.path, parts.query, ""))
    segments = parts.path.split("/")
    if (
        len(segments) > 2
        and segments[1] == "channel"
        and _CHANNEL_ID.match(segments[2])
    ):
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={segments[2]}"
    return url


def is_youtube_page(url: str) -> bool:
    """A YouTube web page rather than one of its feeds."""
    return _youtube_host(url) and not urlsplit(url).path.startswith("/feeds/")


def canonical_item_url(url: str) -> str:
    """One URL per item, so the same video saved two ways is one item."""
    video = youtube_video_id(url)
    return f"https://www.youtube.com/watch?v={video}" if video else url


def site_name(url: str) -> str:
    return (urlsplit(url).hostname or url).removeprefix("www.")
