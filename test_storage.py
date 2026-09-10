import os
import tempfile
import unittest

from model import Block
from storage import (
    MarkdownDocument,
    load_document,
    parse_document,
    save_document,
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


if __name__ == "__main__":
    unittest.main()
