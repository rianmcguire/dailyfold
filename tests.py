import unittest
from datetime import date
from types import SimpleNamespace

from app import (
    Block,
    BlocksView,
    _block_task_state,
    _task_markup,
    blocks_from_clipboard_payload,
    blocks_from_clipboard_text,
    blocks_to_clipboard_html,
    blocks_to_clipboard_payload,
    blocks_to_clipboard_text,
    copy_blocks,
    format_journal_date,
    task_state,
    toggle_task_text,
    visible_block_indices,
)
from history import History


class _StubView:
    _block_index = BlocksView._block_index
    _parent_index = BlocksView._parent_index
    _subtree_end = BlocksView._subtree_end
    _selection_indices = BlocksView._selection_indices
    _expand_block_selection = BlocksView._expand_block_selection
    _shift_levels = BlocksView._shift_levels
    _move_range = BlocksView._move_range
    _visible_neighbor = BlocksView._visible_neighbor
    _append_area_hit = BlocksView._append_area_hit
    _completes_edit_activation_click = (
        BlocksView._completes_edit_activation_click
    )
    _insert_pasted_blocks = BlocksView._insert_pasted_blocks
    _paste_internal_blocks_from_editor = (
        BlocksView._paste_internal_blocks_from_editor
    )


def view(*levels_and_texts):
    v = _StubView()
    v.blocks = [Block(lvl, txt) for (lvl, txt) in levels_and_texts]
    v.selection = None
    v.canvas = _StubCanvas()
    return v


class _StubCanvas:
    def queue_draw(self):
        pass

    def grab_focus(self):
        pass


def levels(v):
    return [b.level for b in v.blocks]


def shape(v):
    return [(b.level, b.text) for b in v.blocks]


class TestJournalDateFormatting(unittest.TestCase):
    def test_iso_date_followed_by_weekday(self):
        self.assertEqual(
            format_journal_date(date(2026, 9, 14)),
            "2026-09-14 Monday",
        )


class TestAppendAreaHit(unittest.TestCase):
    def setUp(self):
        self.v = view((0, "last"))
        self.v.layouts = [SimpleNamespace(y=50, height=24)]
        self.v.header_layout = SimpleNamespace(y=10, height=20)
        self.v._body_row_height = lambda: 24

    def test_covers_one_row_below_last_item(self):
        self.assertTrue(self.v._append_area_hit(74))
        self.assertTrue(self.v._append_area_hit(97.999))

    def test_excludes_items_and_space_beyond_one_row(self):
        self.assertFalse(self.v._append_area_hit(73.999))
        self.assertFalse(self.v._append_area_hit(98))

    def test_starts_below_header_when_document_has_no_items(self):
        self.v.layouts = []
        self.assertFalse(self.v._append_area_hit(37.999))
        self.assertTrue(self.v._append_area_hit(38))


class TestSubtreeEnd(unittest.TestCase):
    def test_leaf(self):
        v = view((0, "A"), (0, "B"))
        self.assertEqual(v._subtree_end(0), 1)
        self.assertEqual(v._subtree_end(1), 2)

    def test_parent_with_children(self):
        v = view((0, "A"), (1, "B"), (1, "C"), (0, "D"))
        self.assertEqual(v._subtree_end(0), 3)

    def test_nested_subtree(self):
        v = view((0, "A"), (1, "B"), (2, "C"), (1, "D"), (0, "E"))
        self.assertEqual(v._subtree_end(0), 4)
        self.assertEqual(v._subtree_end(1), 3)


class TestVisibleBlockIndices(unittest.TestCase):
    def test_all_visible_without_folds(self):
        blocks = [Block(0, "A"), Block(1, "B"), Block(0, "C")]
        self.assertEqual(visible_block_indices(blocks), [0, 1, 2])

    def test_fold_hides_entire_subtree(self):
        blocks = [
            Block(0, "A", collapsed=True),
            Block(1, "B"),
            Block(2, "C"),
            Block(1, "D"),
            Block(0, "E"),
        ]
        self.assertEqual(visible_block_indices(blocks), [0, 4])

    def test_nested_fold_is_retained_when_parent_expands(self):
        blocks = [
            Block(0, "A"),
            Block(1, "B", collapsed=True),
            Block(2, "C"),
            Block(1, "D"),
        ]
        self.assertEqual(visible_block_indices(blocks), [0, 1, 3])

    def test_collapsed_leaf_does_not_hide_following_blocks(self):
        blocks = [Block(0, "A", collapsed=True), Block(0, "B")]
        self.assertEqual(visible_block_indices(blocks), [0, 1])

    def test_neighbors_skip_folded_descendants(self):
        v = view((0, "A"), (1, "B"), (2, "C"), (0, "D"))
        v.blocks[0].collapsed = True
        self.assertEqual(v._visible_neighbor(0, +1), 3)
        self.assertEqual(v._visible_neighbor(3, -1), 0)

    def test_hidden_block_has_no_visible_neighbor(self):
        v = view((0, "A"), (1, "B"), (0, "C"))
        v.blocks[0].collapsed = True
        self.assertIsNone(v._visible_neighbor(1, +1))


