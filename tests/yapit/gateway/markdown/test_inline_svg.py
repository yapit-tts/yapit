"""An SVG written into the markdown as HTML becomes an image block that speaks its text alternative."""

import base64
import xml.etree.ElementTree as ET

import pytest

from yapit.gateway.markdown import DocumentTransformer, parse_markdown
from yapit.gateway.markdown.models import ImageBlock, ParagraphBlock

SVG_NS = "{http://www.w3.org/2000/svg}"

# The shape defuddle writes an inline chart in: one line, the open tag followed by more tags.
CHART = (
    '<svg id="tf-chart" viewBox="0 0 720 472" role="img" aria-label="Safety against customizability: '
    'fully closed is safe, open-weight is &#39;customizable&#39;.">'
    '<defs><marker id="arr"><path d="M0,0 L10,5"></path></marker></defs>'
    '<text fill="currentColor" x="96" y="424">Low</text> <text x="684" y="424">High</text> '
    '<text x="390" y="446">R&amp;D</text></svg>'
)


def blocks(markdown: str):
    return DocumentTransformer().transform(parse_markdown(markdown)).blocks


def decoded(block: ImageBlock) -> ET.Element:
    prefix = "data:image/svg+xml;base64,"
    assert block.src.startswith(prefix)
    return ET.fromstring(base64.b64decode(block.src.removeprefix(prefix)))


def test_inline_chart_is_an_image_that_speaks_its_aria_label():
    before, image, caption = blocks(f"Some prose.\n\n{CHART}\n\nFigure 3. The tradeoff.")

    assert isinstance(before, ParagraphBlock)
    assert isinstance(image, ImageBlock)
    assert image.alt == "Safety against customizability: fully closed is safe, open-weight is 'customizable'."
    assert [c.text for c in image.audio_chunks] == [image.alt]
    assert isinstance(caption, ParagraphBlock)
    assert [c.text for c in caption.audio_chunks] == ["Figure 3. The tradeoff."]


def test_image_is_a_standalone_svg_document_sized_by_its_viewbox():
    (image,) = blocks(CHART)
    root = decoded(image)

    assert root.tag == f"{SVG_NS}svg"
    assert (root.get("width"), root.get("height")) == ("720", "472")
    assert [t.text for t in root.iter(f"{SVG_NS}text")] == ["Low", "High", "R&D"]


def test_multiline_svg_html_block_is_an_image():
    markdown = '<svg viewBox="0 0 10 10" aria-label="A dot">\n<circle cx="5" cy="5" r="2"/>\n</svg>\n\nAfter.'
    image, after = blocks(markdown)

    assert isinstance(image, ImageBlock)
    assert image.alt == "A dot"
    assert decoded(image).find(f"{SVG_NS}circle") is not None
    assert isinstance(after, ParagraphBlock)


def test_declared_namespace_and_size_are_kept():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20" viewBox="0 0 400 200"><title>Bars</title></svg>'
    )
    (image,) = blocks(svg)
    root = decoded(image)

    assert (root.get("width"), root.get("height")) == ("40", "20")
    assert image.alt == "Bars"


def test_percentage_width_is_replaced_by_the_viewbox_size():
    (image,) = blocks('<svg viewBox="0 0 400 100" width="100%" height="100%"><rect/></svg>')

    assert (decoded(image).get("width"), decoded(image).get("height")) == ("400", "100")


def test_xlink_namespace_is_declared_when_used():
    (image,) = blocks('<svg viewBox="0 0 1 1"><use xlink:href="#a"/></svg>')

    assert decoded(image).find(f"{SVG_NS}use") is not None


@pytest.mark.parametrize(
    "markdown",
    [
        'An icon <svg viewBox="0 0 1 1"><path d="M0,0"/></svg> inside a sentence.',
        '<svg viewBox="0 0 1 1"></svg> trailing words',
    ],
)
def test_svg_among_prose_stays_a_paragraph(markdown):
    assert [type(b) for b in blocks(markdown)] == [ParagraphBlock]


def test_svg_without_text_alternative_is_silent():
    (image,) = blocks('<svg viewBox="0 0 1 1"><text>Low</text></svg>')

    assert image.alt == ""
    assert image.audio_chunks == []
