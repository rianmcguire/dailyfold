import unittest

from markdown import (
    parse_inline,
    runs_to_markup,
    source_offset_from_display,
)


class TestParseInline(unittest.TestCase):
    def test_plain_text_maps_every_display_boundary_to_source(self):
        parsed = parse_inline("plain")

        self.assertEqual(parsed.display_text, "plain")
        self.assertEqual(parsed.display_to_source, (0, 1, 2, 3, 4, 5))

    def test_markers_are_skipped_at_styled_run_boundaries(self):
        parsed = parse_inline("a **bold** z")

        self.assertEqual(parsed.display_text, "a bold z")
        self.assertEqual(
            parsed.display_to_source,
            (0, 1, 4, 5, 6, 7, 10, 11, 12),
        )

    def test_existing_styles_still_render_as_pango_markup(self):
        parsed = parse_inline("**bold** *italic* `code` & plain")

        self.assertEqual(
            runs_to_markup(parsed.runs),
            "<b>bold</b> <i>italic</i> <tt>code</tt> &amp; plain",
        )

    def test_end_of_styled_text_stays_inside_closing_marker(self):
        parsed = parse_inline("**bold**")

        self.assertEqual(parsed.display_to_source, (2, 3, 4, 5, 6))
        self.assertEqual(parsed.source_offset(4), 6)

    def test_empty_text_has_one_cursor_boundary(self):
        parsed = parse_inline("")

        self.assertEqual(parsed.display_text, "")
        self.assertEqual(parsed.display_to_source, (0,))
        self.assertEqual(parsed.source_offset(0), 0)

    def test_source_lookup_clamps_out_of_range_display_positions(self):
        parsed = parse_inline("text")

        self.assertEqual(parsed.source_offset(-10), 0)
        self.assertEqual(parsed.source_offset(10), 4)

    def test_backslash_escape_uses_non_contiguous_mapping(self):
        parsed = parse_inline(r"a\*b")

        self.assertEqual(parsed.display_text, "a*b")
        self.assertEqual(parsed.display_to_source, (0, 1, 3, 4))
        self.assertEqual(source_offset_from_display(parsed, 2), 3)

    def test_backslash_only_escapes_ascii_punctuation(self):
        parsed = parse_inline("\\a \\* \\\\")

        self.assertEqual(parsed.display_text, "\\a * \\")

    def test_escaped_markers_do_not_start_formatting(self):
        parsed = parse_inline(r"\*literal\* and \`code\`")

        self.assertEqual(parsed.display_text, "*literal* and `code`")
        self.assertTrue(all(not run.style for run in parsed.runs))


if __name__ == "__main__":
    unittest.main()