class TestSelectionIndices(unittest.TestCase):
    def test_no_selection(self):
        v = view((0, "A"))
        self.assertEqual(list(v._selection_indices()), [])

    def test_single_leaf(self):
        v = view((0, "A"), (0, "B"))
        v.selection = (0, 0)
        self.assertEqual(list(v._selection_indices()), [0])

    def test_single_parent_pulls_in_subtree(self):
        v = view((0, "A"), (1, "B"), (1, "C"), (0, "D"))
        v.selection = (0, 0)
        self.assertEqual(list(v._selection_indices()), [0, 1, 2])

    def test_range_extends_via_last_blocks_subtree(self):
        v = view((0, "A"), (0, "B"), (1, "C"), (0, "D"))
        v.selection = (0, 1)
        self.assertEqual(list(v._selection_indices()), [0, 1, 2])

    def test_anchor_after_head(self):
        v = view((0, "A"), (0, "B"))
        v.selection = (1, 0)
        self.assertEqual(list(v._selection_indices()), [0, 1])

    def test_cross_level_selection(self):
        # anchor on a child, head extended past parent into a shallower block
        v = view((0, "X"), (1, "Y"), (1, "Z"), (0, "W"), (0, "V"))
        v.selection = (1, 3)  # Y..W
        self.assertEqual(list(v._selection_indices()), [1, 2, 3])


class TestSelectAll(unittest.TestCase):
    def test_parent_index(self):
        v = view((0, "A"), (1, "B"), (2, "C"), (1, "D"), (0, "E"))
        self.assertEqual(v._parent_index(2), 1)
        self.assertEqual(v._parent_index(3), 0)
        self.assertIsNone(v._parent_index(4))

    def test_expands_single_block_to_parent_subtree(self):
        v = view((0, "A"), (1, "B"), (2, "C"), (1, "D"), (0, "E"))
        v.selection = (2, 2)
        self.assertTrue(v._expand_block_selection())
        self.assertEqual(v.selection, (1, 1))
        self.assertEqual(list(v._selection_indices()), [1, 2])
        self.assertTrue(v._expand_block_selection())
        self.assertEqual(v.selection, (0, 0))
        self.assertEqual(list(v._selection_indices()), [0, 1, 2, 3])

    def test_cross_sibling_selection_expands_to_common_parent(self):
        v = view((0, "A"), (1, "B"), (1, "C"), (0, "D"))
        v.selection = (1, 2)
        self.assertTrue(v._expand_block_selection())
        self.assertEqual(v.selection, (0, 0))

    def test_top_level_expands_to_whole_document(self):
        v = view((0, "A"), (1, "B"), (0, "C"), (1, "D"))
        v.selection = (0, 0)
        self.assertTrue(v._expand_block_selection())
        self.assertEqual(v.selection, (0, 3))

    def test_no_selection_is_not_handled(self):
        v = view((0, "A"))
        self.assertFalse(v._expand_block_selection())


