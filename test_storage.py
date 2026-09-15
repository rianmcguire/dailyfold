from datetime import date
import os
import tempfile
import unittest

from model import Block
from storage import (
    MarkdownDocument,
    default_data_dir,
    document_is_empty,
    journal_dates,
    journal_path,
    load_document,
    parse_document,
    save_document,
    save_journal_document,
    serialize_document,
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


class TestParseDocument(unittest.TestCase):
    def test_parses_nested_blocks_and_multiline_content(self):
        document = parse_document(
            "- parent\n"
            "  second line\n"
            "    - child\n"
            "        - grandchild\n"
            "- sibling\n"
        )
        self.assertEqual(
            block_shape(document),
            [
                (0, "parent\nsecond line", None, False, ()),
                (1, "child", None, False, ()),
                (2, "grandchild", None, False, ()),
                (0, "sibling", None, False, ()),
            ],
        )

    def test_accepts_tab_indentation(self):
        document = parse_document("- parent\n\t- child\n\t\t- grandchild")
        self.assertEqual([b.level for b in document.blocks], [0, 1, 2])

    def test_preserves_page_and_block_properties(self):
        document = parse_document(
            "title:: Example\n"
            "alias:: Demo\n"
            "\n"
            "- parent\n"
            "  id:: abc-123\n"
            "  collapsed:: true\n"
            "  - child\n"
        )
        self.assertEqual(
            document.preamble,
            ["title:: Example", "alias:: Demo", ""],
        )
        parent = document.blocks[0]
        self.assertEqual(parent.properties, ("id:: abc-123", "collapsed:: true"))
        self.assertTrue(parent.collapsed)

    def test_preserves_star_prefixed_mirror_properties(self):
        source = (
            "- parent\n"
            "  * id:: abc-123\n"
            "  * collapsed:: true\n"
            "  - child\n"
        )
        document = parse_document(source)
        self.assertEqual(
            document.blocks[0].properties,
            ("* id:: abc-123", "* collapsed:: true"),
        )
        self.assertTrue(document.blocks[0].collapsed)
        self.assertEqual(serialize_document(document), source)

    def test_code_content_that_looks_like_a_block_stays_in_code(self):
        document = parse_document("- ```text\n  - not a child\n  ```\n")
        self.assertEqual(
            block_shape(document),
            [(0, "- not a child", "text", False, ())],
        )

    def test_mixed_prose_and_code_is_split_into_blocks(self):
        document = parse_document(
            "- before\n"
            "  ```python\n"
            "  print('hello')\n"
            "  ```\n"
            "  after\n"
        )
        self.assertEqual(
            block_shape(document),
            [
                (0, "before", None, False, ()),
                (0, "print('hello')", "python", False, ()),
                (0, "after", None, False, ()),
            ],
        )

    def test_tracks_missing_final_newline(self):
        self.assertFalse(parse_document("- block").trailing_newline)
        self.assertTrue(parse_document("- block\n").trailing_newline)


class TestSerializeDocument(unittest.TestCase):
    def test_roundtrips_supported_document(self):
        source = (
            "title:: Example\n"
            "\n"
            "- parent\n"
            "  id:: abc-123\n"
            "  collapsed:: true\n"
            "  second line\n"
            "  - child\n"
            "    - ```python\n"
            "      print('hello')\n"
            "      ```\n"
        )
        self.assertEqual(serialize_document(parse_document(source)), source)

    def test_fold_state_updates_collapsed_property(self):
        document = MarkdownDocument(
            [Block(0, "parent", properties=("id:: abc",))]
        )
        document.blocks[0].collapsed = True
        self.assertEqual(
            serialize_document(document),
            "- parent\n  id:: abc\n  collapsed:: true\n",
        )
        document.blocks[0].collapsed = False
        self.assertEqual(
            serialize_document(document),
            "- parent\n  id:: abc\n",
        )

    def test_code_properties_follow_the_fence(self):
        document = MarkdownDocument(
            [Block(0, "body", code_lang="text", properties=("id:: abc",))]
        )
        source = "- ```text\n  body\n  ```\n  id:: abc\n"
        self.assertEqual(serialize_document(document), source)
        self.assertEqual(block_shape(parse_document(source)), block_shape(document))


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
