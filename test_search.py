from datetime import date
import tempfile
import unittest

from block_markdown import MarkdownDocument
from model import Block
from search import compact_block_text, search_journals
from storage import journal_path, save_document


class TestSearchJournals(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = self.temporary.name

    def tearDown(self):
        self.temporary.cleanup()

    def save(self, day, blocks):
        save_document(
            journal_path(self.data_dir, day),
            MarkdownDocument(blocks),
        )

    def test_returns_substring_matches_newest_day_first(self):
        self.save(date(2026, 9, 14), [Block(0, "Launch notes")])
        self.save(
            date(2026, 9, 16),
            [Block(0, "Work"), Block(1, "Draft the LAUNCH announcement")],
        )

        results = search_journals(self.data_dir, "launch")

        self.assertEqual(
            [(result.day, result.block_index) for result in results],
            [(date(2026, 9, 16), 1), (date(2026, 9, 14), 0)],
        )
        self.assertEqual(results[0].ancestors, ("Work",))
        self.assertEqual(
            results[0].text[results[0].match_start : results[0].match_end],
            "LAUNCH",
        )

    def test_preserves_document_order_within_a_day(self):
        day = date(2026, 9, 16)
        self.save(day, [Block(0, "first hit"), Block(0, "second hit")])
        self.assertEqual(
            [result.text for result in search_journals(self.data_dir, "hit")],
            ["first hit", "second hit"],
        )

    def test_breadcrumb_contains_ancestors_but_not_matching_block(self):
        day = date(2026, 9, 16)
        self.save(
            day,
            [
                Block(0, "Project"),
                Block(1, "Planning\nnotes"),
                Block(2, "Needle here"),
                Block(1, "Sibling needle"),
            ],
        )

        results = search_journals(self.data_dir, "needle")

        self.assertEqual(results[0].ancestors, ("Project", "Planning notes"))
        self.assertEqual(results[1].ancestors, ("Project",))

    def test_empty_query_has_no_results(self):
        self.save(date(2026, 9, 16), [Block(0, "anything")])
        self.assertEqual(search_journals(self.data_dir, ""), [])

    def test_stops_at_result_limit(self):
        newest = date(2026, 9, 16)
        older = date(2026, 9, 15)
        self.save(newest, [Block(0, f"hit {index}") for index in range(4)])
        self.save(older, [Block(0, "older hit")])

        results = search_journals(self.data_dir, "hit", limit=3)

        self.assertEqual(
            [result.text for result in results],
            ["hit 0", "hit 1", "hit 2"],
        )

    def test_non_positive_limit_has_no_results(self):
        self.save(date(2026, 9, 16), [Block(0, "hit")])
        self.assertEqual(search_journals(self.data_dir, "hit", limit=0), [])


class TestCompactBlockText(unittest.TestCase):
    def test_collapses_multiline_whitespace(self):
        self.assertEqual(compact_block_text("one\n  two\tthree"), "one two three")


if __name__ == "__main__":
    unittest.main()
