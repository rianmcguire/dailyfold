import unittest

from app import (
    Block,
    BlocksView,
    _block_task_state,
    _task_markup,
    task_state,
    toggle_task_text,
)
from history import History


class _StubView:
    _block_index = BlocksView._block_index
    _subtree_end = BlocksView._subtree_end
    _selection_indices = BlocksView._selection_indices
    _shift_levels = BlocksView._shift_levels
    _move_range = BlocksView._move_range


def view(*levels_and_texts):
    v = _StubView()
    v.blocks = [Block(lvl, txt) for (lvl, txt) in levels_and_texts]
    v.selection = None
    return v


def levels(v):
    return [b.level for b in v.blocks]


def shape(v):
    return [(b.level, b.text) for b in v.blocks]


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
