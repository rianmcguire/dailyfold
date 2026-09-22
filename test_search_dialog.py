import unittest
from datetime import date

from search_dialog import _search_result_markup, format_journal_date


class TestJournalDateFormatting(unittest.TestCase):
    def test_iso_date_followed_by_weekday(self):
        self.assertEqual(
            format_journal_date(date(2026, 9, 14)),
            "2026-09-14 Monday",
        )


class TestSearchResultMarkup(unittest.TestCase):
    def test_highlights_every_case_insensitive_match_and_escapes_text(self):
        self.assertEqual(
            _search_result_markup("<Launch> and LAUNCH", "launch"),
            '&lt;<span background="#fff0a8" foreground="#222222">'
            'Launch</span>&gt; and '
            '<span background="#fff0a8" foreground="#222222">LAUNCH</span>',
        )

    def test_flattens_multiline_blocks_for_result_display(self):
        self.assertEqual(
            _search_result_markup("first\nsecond", "second"),
            'first <span background="#fff0a8" foreground="#222222">'
            'second</span>',
        )
