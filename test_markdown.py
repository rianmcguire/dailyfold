import unittest
from pathlib import Path

from markdown import (
    link_url_at_display_offset,
    parse_inline,
    runs_to_html,
    runs_to_markup,
    source_offset_from_display,
)


class TestParseInline(unittest.TestCase):
    def test_bundled_example_uses_renderable_italic_markers(self):
        example = Path(__file__).with_name("example.md").read_text(
            encoding="utf-8"
        )
        lines = example.splitlines()
        italic_example = next(
            line for line in lines if "inline markdown:" in line
        )
        nested_example = next(
            line for line in lines if "combined formatting:" in line
        )

        self.assertIn(
            "<i>italic</i>",
            runs_to_markup(parse_inline(italic_example).runs),
        )
        self.assertIn(
            "<i>nested italic</i>",
            runs_to_markup(parse_inline(nested_example).runs),
        )

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

    def test_underscore_emphasis_renders_as_italic(self):
        parsed = parse_inline("_italic_")

        self.assertEqual(parsed.display_text, "italic")
        self.assertEqual(
            runs_to_markup(parsed.runs),
            "<i>italic</i>",
        )

    def test_underscore_emphasis_can_nest(self):
        parsed = parse_inline("**bold with _italic_ inside**")

        self.assertEqual(parsed.display_text, "bold with italic inside")
        self.assertEqual(
            [(run.text, run.style) for run in parsed.runs],
            [
                ("bold with ", frozenset({"bold"})),
                ("italic", frozenset({"bold", "italic"})),
                (" inside", frozenset({"bold"})),
            ],
        )

    def test_underscores_inside_words_stay_literal(self):
        parsed = parse_inline("snake_case and foo__bar__baz")

        self.assertEqual(parsed.display_text, "snake_case and foo__bar__baz")
        self.assertTrue(all(not run.style for run in parsed.runs))

    def test_underscore_emphasis_maps_display_boundaries_to_source(self):
        parsed = parse_inline("_word_")

        self.assertEqual(parsed.display_to_source, (1, 2, 3, 4, 5))

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

    def test_strikethrough_renders_to_pango_and_html(self):
        parsed = parse_inline("keep ~~remove~~")

        self.assertEqual(parsed.display_text, "keep remove")
        self.assertEqual(runs_to_markup(parsed.runs), "keep <s>remove</s>")
        self.assertEqual(runs_to_html(parsed.runs), "keep <del>remove</del>")

    def test_different_inline_styles_can_nest(self):
        parsed = parse_inline("**bold and *italic* and ~~gone~~**")

        self.assertEqual(parsed.display_text, "bold and italic and gone")
        self.assertEqual(
            [(run.text, run.style) for run in parsed.runs],
            [
                ("bold and ", frozenset({"bold"})),
                ("italic", frozenset({"bold", "italic"})),
                (" and ", frozenset({"bold"})),
                ("gone", frozenset({"bold", "strike"})),
            ],
        )

    def test_code_span_contents_are_not_parsed(self):
        parsed = parse_inline("`**literal** https://example.com`")

        self.assertEqual(parsed.display_text, "**literal** https://example.com")
        self.assertEqual(len(parsed.runs), 1)
        self.assertEqual(parsed.runs[0].style, frozenset({"code"}))
        self.assertIsNone(parsed.runs[0].link_url)

    def test_markdown_link_supports_formatted_label(self):
        parsed = parse_inline(
            "[**Dailyfold** docs](https://example.com/a?x=1&y=2)"
        )

        self.assertEqual(parsed.display_text, "Dailyfold docs")
        self.assertTrue(all(run.link_url for run in parsed.runs))
        self.assertEqual(
            runs_to_html(parsed.runs),
            '<a href="https://example.com/a?x=1&amp;y=2">'
            "<strong>Dailyfold</strong></a>"
            '<a href="https://example.com/a?x=1&amp;y=2"> docs</a>',
        )
        self.assertIn('foreground="#1a5fb4"', runs_to_markup(parsed.runs))

    def test_link_mapping_skips_label_and_destination_markers(self):
        parsed = parse_inline("[docs](target) next")

        self.assertEqual(parsed.display_text, "docs next")
        self.assertEqual(parsed.display_to_source[:5], (1, 2, 3, 4, 14))

    def test_finds_link_at_displayed_character(self):
        parsed = parse_inline("See [the **docs**](https://example.com) now")

        self.assertIsNone(link_url_at_display_offset(parsed, 3))
        for offset in range(4, 12):
            self.assertEqual(
                link_url_at_display_offset(parsed, offset),
                "https://example.com",
            )
        self.assertIsNone(link_url_at_display_offset(parsed, 12))
        self.assertIsNone(link_url_at_display_offset(parsed, -1))
        self.assertIsNone(
            link_url_at_display_offset(parsed, len(parsed.display_text))
        )

    def test_angle_url_and_email_autolinks(self):
        url = parse_inline("<https://example.com/a>")
        email = parse_inline("<hello@example.com>")

        self.assertEqual(url.display_text, "https://example.com/a")
        self.assertEqual(url.runs[0].link_url, "https://example.com/a")
        self.assertEqual(email.display_text, "hello@example.com")
        self.assertEqual(email.runs[0].link_url, "mailto:hello@example.com")

    def test_bare_url_does_not_consume_sentence_punctuation(self):
        parsed = parse_inline("Visit https://example.com/path?q=1.")

        self.assertEqual(parsed.display_text, "Visit https://example.com/path?q=1.")
        self.assertEqual(parsed.runs[1].text, "https://example.com/path?q=1")
        self.assertEqual(parsed.runs[1].link_url, parsed.runs[1].text)
        self.assertEqual(parsed.runs[2].text, ".")

    def test_malformed_link_markup_remains_literal(self):
        parsed = parse_inline("[broken](target")

        self.assertEqual(parsed.display_text, "[broken](target")
        self.assertTrue(all(run.link_url is None for run in parsed.runs))

    def test_active_link_scheme_is_not_exported(self):
        parsed = parse_inline("[unsafe](javascript:alert%281%29)")

        self.assertEqual(parsed.display_text, "[unsafe](javascript:alert%281%29)")
        self.assertNotIn("<a ", runs_to_html(parsed.runs))

    def test_malformed_link_destination_does_not_break_parsing(self):
        parsed = parse_inline("[broken](http://[)")

        self.assertEqual(parsed.display_text, "[broken](http://[)")


if __name__ == "__main__":
    unittest.main()