class TestEditActivationDoubleClick(unittest.TestCase):
    def setUp(self):
        self.v = view((0, "alpha bravo"))
        self.block = self.v.blocks[0]
        self.v._edit_activation_click = (
            1000,
            50.0,
            80.0,
            self.block,
            3,
        )
        self.v._double_click_thresholds = lambda: (250, 5)

    def event(self, **changes):
        values = {
            "button": 1,
            "time": 1200,
            "x_root": 54.0,
            "y_root": 76.0,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def test_accepts_second_click_within_gtk_thresholds(self):
        self.assertTrue(
            self.v._completes_edit_activation_click(
                self.event(), self.block
            )
        )

    def test_rejects_late_or_distant_click(self):
        self.assertFalse(
            self.v._completes_edit_activation_click(
                self.event(time=1251), self.block
            )
        )
        self.assertFalse(
            self.v._completes_edit_activation_click(
                self.event(x_root=56.0), self.block
            )
        )

    def test_rejects_another_button_or_block(self):
        self.assertFalse(
            self.v._completes_edit_activation_click(
                self.event(button=3), self.block
            )
        )
        self.assertFalse(
            self.v._completes_edit_activation_click(
                self.event(), Block(0, "different")
            )
        )


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


class TestShiftLevels(unittest.TestCase):
    def test_indent_with_prev_sibling(self):
        v = view((0, "A"), (0, "B"))
        self.assertTrue(v._shift_levels(1, 2, shift=False))
        self.assertEqual(levels(v), [0, 1])

    def test_indent_no_prev_sibling_refused(self):
        v = view((0, "A"))
        self.assertFalse(v._shift_levels(0, 1, shift=False))
        self.assertEqual(levels(v), [0])

    def test_indent_subtree_shifts_uniformly(self):
        # B + its child C indent together; both gain +1
        v = view((0, "A"), (0, "B"), (1, "C"))
        self.assertTrue(v._shift_levels(1, 3, shift=False))
        self.assertEqual(levels(v), [0, 1, 2])

    def test_outdent_strips_one_level(self):
        v = view((0, "A"), (1, "B"), (2, "C"))
        self.assertTrue(v._shift_levels(1, 3, shift=True))
        self.assertEqual(levels(v), [0, 0, 1])

    def test_outdent_refused_when_any_block_at_level_zero(self):
        v = view((0, "A"), (1, "B"), (0, "C"))
        self.assertFalse(v._shift_levels(0, 3, shift=True))
        self.assertEqual(levels(v), [0, 1, 0])


class TestMoveRange(unittest.TestCase):
    def test_move_down_well_formed_preserves_levels(self):
        # X / A(L1) - B(L2 child of A) / C(L1)  →  X / C / A - B
        v = view((0, "X"), (1, "A"), (2, "B"), (1, "C"))
        self.assertEqual(v._move_range(1, 3, +1), (2, 4))
        self.assertEqual(
            shape(v),
            [(0, "X"), (1, "C"), (1, "A"), (2, "B")],
        )

    def test_move_down_single_subtree_preserves_level_becomes_child(self):
        # Single-subtree move preserves indent; A nests under Y rather than
        # outdenting to Y's level.
        v = view((0, "X"), (1, "A"), (0, "Y"))
        self.assertEqual(v._move_range(1, 2, +1), (2, 3))
        self.assertEqual(shape(v), [(0, "X"), (0, "Y"), (1, "A")])

    def test_move_down_users_example_y_becomes_child_of_v(self):
        # X / Z W Y   V   →   X / Z W   V / Y
        v = view((0, "X"), (1, "Z"), (1, "W"), (1, "Y"), (0, "V"))
        self.assertEqual(v._move_range(3, 4, +1), (4, 5))
        self.assertEqual(
            shape(v),
            [(0, "X"), (1, "Z"), (1, "W"), (0, "V"), (1, "Y")],
        )

    def test_move_down_single_subtree_with_descendants_preserves_shape(self):
        # X / Y / Z   V   →   X   V / Y / Z   (whole subtree slots under V)
        v = view((0, "X"), (1, "Y"), (2, "Z"), (0, "V"))
        self.assertEqual(v._move_range(1, 3, +1), (2, 4))
        self.assertEqual(
            shape(v),
            [(0, "X"), (0, "V"), (1, "Y"), (2, "Z")],
        )

    def test_move_down_single_block_refused_when_level_skip(self):
        # Y at L2 cannot land directly under V at L0 (would skip L1) → no-op
        v = view((0, "X"), (1, "M"), (2, "Y"), (0, "V"))
        self.assertIsNone(v._move_range(2, 3, +1))
        self.assertEqual(
            shape(v),
            [(0, "X"), (1, "M"), (2, "Y"), (0, "V")],
        )

    def test_move_up_single_block_refused_at_doc_top(self):
        # First-child Y(L1) at idx 1 would land at idx 0 with no L0 above → no-op
        v = view((0, "X"), (1, "Y"))
        self.assertIsNone(v._move_range(1, 2, -1))

    def test_move_down_cross_level_selection_drops_to_destination(self):
        # X / Y Z / W   V   →   X   V   Y Z W   (Y, Z clamp up to dest L0)
        v = view((0, "X"), (1, "Y"), (1, "Z"), (0, "W"), (0, "V"))
        self.assertEqual(v._move_range(1, 4, +1), (2, 5))
        self.assertEqual(
            shape(v),
            [(0, "X"), (0, "V"), (0, "Y"), (0, "Z"), (0, "W")],
        )

    def test_move_up_cross_level_clamps_shallower_blocks_into_destination(self):
        # X / Y Z   W   V   →   X / Z W Y   V   (W rises L0→L1 to clamp)
        v = view((0, "X"), (1, "Y"), (1, "Z"), (0, "W"), (0, "V"))
        self.assertEqual(v._move_range(2, 4, -1), (1, 3))
        self.assertEqual(
            shape(v),
            [(0, "X"), (1, "Z"), (1, "W"), (1, "Y"), (0, "V")],
        )

    def test_move_up_at_top_is_no_op(self):
        v = view((0, "A"), (0, "B"))
        self.assertIsNone(v._move_range(0, 1, -1))

    def test_move_down_at_bottom_is_no_op(self):
        v = view((0, "A"), (0, "B"))
        self.assertIsNone(v._move_range(1, 2, +1))

    def test_move_up_single_subtree_refused_when_level_skip(self):
        # Z(L2) move-up would land between X(L0) and Y(L1) — skip L0→L2 → no-op.
        # User must Shift+Tab Z first to outdent, then move.
        v = view((0, "X"), (1, "Y"), (2, "Z"))
        self.assertIsNone(v._move_range(2, 3, -1))
        self.assertEqual(shape(v), [(0, "X"), (1, "Y"), (2, "Z")])

    def test_move_down_multi_block_uses_clamp_rule(self):
        # Range [1..4) covers A, B, C — but C is NOT in A's subtree, so this is
        # a multi-block range and the clamp rule (not preserve) applies.
        v = view((0, "X"), (1, "A"), (2, "B"), (0, "C"), (0, "D"))
        self.assertEqual(v._move_range(1, 4, +1), (2, 5))
        self.assertEqual(
            shape(v),
            [(0, "X"), (0, "D"), (0, "A"), (1, "B"), (0, "C")],
        )


def bs(*texts):
    return [Block(0, t) for t in texts]


class TestHistory(unittest.TestCase):
    def test_text_edits_same_block_coalesce(self):
        h = History()
        h.commit_text(bs("a"), None, 0)
        h.commit_text(bs("ab"), None, 0)
        h.commit_text(bs("abc"), None, 0)
        self.assertEqual(len(h.undo_stack), 1)
        self.assertEqual(h.undo_stack[0].blocks[0].text, "a")

    def test_text_edits_different_blocks_dont_coalesce(self):
        h = History()
        h.commit_text(bs("a", "x"), None, 0)
        h.commit_text(bs("ab", "x"), None, 0)
        h.commit_text(bs("ab", "y"), None, 1)
        self.assertEqual(len(h.undo_stack), 2)

    def test_structural_breaks_coalesce(self):
        h = History()
        h.commit_text(bs("a"), None, 0)
        h.commit_structural(bs("a"), None)
        h.commit_text(bs("ab"), None, 0)
        self.assertEqual(len(h.undo_stack), 3)

    def test_break_coalesce_starts_fresh_run(self):
        h = History()
        h.commit_text(bs("a"), None, 0)
        h.break_coalesce()
        h.commit_text(bs("ab"), None, 0)
        self.assertEqual(len(h.undo_stack), 2)

    def test_undo_redo_roundtrip(self):
        h = History()
        h.commit_structural(bs("a"), None)
        snap = h.undo(bs("ab"), None)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.blocks[0].text, "a")
        snap = h.redo(bs("a"), None)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.blocks[0].text, "ab")

    def test_new_commit_clears_redo(self):
        h = History()
        h.commit_structural(bs("a"), None)
        h.undo(bs("ab"), None)
        self.assertEqual(len(h.redo_stack), 1)
        h.commit_structural(bs("c"), None)
        self.assertEqual(len(h.redo_stack), 0)

    def test_snapshot_isolated_from_later_mutation(self):
        h = History()
        live = bs("a")
        h.commit_structural(live, None)
        live[0].text = "MUTATED"
        self.assertEqual(h.undo_stack[0].blocks[0].text, "a")

    def test_snapshot_preserves_fold_state(self):
        h = History()
        blocks = [Block(0, "parent", collapsed=True), Block(1, "child")]
        h.commit_structural(blocks, None)
        blocks[0].collapsed = False
        self.assertTrue(h.undo_stack[0].blocks[0].collapsed)

    def test_cap_drops_oldest(self):
        h = History(cap=3)
        for i in range(5):
            h.commit_structural(bs(str(i)), None)
        self.assertEqual(len(h.undo_stack), 3)
        self.assertEqual(h.undo_stack[0].blocks[0].text, "2")
        self.assertEqual(h.undo_stack[-1].blocks[0].text, "4")

    def test_undo_empty_returns_none(self):
        self.assertIsNone(History().undo([], None))

    def test_redo_empty_returns_none(self):
        self.assertIsNone(History().redo([], None))

    def test_undo_after_text_run_then_more_text(self):
        # type "a", "b", "c" in block 0; undo; type "x" — redo should be cleared
        h = History()
        h.commit_text(bs("a"), None, 0)
        h.commit_text(bs("ab"), None, 0)
        h.undo(bs("abc"), None)
        h.commit_text(bs("ax"), None, 0)
        self.assertEqual(len(h.redo_stack), 0)


