from datetime import date
import os
import tempfile
import unittest

from block_markdown import MarkdownDocument
from model import Block
from storage import (
    default_data_dir,
    document_is_empty,
    journal_dates,
    journal_path,
    load_document,
    save_document,
    save_journal_document,
    seed_journal_from_template,
)


def block_shape(document):
    return [
        (
            block.level,
            block.text,
            block.code_lang,
            block.collapsed,
            block.properties,
        )
        for block in document.blocks
    ]


class TestFileIO(unittest.TestCase):
    def test_save_and_load_utf8_document(self):
        document = MarkdownDocument(
            [Block(0, "hello → 世界"), Block(1, "child")]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "journal", "example.md")
            save_document(path, document)
            loaded = load_document(path)
            self.assertEqual(block_shape(loaded), block_shape(document))
            with open(path, encoding="utf-8") as handle:
                saved_text = handle.read()
            self.assertEqual(
                saved_text,
                "- hello → 世界\n  - child\n",
            )
            self.assertEqual(
                [
                    name
                    for name in os.listdir(os.path.dirname(path))
                    if name != "example.md"
                ],
                [],
            )

    def test_empty_journal_removes_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "2026_09_16.md")
            save_document(path, MarkdownDocument([Block(0, "content")]))

            save_journal_document(path, MarkdownDocument([Block(0, "")]))

            self.assertFalse(os.path.exists(path))

    def test_empty_journal_without_file_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "2026_09_16.md")
            save_journal_document(path, MarkdownDocument([Block(0, "")]))
            self.assertFalse(os.path.exists(path))


class TestDocumentIsEmpty(unittest.TestCase):
    def test_accepts_no_blocks_and_blank_placeholder_blocks(self):
        self.assertTrue(document_is_empty(MarkdownDocument()))
        self.assertTrue(
            document_is_empty(
                MarkdownDocument([Block(0, ""), Block(0, "  \n")], [""])
            )
        )

    def test_preserves_text_code_and_metadata(self):
        documents = [
            MarkdownDocument([Block(0, "content")]),
            MarkdownDocument([Block(0, "", code_lang="")]),
            MarkdownDocument([Block(0, "", properties=("id:: 123",))]),
            MarkdownDocument([Block(0, "", collapsed=True)]),
            MarkdownDocument([], ["title:: Journal"]),
        ]
        for document in documents:
            with self.subTest(document=document):
                self.assertFalse(document_is_empty(document))


class TestJournalStorage(unittest.TestCase):
    def test_seeds_empty_data_dir_from_template(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = os.path.join(directory, "journal")
            os.mkdir(data_dir)
            template_path = os.path.join(directory, "example.md")
            with open(template_path, "w", encoding="utf-8") as handle:
                handle.write("- welcome\n  - first child\n")

            seeded = seed_journal_from_template(
                data_dir, date(2026, 9, 21), template_path
            )

            self.assertTrue(seeded)
            document = load_document(
                os.path.join(data_dir, "2026_09_21.md")
            )
            self.assertEqual(
                block_shape(document),
                [
                    (0, "welcome", None, False, ()),
                    (1, "first child", None, False, ()),
                ],
            )

    def test_seeds_missing_data_dir_from_template(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = os.path.join(directory, "journal")
            template_path = os.path.join(directory, "example.md")
            with open(template_path, "w", encoding="utf-8") as handle:
                handle.write("- welcome\n")

            seeded = seed_journal_from_template(
                data_dir, date(2026, 9, 21), template_path
            )

            self.assertTrue(seeded)
            self.assertTrue(
                os.path.isfile(os.path.join(data_dir, "2026_09_21.md"))
            )

    def test_does_not_seed_nonempty_data_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = os.path.join(directory, "journal")
            os.mkdir(data_dir)
            existing_path = os.path.join(data_dir, "notes.txt")
            with open(existing_path, "w", encoding="utf-8") as handle:
                handle.write("keep me")
            template_path = os.path.join(directory, "example.md")
            with open(template_path, "w", encoding="utf-8") as handle:
                handle.write("- welcome\n")

            seeded = seed_journal_from_template(
                data_dir, date(2026, 9, 21), template_path
            )

            self.assertFalse(seeded)
            self.assertFalse(
                os.path.exists(os.path.join(data_dir, "2026_09_21.md"))
            )

    def test_data_dir_environment_override_wins(self):
        self.assertEqual(
            default_data_dir(
                {
                    "DAILYFOLD_DATA_DIR": "/tmp/my-journal",
                    "XDG_DATA_HOME": "/tmp/ignored",
                }
            ),
            "/tmp/my-journal",
        )

    def test_data_dir_uses_xdg_location(self):
        self.assertEqual(
            default_data_dir({"XDG_DATA_HOME": "/tmp/app-data"}),
            "/tmp/app-data/dailyfold",
        )

    def test_data_dir_falls_back_to_local_share(self):
        self.assertEqual(
            default_data_dir({}),
            os.path.abspath(
                os.path.join(os.path.expanduser("~"), ".local", "share", "dailyfold")
            ),
        )

    def test_journal_path_uses_logseq_date(self):
        self.assertEqual(
            journal_path("/tmp/journal", date(2026, 9, 11)),
            "/tmp/journal/2026_09_11.md",
        )

    def test_lists_only_valid_dated_markdown_files(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in (
                "2026_09_11.md",
                "2026_02_29.md",
                "2026-09-11.md",
                "notes.md",
                "2026_09_11.txt",
            ):
                with open(os.path.join(directory, name), "w", encoding="utf-8"):
                    pass
            os.mkdir(os.path.join(directory, "2026_09_12.md"))
            self.assertEqual(journal_dates(directory), {date(2026, 9, 11)})

    def test_missing_data_dir_has_no_journal_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                journal_dates(os.path.join(directory, "missing")), set()
            )


if __name__ == "__main__":
    unittest.main()
