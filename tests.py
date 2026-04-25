import unittest

from app import Block, BlocksView


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

    def test_move_down_at_parent_boundary_tunnels_out(self):
        # X / A(L1)   Y(L0)  →  X   Y   A(L0)  (A adopts Y's level)
        v = view((0, "X"), (1, "A"), (0, "Y"))
        self.assertEqual(v._move_range(1, 2, +1), (2, 3))
        self.assertEqual(shape(v), [(0, "X"), (0, "Y"), (0, "A")])

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

    def test_iterative_move_up_walks_deep_block_to_root(self):
        # X / Y / Z  → step → X / Z Y  → step → Z   X / Y
        v = view((0, "X"), (1, "Y"), (2, "Z"))
        v._move_range(2, 3, -1)
        self.assertEqual(shape(v), [(0, "X"), (1, "Z"), (1, "Y")])
        v._move_range(1, 2, -1)
        self.assertEqual(shape(v), [(0, "Z"), (0, "X"), (1, "Y")])


if __name__ == "__main__":
    unittest.main()
