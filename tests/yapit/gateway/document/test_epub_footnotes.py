"""Tests for EPUB footnote extraction and conversion.

Two patterns exist in the wild:

1. Old-style HTML (e.g., Ubiquity): refs and definitions both survive in pandoc
   output as HTML links. Definitions are in a notes section at the end.
   - Ref: <sup><a href="#TARGET" id="BACKREF">N</a></sup>
   - Def: <a href="#BACKREF" id="TARGET">N.</a> Note text here

2. EPUB3 semantic (e.g., Deep Utopia): pandoc drops definitions entirely
   (pandoc bug #5531). Must extract from EPUB ZIP.
   - Ref: <a href="#notes.xhtml_note_N" class="noteref" role="doc-noteref">N</a>
   - Def (in ZIP): <li><span id="note_N"><a epub:type="backlink">N</a> text</span></li>

Both patterns are converted to markdown footnotes: [^N] / [^N]: text
"""

from yapit.gateway.document.processors.epub import convert_footnotes, extract_footnotes_from_zip


class TestExtractFootnotesFromZip:
    """Extract note definitions from the raw EPUB ZIP."""

    def _make_epub_zip(self, notes_xhtml: str) -> bytes:
        """Create a minimal EPUB ZIP with a notes file."""
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?>'
                '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
                '<rootfiles><rootfile full-path="content.opf"/></rootfiles></container>',
            )
            zf.writestr(
                "content.opf",
                '<?xml version="1.0"?>'
                '<package xmlns="http://www.idpf.org/2007/opf">'
                "<metadata/><manifest>"
                '<item id="notes" href="notes.xhtml" media-type="application/xhtml+xml"/>'
                "</manifest>"
                '<spine><itemref idref="notes"/></spine>'
                "</package>",
            )
            zf.writestr("notes.xhtml", notes_xhtml)
        return buf.getvalue()

    def test_extracts_epub3_endnotes(self):
        notes_xhtml = """<?xml version="1.0" encoding="UTF-8"?>
        <html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
        <body>
        <section epub:type="endnotes" role="doc-endnotes">
        <ol class="footnotes">
        <li class="notes"><span id="note_1"><a epub:type="backlink" href="ch01.xhtml#note-1">1</a> Gates (2017)</span></li>
        <li class="notes"><span id="note_2"><a epub:type="backlink" href="ch01.xhtml#note-2">2</a> Musk (2023)</span></li>
        </ol>
        </section>
        </body></html>"""

        result = extract_footnotes_from_zip(self._make_epub_zip(notes_xhtml))
        assert result["note_1"] == "Gates (2017)"
        assert result["note_2"] == "Musk (2023)"

    def test_extracts_old_style_notes(self):
        """Old-style: <a> with id and backlink href, followed by note text."""
        notes_xhtml = """<?xml version="1.0" encoding="UTF-8"?>
        <html xmlns="http://www.w3.org/1999/xhtml">
        <body>
        <p><a href="#ch01_nts1a" id="nts1">1.</a> John Kenneth Galbraith, letter to JFK.</p>
        <p><a href="#ch01_nts2a" id="nts2">2.</a> Paul Valéry, <em>Variété IV</em>.</p>
        </body></html>"""

        result = extract_footnotes_from_zip(self._make_epub_zip(notes_xhtml))
        assert result["nts1"] == "John Kenneth Galbraith, letter to JFK."
        assert "Paul Valéry" in result["nts2"]

    def test_returns_empty_when_no_notes(self):
        content = b"not a zip"
        result = extract_footnotes_from_zip(content)
        assert result == {}

    def test_returns_empty_for_epub_without_notes(self):
        no_notes_xhtml = """<?xml version="1.0" encoding="UTF-8"?>
        <html xmlns="http://www.w3.org/1999/xhtml">
        <body><p>Just a regular chapter.</p></body></html>"""

        result = extract_footnotes_from_zip(self._make_epub_zip(no_notes_xhtml))
        assert result == {}


