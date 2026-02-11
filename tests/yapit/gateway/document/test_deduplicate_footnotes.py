"""Tests for footnote deduplication across independently-extracted pages."""

from yapit.gateway.document.extraction import deduplicate_footnotes


class TestDeduplicateFootnotes:
    def test_single_page_noop(self):
        pages = {0: "Text[^1].\n\n[^1]: Footnote."}
        assert deduplicate_footnotes(pages) == pages

    def test_no_footnotes_noop(self):
        pages = {0: "Hello", 1: "World"}
        assert deduplicate_footnotes(pages) == pages

    def test_no_collisions_noop(self):
        """Unique labels across pages — nothing to do."""
        pages = {
            0: "Text[^1].\n\n[^1]: First.",
            1: "Text[^2].\n\n[^2]: Second.",
        }
        assert deduplicate_footnotes(pages) == pages

    def test_per_page_footnotes_different_content(self):
        """Same label on two pages with different defs — the core collision case."""
        pages = {
            0: "Claim A[^1].\n\n[^1]: Source A.",
            1: "Claim B[^1].\n\n[^1]: Source B.",
        }
        result = deduplicate_footnotes(pages)
        # Each page's ref+def should be renamed to match each other
        assert "[^p0-1]" in result[0]
        assert "[^p0-1]:" in result[0]
        assert "[^p1-1]" in result[1]
        assert "[^p1-1]:" in result[1]
        # Original labels gone
        assert "[^1]" not in result[0]
        assert "[^1]" not in result[1]

    def test_cross_page_ref_def_not_broken(self):
        """Ref on one page, def on another — NOT a collision. Must stay linked."""
        pages = {
            1: "Something important[^1].",
            9: "[^1]: The explanation.",
        }
        result = deduplicate_footnotes(pages)
        # Should be untouched — no collision among defs
        assert result == pages

    def test_endnotes_multiple_refs_one_def(self):
        """Multiple pages reference [^1], definition only on last page."""
        pages = {
            0: "First ref[^1].",
            3: "Second ref[^1].",
            9: "[^1]: Endnote content.",
        }
        result = deduplicate_footnotes(pages)
        # No def collision (only page 9 defines [^1]) — everything untouched
        assert result == pages

    def test_page_boundary_split(self):
        """Ref at end of one page, def at start of next — cross-page link."""
        pages = {
            2: "End of page ref[^1].",
            3: "[^1]: Definition on next page.",
        }
        result = deduplicate_footnotes(pages)
        assert result == pages

    def test_duplicate_content_across_pages(self):
        """Same ref+def on multiple pages (Gemini duplicates). Gets renamed but not broken."""
        pages = {
            1: "Text[^1].\n\n[^1]: Same content.",
            4: "Text[^1].\n\n[^1]: Same content.",
        }
        result = deduplicate_footnotes(pages)
        # Defs collide → both renamed. Each ref still matches its own def.
        assert "[^p1-1]" in result[1]
        assert "[^p1-1]:" in result[1]
        assert "[^p4-1]" in result[4]
        assert "[^p4-1]:" in result[4]

    def test_only_colliding_labels_renamed(self):
        """Non-colliding labels on the same page should not be touched."""
        pages = {
            0: "A[^1] and B[^unique].\n\n[^1]: Note.\n[^unique]: Other.",
            1: "C[^1].\n\n[^1]: Different note.",
        }
        result = deduplicate_footnotes(pages)
        # [^1] collides → renamed
        assert "[^p0-1]" in result[0]
        assert "[^p0-1]:" in result[0]
        # [^unique] doesn't collide → untouched
        assert "[^unique]" in result[0]
        assert "[^unique]:" in result[0]

    def test_ref_only_pages_untouched_when_defs_collide(self):
        """Pages with only a ref (no def) for a colliding label are left alone."""
        pages = {
            0: "Ref here[^1].\n\n[^1]: Def A.",
            2: "Cross-page ref[^1].",  # ref only, no def
            5: "Another[^1].\n\n[^1]: Def B.",
        }
        result = deduplicate_footnotes(pages)
        # Pages 0 and 5 have colliding defs → renamed
        assert "[^p0-1]" in result[0]
        assert "[^p5-1]" in result[5]
        # Page 2 has no def → left alone
        assert result[2] == pages[2]

    def test_multiple_labels_some_colliding(self):
        """Mix of colliding and non-colliding labels across pages."""
        pages = {
            0: "A[^1] B[^2].\n\n[^1]: One.\n[^2]: Two.",
            1: "C[^1] D[^3].\n\n[^1]: Uno.\n[^3]: Three.",
        }
        result = deduplicate_footnotes(pages)
        # [^1] collides → renamed on both pages
        assert "[^p0-1]" in result[0]
        assert "[^p1-1]" in result[1]
        # [^2] and [^3] don't collide → untouched
        assert "[^2]" in result[0]
        assert "[^3]" in result[1]

    def test_multiple_refs_to_same_footnote_on_one_page(self):
        """Same footnote referenced twice on the same page."""
        pages = {
            0: "First[^1] and again[^1].\n\n[^1]: Shared note.",
            1: "Other[^1].\n\n[^1]: Different.",
        }
        result = deduplicate_footnotes(pages)
        # Both refs + the def on page 0 should be renamed
        assert result[0].count("[^p0-1]") == 3  # 2 refs + 1 def (with colon)
        assert "[^p0-1]:" in result[0]