class TestCodeBlocks(unittest.TestCase):
    def test_default_code_lang_is_none(self):
        b = Block(0, "hi")
        self.assertIsNone(b.code_lang)

    def test_code_block_survives_structural_snapshot_copy(self):
        v = view((0, "outer"))
        v.blocks.append(Block(0, "def foo():\n    pass", code_lang="python"))
        copies = [Block(b.level, b.text, b.code_lang) for b in v.blocks]
        v.blocks[1].text = "MUTATED"
        v.blocks[1].code_lang = "rust"
        self.assertEqual(copies[1].text, "def foo():\n    pass")
        self.assertEqual(copies[1].code_lang, "python")

    def test_history_deepcopy_preserves_code_lang(self):
        from copy import deepcopy
        blocks = [Block(0, "code body", code_lang="python")]
        snap = deepcopy(blocks)
        blocks[0].code_lang = "rust"
        self.assertEqual(snap[0].code_lang, "python")

    def test_indent_works_on_code_block(self):
        v = view((0, "parent"))
        v.blocks.append(Block(0, "code", code_lang=""))
        ok = v._shift_levels(1, 2, shift=False)
        self.assertTrue(ok)
        self.assertEqual(v.blocks[1].level, 1)
        self.assertEqual(v.blocks[1].code_lang, "")

    def test_move_range_keeps_code_lang(self):
        v = _StubView()
        v.blocks = [
            Block(0, "a"),
            Block(0, "code", code_lang="python"),
        ]
        v.selection = None
        v._move_range(1, 2, direction=-1)
        self.assertEqual(v.blocks[0].text, "code")
        self.assertEqual(v.blocks[0].code_lang, "python")
        self.assertEqual(v.blocks[1].text, "a")
        self.assertIsNone(v.blocks[1].code_lang)


