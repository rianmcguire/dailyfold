"""Undo/redo via whole-document snapshots.

Snapshots capture the state BEFORE a change is applied. Text edits to the same
block coalesce into a single snapshot until ``break_coalesce()`` is called —
the BlocksView fires that from a pause timer and before any structural op.
"""

import copy
from dataclasses import dataclass
from typing import Optional


@dataclass
class Snapshot:
    blocks: list
    cursor: Optional[tuple]


class History:
    def __init__(self, cap=1000):
        self.cap = cap
        self.undo_stack = []
        self.redo_stack = []
        self._pending_text_block_idx = None

    def commit_structural(self, blocks, cursor):
        self._push(Snapshot(copy.deepcopy(blocks), cursor))
        self._pending_text_block_idx = None

    def commit_text(self, blocks, cursor, block_idx):
        if self._pending_text_block_idx == block_idx:
            return
        self._push(Snapshot(copy.deepcopy(blocks), cursor))
        self._pending_text_block_idx = block_idx

    def break_coalesce(self):
        self._pending_text_block_idx = None

    def undo(self, current_blocks, current_cursor):
        if not self.undo_stack:
            return None
        self.redo_stack.append(Snapshot(copy.deepcopy(current_blocks), current_cursor))
        self._pending_text_block_idx = None
        return self.undo_stack.pop()

    def redo(self, current_blocks, current_cursor):
        if not self.redo_stack:
            return None
        self.undo_stack.append(Snapshot(copy.deepcopy(current_blocks), current_cursor))
        self._pending_text_block_idx = None
        return self.redo_stack.pop()

    def _push(self, snap):
        self.undo_stack.append(snap)
        if len(self.undo_stack) > self.cap:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
