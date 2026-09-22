import unittest

from history import History
from model import Block


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

