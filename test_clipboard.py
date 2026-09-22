import unittest
from unittest.mock import patch

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from _app_test_support import shape, view
from clipboard import (
    blocks_from_clipboard_payload,
    blocks_from_clipboard_text,
    blocks_to_clipboard_html,
    blocks_to_clipboard_payload,
    blocks_to_clipboard_text,
    copy_blocks,
    link_from_paste,
)
from model import Block


class TestLinkFromPaste(unittest.TestCase):
    def test_wraps_selected_text_in_markdown_link(self):
        self.assertEqual(
            link_from_paste("Dailyfold docs", "https://example.com/docs"),
            "[Dailyfold docs](https://example.com/docs)",
        )

    def test_accepts_clipboard_line_ending(self):
        self.assertEqual(
            link_from_paste("docs", "https://example.com\n"),
            "[docs](https://example.com)",
        )

    def test_escapes_link_syntax(self):
        self.assertEqual(
            link_from_paste("array[index]", "https://example.com/a_(b)"),
            r"[array[index\]](https://example.com/a_\(b\))",
        )

    def test_rejects_plain_text_and_partial_url_matches(self):
        self.assertIsNone(link_from_paste("label", "not a URL"))
        self.assertIsNone(
            link_from_paste("label", "See https://example.com")
        )
        self.assertIsNone(link_from_paste("label", "https://example.com."))

    def test_requires_selected_text(self):
        self.assertIsNone(link_from_paste("", "https://example.com"))


class TestClipboardFormat(unittest.TestCase):
    def test_copy_normalizes_to_first_block(self):
        blocks = [Block(2, "A"), Block(3, "B"), Block(1, "C")]
        copied = copy_blocks(blocks)
        self.assertEqual(
            [(b.level, b.text) for b in copied],
            [(0, "A"), (1, "B"), (0, "C")],
        )

    def test_serializes_outline_as_markdown(self):
        blocks = [Block(1, "parent"), Block(2, "child"), Block(1, "sibling")]
        self.assertEqual(
            blocks_to_clipboard_text(blocks),
            "- parent\n  - child\n- sibling",
        )

    def test_serializes_multiline_block(self):
        self.assertEqual(
            blocks_to_clipboard_text([Block(0, "first\nsecond")]),
            "- first\n  second",
        )

    def test_serializes_code_block(self):
        block = Block(0, "print('hi')\nreturn", code_lang="python")
        self.assertEqual(
            blocks_to_clipboard_text([block]),
            "- ```python\n  print('hi')\n  return\n  ```",
        )

    def test_parses_markdown_outline(self):
        blocks = blocks_from_clipboard_text("- parent\n  - child\n- sibling")
        self.assertEqual(
            [(b.level, b.text, b.code_lang) for b in blocks],
            [(0, "parent", None), (1, "child", None), (0, "sibling", None)],
        )

    def test_accepts_four_space_and_tab_indentation(self):
        spaced = blocks_from_clipboard_text(
            "- parent\n    - child\n        - grandchild"
        )
        tabbed = blocks_from_clipboard_text(
            "- parent\n\t- child\n\t\t- grandchild"
        )
        self.assertEqual([b.level for b in spaced], [0, 1, 2])
        self.assertEqual([b.level for b in tabbed], [0, 1, 2])

    def test_parses_multiline_and_code_blocks(self):
        text = "- first\n  second\n- ```python\n  print('hi')\n  return\n  ```"
        blocks = blocks_from_clipboard_text(text)
        self.assertEqual(blocks[0].text, "first\nsecond")
        self.assertEqual(blocks[1].text, "print('hi')\nreturn")
        self.assertEqual(blocks[1].code_lang, "python")

    def test_code_clipboard_roundtrip_preserves_blank_lines(self):
        original = Block(0, "\nbody\n", code_lang="")
        [parsed] = blocks_from_clipboard_text(
            blocks_to_clipboard_text([original])
        )
        self.assertEqual(parsed.text, original.text)

    def test_plain_text_becomes_one_block(self):
        blocks = blocks_from_clipboard_text("plain\ntext")
        self.assertEqual([(b.level, b.text) for b in blocks], [(0, "plain\ntext")])

    def test_internal_copy_preserves_metadata(self):
        original = [Block(2, "code", code_lang="python", collapsed=True)]
        copied = copy_blocks(original)
        self.assertEqual(copied[0].code_lang, "python")
        self.assertTrue(copied[0].collapsed)
        self.assertIsNot(copied[0], original[0])

    def test_html_is_a_nested_semantic_list(self):
        blocks = [
            Block(0, "**parent**"),
            Block(1, "*child* with `code`"),
            Block(0, "sibling"),
        ]
        self.assertEqual(
            blocks_to_clipboard_html(blocks),
            "<ul><li><strong>parent</strong><ul>"
            "<li><em>child</em> with <code>code</code></li>"
            "</ul></li><li>sibling</li></ul>",
        )

    def test_html_includes_strikethrough_and_links(self):
        block = Block(0, "~~old~~ [docs](https://example.com?q=1&lang=en)")

        self.assertEqual(
            blocks_to_clipboard_html([block]),
            "<ul><li><del>old</del> "
            '<a href="https://example.com?q=1&amp;lang=en">docs</a>'
            "</li></ul>",
        )

    def test_html_escapes_text_and_preserves_line_breaks(self):
        block = Block(0, "<tag>\n& more")
        self.assertEqual(
            blocks_to_clipboard_html([block]),
            "<ul><li>&lt;tag&gt;<br>\n&amp; more</li></ul>",
        )

    def test_html_renders_fenced_code_semantically(self):
        block = Block(0, "if a < b:\n    pass", code_lang="python")
        self.assertEqual(
            blocks_to_clipboard_html([block]),
            '<ul><li><pre><code class="language-python">'
            "if a &lt; b:\n    pass</code></pre></li></ul>",
        )

    def test_private_payload_roundtrip_is_lossless(self):
        original = [
            Block(
                0,
                "parent",
                collapsed=True,
                properties=("id:: abc-123",),
            ),
            Block(1, "code\n", code_lang="python"),
        ]
        parsed = blocks_from_clipboard_payload(
            blocks_to_clipboard_payload(original)
        )
        self.assertEqual(
            [
                (b.level, b.text, b.code_lang, b.collapsed, b.properties)
                for b in parsed
            ],
            [
                (0, "parent", None, True, ("id:: abc-123",)),
                (1, "code\n", "python", False, ()),
            ],
        )

    def test_rejects_invalid_private_payload(self):
        self.assertIsNone(blocks_from_clipboard_payload("not json"))
        self.assertIsNone(
            blocks_from_clipboard_payload(
                '{"version":1,"blocks":[{"level":true}]}'
            )
        )


