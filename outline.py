"""Pure outline traversal and structural editing operations."""

from dataclasses import dataclass

from model import Block


@dataclass(frozen=True)
class CursorPosition:
    block_index: int
    line: int = 0
    column: int = 0


def visible_neighbor(blocks, block_idx, direction):
    """Return the adjacent visible block index in *direction*."""
    visible = visible_block_indices(blocks)
    try:
        position = visible.index(block_idx)
    except ValueError:
        return None
    target = position + direction
    if 0 <= target < len(visible):
        return visible[target]
    return None


def visible_block_indices(blocks):
    """Return the document indices that are visible after applying folds."""
    visible = []
    hidden_below_level = None
    for i, block in enumerate(blocks):
        if hidden_below_level is not None:
            if block.level > hidden_below_level:
                continue
            hidden_below_level = None
        visible.append(i)
        if block.collapsed:
            hidden_below_level = block.level
    return visible


def subtree_end(blocks, block_idx):
    """Return the exclusive end index of a block and its descendants."""
    level = blocks[block_idx].level
    end = block_idx + 1
    while end < len(blocks) and blocks[end].level > level:
        end += 1
    return end


def parent_index(blocks, block_idx):
    """Return the nearest ancestor index, or ``None`` for a root block."""
    level = blocks[block_idx].level
    for candidate in range(block_idx - 1, -1, -1):
        if blocks[candidate].level < level:
            return candidate
    return None


def shift_levels(blocks, start, end, outdent):
    """Indent or outdent a contiguous block range in place."""
    if outdent:
        if any(blocks[i].level < 1 for i in range(start, end)):
            return False
        delta = -1
    else:
        previous_sibling = None
        for i in range(start - 1, -1, -1):
            if blocks[i].level < blocks[start].level:
                break
            if blocks[i].level == blocks[start].level:
                previous_sibling = i
                break
        if previous_sibling is None:
            return False
        delta = 1
    for i in range(start, end):
        blocks[i].level += delta
    return True


def move_range(blocks, start, end, direction):
    """Move a block range up or down and return its new bounds."""
    if direction > 0:
        if end >= len(blocks):
            return None
        target_start = end
        target_end = subtree_end(blocks, end)
        dest_level = blocks[end].level
    else:
        if start == 0:
            return None
        target_start = start - 1
        while target_start > 0 and blocks[target_start].level > blocks[start].level:
            target_start -= 1
        if blocks[target_start].level > blocks[start].level:
            return None
        target_end = start
        dest_level = blocks[target_start].level

    if end == subtree_end(blocks, start):
        if direction > 0:
            prev_level = blocks[target_end - 1].level
        else:
            prev_level = blocks[target_start - 1].level if target_start > 0 else -1
        if blocks[start].level > prev_level + 1:
            return None
    else:
        delta = dest_level - blocks[start].level
        for i in range(start, end):
            blocks[i].level = max(blocks[i].level + delta, dest_level)

    moved = blocks[start:end]
    target = blocks[target_start:target_end]
    if direction > 0:
        blocks[start:target_end] = target + moved
        new_start = start + len(target)
    else:
        blocks[target_start:end] = moved + target
        new_start = target_start
    return (new_start, new_start + len(moved))


def selection_indices(blocks, selection):
    """Return a selected range expanded to include descendant blocks."""
    if selection is None:
        return range(0, 0)
    anchor, head = selection
    lo = min(anchor, head)
    hi = max(anchor, head)
    end = hi + 1
    for i in range(lo, hi + 1):
        end = max(end, subtree_end(blocks, i))
    return range(lo, end)


def expand_selection(blocks, selection):
    """Expand a selection to its containing subtree or the whole outline."""
    if selection is None or not blocks:
        return None

    indices = selection_indices(blocks, selection)
    start, end = indices[0], indices[-1] + 1
    parent = parent_index(blocks, start)
    while parent is not None and subtree_end(blocks, parent) < end:
        parent = parent_index(blocks, parent)
    if parent is not None:
        return (parent, parent)
    return (0, len(blocks) - 1)


def split_block(blocks, block_idx, offset):
    """Split a block at *offset* and return the desired editor cursor."""
    block = blocks[block_idx]
    original_text = block.text
    left = original_text[:offset]
    right = original_text[offset:]
    has_children = subtree_end(blocks, block_idx) > block_idx + 1

    if has_children and block.collapsed:
        block.collapsed = False
    new_level = block.level + 1 if has_children and not right else block.level
    new_language = (
        block.code_lang
        if block.code_lang is not None and offset < len(original_text)
        else None
    )
    block.text = left
    blocks.insert(
        block_idx + 1,
        Block(level=new_level, text=right, code_lang=new_language),
    )

    focus_index = block_idx if not left and right else block_idx + 1
    return CursorPosition(focus_index)


def join_with_previous(blocks, block_idx, previous_idx):
    """Join a block into a preceding visible block and preserve descendants."""
    previous = blocks[previous_idx]
    block = blocks[block_idx]
    previous_lines = previous.text.split("\n")
    cursor = CursorPosition(
        previous_idx,
        len(previous_lines) - 1,
        len(previous_lines[-1]),
    )

    end = subtree_end(blocks, block_idx)
    level_delta = previous.level - block.level
    for i in range(block_idx + 1, end):
        blocks[i].level += level_delta
    previous.text += block.text
    del blocks[block_idx]
    return cursor


def delete_empty_forward(blocks, block_idx):
    """Delete an empty block and promote descendants toward the next block."""
    if blocks[block_idx].text or block_idx + 1 >= len(blocks):
        return None

    end = subtree_end(blocks, block_idx)
    for i in range(block_idx + 1, end):
        blocks[i].level -= 1
    del blocks[block_idx]
    return CursorPosition(block_idx)


def delete_range(blocks, start, end):
    """Delete a block range and return the nearest remaining cursor."""
    del blocks[start:end]
    if not blocks:
        return None
    if start == 0:
        return CursorPosition(0)

    target_idx = start - 1
    target_lines = blocks[target_idx].text.split("\n")
    return CursorPosition(
        target_idx,
        len(target_lines) - 1,
        len(target_lines[-1]),
    )


def insert_blocks(blocks, inserted_blocks, insert_idx, destination_level):
    """Insert normalized blocks rebased to *destination_level*."""
    inserted = [
        Block(
            block.level + destination_level,
            block.text,
            block.code_lang,
            block.collapsed,
            block.properties,
        )
        for block in inserted_blocks
    ]
    blocks[insert_idx:insert_idx] = inserted
    return (insert_idx, insert_idx + len(inserted) - 1)
