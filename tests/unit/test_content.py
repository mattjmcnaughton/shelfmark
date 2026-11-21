import pytest

from shelfmark.services.content import html_to_blocks, plain_text
from shelfmark.services.urls import WebURLError, canonical_item_url, parse_web_url


def test_html_becomes_text_blocks_without_markup():
    blocks = html_to_blocks(
        '<div><h2 onclick="x()">Title</h2>'
        '<p>Hi <a href="javascript:evil()">there</a></p>'
        "<script>steal()</script><style>p{}</style><ul><li>one</li></ul></div>"
    )
    assert blocks == [
        {"text": "Title", "heading": True},
        {"text": "Hi there", "heading": False},
        {"text": "one", "heading": False},
    ]


def test_plain_text_strips_tags_from_titles():
    assert (
        plain_text("Hello <img src=x onerror=alert(1)><b>world</b>", 50)
        == "Hello world"
    )


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://u:p@x.com/",
        "https://x.com:8443/",
    ],
)
def test_rejects_non_web_urls(url):
    with pytest.raises(WebURLError):
        parse_web_url(url)


def test_youtube_variants_share_one_canonical_url():
    canon = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    for url in (
        "https://youtu.be/dQw4w9WgXcQ",
        "https://m.youtube.com/shorts/dQw4w9WgXcQ",
    ):
        assert canonical_item_url(url) == canon
    assert canonical_item_url("https://notyoutube.com/watch?v=dQw4w9WgXcQ").startswith(
        "https://notyoutube"
    )


def test_br_separated_text_splits_into_paragraphs():
    html = "<font>First line<br>same para<br><br>Second para<br /><br />Third</font>"
    assert [b["text"] for b in html_to_blocks(html)] == [
        "First line same para",
        "Second para",
        "Third",
    ]


def test_loose_text_beside_block_elements_is_kept():
    html = "<font>Intro text<br><br><blockquote>Quoted</blockquote>Closing words</font>"
    assert [b["text"] for b in html_to_blocks(html)] == [
        "Intro text",
        "Quoted",
        "Closing words",
    ]


def test_deck_comes_from_page_description_and_ends_on_a_word():
    from shelfmark.services.content import extract_article

    words = "word " * 100
    page = (
        f'<html><head><meta name="description" content="{words}"></head><body>'
        "<article>"
        + "<p>Body paragraph with enough words to extract. </p>" * 10
        + "</article></body></html>"
    )
    deck = extract_article(page).deck
    assert deck.endswith("word…") and len(deck) <= 280
    no_meta = page.replace('name="description"', 'name="other"')
    assert extract_article(no_meta).deck == ""