class TestClipboardOwnership(unittest.TestCase):
    def test_claims_ownership_before_publishing_targets(self):
        v = view((0, "copied"))
        v.selection = (0, 0)
        v._clipboard_targets = [object()]
        calls = []

        with (
            patch.object(
                Gtk,
                "selection_owner_set",
                side_effect=lambda *args: calls.append("owner") or True,
            ),
            patch.object(
                Gtk,
                "selection_clear_targets",
                side_effect=lambda *args: calls.append("clear"),
            ),
            patch.object(
                Gtk,
                "selection_add_targets",
                side_effect=lambda *args: calls.append("targets"),
            ),
        ):
            self.assertTrue(v._copy_block_selection(cut=False))

        self.assertEqual(calls, ["owner", "clear", "targets"])


class TestPasteInternalBlocksFromEditor(unittest.TestCase):
    def prepare(self, v, pasted):
        v.editing_block = v.blocks[-1]
        v._read_blocks_from_clipboard = lambda allow_plain_text: pasted
        v._begin_structural = lambda: "before"
        v._finish_editing = lambda: setattr(v, "editing_block", None)
        v._end_structural = lambda pre: self.assertEqual(pre, "before")
        v.queue_resize = lambda: None

    def test_replaces_empty_day_placeholder(self):
        v = view((0, ""))
        self.prepare(v, [Block(0, "parent"), Block(1, "child")])

        self.assertTrue(v._paste_internal_blocks_from_editor())

        self.assertEqual(shape(v), [(0, "parent"), (1, "child")])
        self.assertEqual(v.selection, (0, 1))

    def test_replaces_empty_block_at_its_existing_level(self):
        v = view((0, "parent"), (1, ""), (1, "sibling"))
        self.prepare(v, [Block(0, "pasted"), Block(1, "pasted child")])
        v.editing_block = v.blocks[1]

        self.assertTrue(v._paste_internal_blocks_from_editor())

        self.assertEqual(
            shape(v),
            [
                (0, "parent"),
                (1, "pasted"),
                (2, "pasted child"),
                (1, "sibling"),
            ],
        )
        self.assertEqual(v.selection, (1, 2))

    def test_inserts_after_target_subtree_at_target_level(self):
        v = view((0, "parent"), (1, "target"), (2, "existing child"))
        self.prepare(v, [Block(0, "pasted"), Block(1, "pasted child")])
        v.editing_block = v.blocks[1]

        self.assertTrue(v._paste_internal_blocks_from_editor())

        self.assertEqual(
            shape(v),
            [
                (0, "parent"),
                (1, "target"),
                (2, "existing child"),
                (1, "pasted"),
                (2, "pasted child"),
            ],
        )

    def test_leaves_external_plain_text_to_textview(self):
        v = view((0, "target"))
        self.prepare(v, None)

        self.assertFalse(v._paste_internal_blocks_from_editor())

        self.assertEqual(shape(v), [(0, "target")])
        self.assertIs(v.editing_block, v.blocks[0])