class TestConvertFootnotes:
    """Convert inline footnote refs + definitions to markdown [^N] syntax."""

    def test_converts_sup_a_refs(self):
        """Old-style: <sup><a href="#target">N</a></sup> → [^N]"""
        md = 'Some text<sup><a href="#notes.xhtml_nts1" id="ch01_nts1a">1</a></sup> more text.'
        notes = {"nts1": "The source reference."}

        result = convert_footnotes(md, notes, "notes.xhtml")
        assert "[^1]" in result
        assert "[^1]: The source reference." in result
        assert "<sup>" not in result

    def test_converts_noteref_a_refs(self):
        """EPUB3: <a ... role="doc-noteref" ...>N</a> → [^N]"""
        md = 'Some text<a href="#notes.xhtml_note_1" class="noteref" role="doc-noteref">1</a> more text.'
        notes = {"note_1": "Gates (2017)"}

        result = convert_footnotes(md, notes, "notes.xhtml")
        assert "[^1]" in result
        assert "[^1]: Gates (2017)" in result
        assert "<a " not in result

    def test_handles_multiple_footnotes(self):
        md = (
            'First<sup><a href="#notes.xhtml_n1" id="r1">1</a></sup> '
            'second<sup><a href="#notes.xhtml_n2" id="r2">2</a></sup> text.'
        )
        notes = {"n1": "Note one.", "n2": "Note two."}

        result = convert_footnotes(md, notes, "notes.xhtml")
        assert "[^1]" in result
        assert "[^2]" in result
        assert "[^1]: Note one." in result
        assert "[^2]: Note two." in result

    def test_sequential_numbering_across_chapters(self):
        """Notes from different chapters get unique sequential numbers."""
        md = (
            'Ch1 text<sup><a href="#notes.xhtml_c01_n1">1</a></sup>.\n\n'
            'Ch2 text<sup><a href="#notes.xhtml_c02_n1">1</a></sup>.'
        )
        notes = {"c01_n1": "Chapter 1 note.", "c02_n1": "Chapter 2 note."}

        result = convert_footnotes(md, notes, "notes.xhtml")
        assert "[^1]" in result
        assert "[^2]" in result
        assert "[^1]: Chapter 1 note." in result
        assert "[^2]: Chapter 2 note." in result

    def test_no_conversion_when_no_notes(self):
        md = "Plain text without any footnotes."
        result = convert_footnotes(md, {}, "notes.xhtml")
        assert result == md

    def test_unmatched_refs_left_as_is(self):
        """Refs that don't match any note definition are not converted."""
        md = 'Text<sup><a href="#notes.xhtml_unknown">1</a></sup> more.'
        notes = {"other_id": "Some note."}

        result = convert_footnotes(md, notes, "notes.xhtml")
        assert "<sup>" in result  # left as-is

    def test_strips_notes_section_from_body(self):
        """The original notes section (heading + definitions) should be removed
        since definitions are now inline as [^N]: at the end.
        """
        md = (
            'Text<sup><a href="#notes.xhtml_n1" id="r1">1</a></sup>.\n\n'
            "# Notes and References\n\n"
            '<a href="#r1" id="notes.xhtml_n1">1.</a> The note text.\n\n'
            '<a href="#r2" id="notes.xhtml_n2">2.</a> Another note.\n'
        )
        notes = {"n1": "The note text.", "n2": "Another note."}

        result = convert_footnotes(md, notes, "notes.xhtml")
        assert "# Notes and References" not in result
        assert "[^1]: The note text." in result

    def test_handles_notes_filename_prefix(self):
        """Pandoc prefixes IDs with the source filename. The notes_filename
        parameter tells us what prefix to strip when matching.
        """
        md = 'Text<sup><a href="#endnotes.xhtml_fn42">1</a></sup>.'
        notes = {"fn42": "A footnote."}

        result = convert_footnotes(md, notes, "endnotes.xhtml")
        assert "[^1]" in result
        assert "[^1]: A footnote." in result
