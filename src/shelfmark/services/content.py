"""Turn untrusted HTML into plain-text reading blocks.

Fetched pages and feed entries are untrusted. Nothing here returns HTML: the output
is a list of ``{"text": str, "heading": bool}`` blocks that the desk renders as
text nodes, so scripts, styles, attributes, and links in the source never reach the
browser.
"""

import contextlib
from dataclasses import dataclass, field

import lxml.html
from lxml import etree
from lxml.html import HtmlElement
from readability import Document

HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
BLOCK_TAGS = HEADING_TAGS | {
    "p",
    "div",
    "li",
    "ul",
    "ol",
    "dl",
    "dt",
    "dd",
    "pre",
    "blockquote",
    "section",
    "article",
    "main",
    "header",
    "footer",
    "aside",
    "nav",
    "figure",
    "figcaption",
    "table",
    "tr",
    "td",
    "th",
    "caption",
    "hr",
    "address",
    "details",
    "summary",
}
DROP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe", "form")
CHROME_TAGS = ("nav", "aside", "footer", "header", "button", "sup")
CHROME_HINTS = (
    "navbox",
    "sidebar",
    "infobox",
    "mw-editsection",
    "reflist",
    "toc",
    "share",
)
MAX_BLOCKS = 250
MAX_BLOCK_CHARS = 8000

Block = dict[str, str | bool]


@dataclass(frozen=True)
class Article:
    title: str = ""
    author: str = ""
    deck: str = ""
    blocks: list[Block] = field(default_factory=list)


def html_to_blocks(html: str) -> list[Block]:
    """Linearize HTML into text blocks.

    Block-level elements and double line breaks end a block; inline markup and
    single ``<br>`` become spaces. Text outside any block element is kept.
    """
    if not html or not html.strip():
        return []
    try:
        root = lxml.html.fragment_fromstring(html, create_parent="div")
    except (etree.ParserError, ValueError):
        return []
    for bad in root.iter(*DROP_TAGS):
        bad.drop_tree()
    return _Linearizer().run(root)


class _Linearizer:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.buffer: list[str] = []
        self.pending_break = False

    def run(self, root) -> list[Block]:
        self.walk(root, heading=False)
        self.flush(heading=False)
        return self.blocks[:MAX_BLOCKS]

    def flush(self, heading: bool) -> None:
        text = " ".join("".join(self.buffer).split())
        self.buffer.clear()
        self.pending_break = False
        if text and len(self.blocks) < MAX_BLOCKS:
            self.blocks.append({"text": text[:MAX_BLOCK_CHARS], "heading": heading})

    def add(self, text: str | None) -> None:
        if not text:
            return
        if text.strip():
            self.pending_break = False
        self.buffer.append(text)

    def walk(self, el, heading: bool) -> None:
        tag = el.tag.lower() if isinstance(el.tag, str) else ""
        if tag == "br":
            if self.pending_break:
                self.flush(heading)
            else:
                self.buffer.append(" ")
                self.pending_break = True
        elif tag:
            inner = heading or tag in HEADING_TAGS
            block = tag in BLOCK_TAGS
            if block:
                self.flush(heading)
            self.add(el.text)
            for child in el:
                self.walk(child, inner)
            if block:
                self.flush(inner)
        self.add(el.tail)


def extract_article(html: str) -> Article:
    """Readability extraction of a full page into plain-text blocks."""
    try:
        doc = Document(html)
        summary = doc.summary(html_partial=True)
        title = (doc.short_title() or "").strip()
    except Exception:  # readability raises assorted parser errors on junk input
        return Article()
    blocks = html_to_blocks(summary)
    region = _main_region_blocks(html)
    if _words(region) > 2 * _words(blocks):
        # Readability sometimes keeps one section of a long page (e.g. Wikipedia).
        blocks = region
    author = _meta(html, "author")
    deck = _meta(html, "description") or _meta(html, "og:description")
    return Article(
        title=title[:400],
        author=author[:200],
        deck=_shorten(deck, 280),
        blocks=blocks,
    )


def plain_text(html_or_text: str, limit: int) -> str:
    """Collapse a possibly-HTML snippet (feed titles, authors) to plain text."""
    if not html_or_text:
        return ""
    if "<" in html_or_text:
        with contextlib.suppress(etree.ParserError, ValueError):
            html_or_text = _text(lxml.html.fragment_fromstring(html_or_text, "div"))
    return " ".join(html_or_text.split())[:limit]


def _main_region_blocks(html: str) -> list[Block]:
    """Blocks from the page's own <main>/<article> region, minus page chrome."""
    try:
        root = lxml.html.document_fromstring(html)
    except (etree.ParserError, ValueError):
        return []
    regions = [el for el in root.iter("main", "article") if isinstance(el.tag, str)] + [
        el for el in root.iter() if el.get("role") == "main"
    ]
    if not regions:
        return []
    best: HtmlElement = max(regions, key=lambda el: len(el.text_content() or ""))
    for el in list(best.iter()):
        if el is best or not isinstance(el, HtmlElement):
            continue
        classes = f"{el.get('class', '')} {el.get('id', '')}".lower()
        if el.tag in CHROME_TAGS or any(hint in classes for hint in CHROME_HINTS):
            el.drop_tree()
    return html_to_blocks(lxml.html.tostring(best, encoding="unicode"))


def _words(blocks: list[Block]) -> int:
    return sum(len(str(b["text"]).split()) for b in blocks)


def _text(el) -> str:
    return " ".join(el.text_content().split())


def _meta(html: str, name: str) -> str:
    try:
        root = lxml.html.document_fromstring(html)
    except (etree.ParserError, ValueError):
        return ""
    for attr in ("name", "property"):
        for node in root.iter("meta"):
            if node.get(attr) != name:
                continue
            content = " ".join(str(node.get("content") or "").split())
            if content:
                return content
    return ""


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip(" ,;:") + "…"
