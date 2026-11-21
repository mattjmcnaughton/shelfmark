"""URL validation and YouTube recognition."""

import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


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


def canonical_item_url(url: str) -> str:
    """One URL per item, so the same video saved two ways is one item."""
    video = youtube_video_id(url)
    return f"https://www.youtube.com/watch?v={video}" if video else url


def site_name(url: str) -> str:
    return (urlsplit(url).hostname or url).removeprefix("www.")
