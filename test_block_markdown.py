import unittest

from block_markdown import (
    MarkdownDocument,
    parse_block_fragment,
    parse_document,
    serialize_block_fragment,
    serialize_document,
)
from model import Block


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


class TestBlockFragment(unittest.TestCase):
    def test_serializes_normalized_outline(self):
        blocks = [Block(1, "parent"), Block(2, "child"), Block(1, "sibling")]
        self.assertEqual(
            serialize_block_fragment(blocks),
            "- parent\n  - child\n- sibling",
        )

    def test_serializes_multiline_block(self):
        self.assertEqual(
            serialize_block_fragment([Block(0, "first\nsecond")]),
            "- first\n  second",
        )

    def test_serializes_code_block(self):
        block = Block(0, "print('hi')\nreturn", code_lang="python")
        self.assertEqual(
            serialize_block_fragment([block]),
            "- ```python\n  print('hi')\n  return\n  ```",
        )

    def test_parses_markdown_outline(self):
        blocks = parse_block_fragment("- parent\n  - child\n- sibling")
        self.assertEqual(
            [(block.level, block.text, block.code_lang) for block in blocks],
            [(0, "parent", None), (1, "child", None), (0, "sibling", None)],
        )

    def test_accepts_four_space_and_tab_indentation(self):
        spaced = parse_block_fragment(
            "- parent\n    - child\n        - grandchild"
        )
        tabbed = parse_block_fragment(
            "- parent\n\t- child\n\t\t- grandchild"
        )
        self.assertEqual([block.level for block in spaced], [0, 1, 2])
        self.assertEqual([block.level for block in tabbed], [0, 1, 2])

    def test_parses_multiline_and_code_blocks(self):
        text = "- first\n  second\n- ```python\n  print('hi')\n  return\n  ```"
        blocks = parse_block_fragment(text)
        self.assertEqual(blocks[0].text, "first\nsecond")
        self.assertEqual(blocks[1].text, "print('hi')\nreturn")
        self.assertEqual(blocks[1].code_lang, "python")

    def test_code_roundtrip_preserves_blank_lines(self):
        original = Block(0, "\nbody\n", code_lang="")
        [parsed] = parse_block_fragment(serialize_block_fragment([original]))
        self.assertEqual(parsed.text, original.text)

    def test_plain_text_is_not_a_block_fragment(self):
        self.assertIsNone(parse_block_fragment("plain\ntext"))


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
        self.assertEqual([block.level for block in document.blocks], [0, 1, 2])

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