class TestTasks(unittest.TestCase):
    def test_recognizes_exact_logseq_prefixes(self):
        self.assertEqual(task_state("TODO write tests"), "TODO")
        self.assertEqual(task_state("DONE write tests"), "DONE")
        self.assertIsNone(task_state("TODO"))
        self.assertIsNone(task_state("todo write tests"))
        self.assertIsNone(task_state("prefix TODO write tests"))

    def test_toggle_preserves_everything_after_keyword(self):
        self.assertEqual(toggle_task_text("TODO **ship** it"), "DONE **ship** it")
        self.assertEqual(toggle_task_text("DONE **ship** it"), "TODO **ship** it")
        self.assertIsNone(toggle_task_text("ship it"))

    def test_code_blocks_do_not_become_tasks(self):
        self.assertIsNone(_block_task_state(Block(0, "TODO example", code_lang="")))

    def test_task_markup_keeps_prefix_and_inline_markdown(self):
        todo = _task_markup("TODO **ship** it")
        done = _task_markup("DONE **ship** it")
        self.assertIn(">TODO</span> ", todo)
        self.assertIn("<b>ship</b>", todo)
        self.assertIn(">DONE</span> ", done)
        self.assertIn('strikethrough="true"', done)
        self.assertIn("<b>ship</b>", done)


if __name__ == "__main__":
    unittest.main()
