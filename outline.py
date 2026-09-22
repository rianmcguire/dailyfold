"""Pure outline traversal and structural editing operations."""


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
