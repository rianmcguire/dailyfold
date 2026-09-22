import unittest

from model import Block
from outline import (
    CursorPosition,
    delete_empty_forward,
    delete_range,
    expand_selection,
    insert_blocks,
    join_with_previous,
    move_range,
    parent_index,
    selection_indices,
    shift_levels,
    split_block,
    subtree_end,
    visible_block_indices,
    visible_neighbor,
)


class OutlineHarness:
    def __init__(self, blocks):
        self.blocks = blocks
        self.selection = None

    def _subtree_end(self, block_idx):
        return subtree_end(self.blocks, block_idx)

    def _visible_neighbor(self, block_idx, direction):
        return visible_neighbor(self.blocks, block_idx, direction)

    def _selection_indices(self):
        return selection_indices(self.blocks, self.selection)

    def _parent_index(self, block_idx):
        return parent_index(self.blocks, block_idx)

    def _expand_block_selection(self):
        expanded = expand_selection(self.blocks, self.selection)
        if expanded is None:
            return False
        self.selection = expanded
        return True

    def _shift_levels(self, start, end, shift):
        return shift_levels(self.blocks, start, end, shift)

    def _move_range(self, start, end, direction):
        return move_range(self.blocks, start, end, direction)


def view(*levels_and_texts):
    return OutlineHarness(
        [Block(level, text) for level, text in levels_and_texts]
    )


def levels(view_under_test):
    return [block.level for block in view_under_test.blocks]


def shape(view_under_test):
    return [
        (block.level, block.text) for block in view_under_test.blocks
    ]


def block_shape(blocks):
    return [
        (
            block.level,
            block.text,
            block.code_lang,
            block.collapsed,
            block.properties,
        )
        for block in blocks
    ]


class TestStructuralEditing(unittest.TestCase):
    def test_split_before_text_keeps_existing_children_with_right_block(self):
        blocks = [
            Block(0, "a"),
            Block(1, "b"),
            Block(2, "c"),
            Block(2, "d"),
        ]

        cursor = split_block(blocks, 1, 0)

        self.assertEqual(
            [(block.level, block.text) for block in blocks],
            [(0, "a"), (1, ""), (1, "b"), (2, "c"), (2, "d")],
        )
        self.assertEqual(cursor, CursorPosition(1))

    def test_split_at_end_of_parent_creates_first_child(self):
        blocks = [Block(0, "parent"), Block(1, "child")]

        cursor = split_block(blocks, 0, len("parent"))

        self.assertEqual(
            [(block.level, block.text) for block in blocks],
            [(0, "parent"), (1, ""), (1, "child")],
        )
        self.assertEqual(cursor, CursorPosition(1))

    def test_split_code_block_preserves_language_on_right_side(self):
        blocks = [Block(0, "left\nright", code_lang="python")]

        cursor = split_block(blocks, 0, 5)

        self.assertEqual(
            [(block.text, block.code_lang) for block in blocks],
            [("left\n", "python"), ("right", "python")],
        )
        self.assertEqual(cursor, CursorPosition(1))

    def test_join_rebases_descendants_and_returns_join_position(self):
        blocks = [
            Block(0, "previous"),
            Block(1, "current"),
            Block(2, "child"),
        ]

        cursor = join_with_previous(blocks, 1, 0)

        self.assertEqual(
            [(block.level, block.text) for block in blocks],
            [(0, "previouscurrent"), (1, "child")],
        )
        self.assertEqual(cursor, CursorPosition(0, 0, len("previous")))

    def test_delete_empty_forward_promotes_descendants(self):
        blocks = [
            Block(0, "parent"),
            Block(1, ""),
            Block(2, "child"),
            Block(1, "sibling"),
        ]

        cursor = delete_empty_forward(blocks, 1)

        self.assertEqual(
            [(block.level, block.text) for block in blocks],
            [(0, "parent"), (1, "child"), (1, "sibling")],
        )
        self.assertEqual(cursor, CursorPosition(1))

    def test_delete_range_focuses_end_of_previous_block(self):
        blocks = [Block(0, "first\nline"), Block(0, "second")]

        cursor = delete_range(blocks, 1, 2)

        self.assertEqual(cursor, CursorPosition(0, 1, len("line")))

    def test_insert_blocks_rebases_and_copies_metadata(self):
        blocks = [Block(0, "parent")]
        pasted = [
            Block(0, "pasted", collapsed=True, properties=("id:: one",)),
            Block(1, "child", code_lang="python"),
        ]

        selection = insert_blocks(blocks, pasted, 1, 1)

        self.assertEqual(selection, (1, 2))
        self.assertEqual(
            block_shape(blocks),
            [
                (0, "parent", None, False, ()),
                (1, "pasted", None, True, ("id:: one",)),
                (2, "child", "python", False, ()),
            ],
        )
        self.assertIsNot(blocks[1], pasted[0])

    def test_indent_preserves_code_language(self):
        blocks = [Block(0, "parent"), Block(0, "code", code_lang="")]

        self.assertTrue(shift_levels(blocks, 1, 2, outdent=False))

        self.assertEqual(blocks[1].level, 1)
        self.assertEqual(blocks[1].code_lang, "")

    def test_move_preserves_code_language(self):
        blocks = [
            Block(0, "a"),
            Block(0, "code", code_lang="python"),
        ]

        self.assertEqual(move_range(blocks, 1, 2, direction=-1), (0, 1))

        self.assertEqual(blocks[0].text, "code")
        self.assertEqual(blocks[0].code_lang, "python")
        self.assertEqual(blocks[1].text, "a")
        self.assertIsNone(blocks[1].code_lang)


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
