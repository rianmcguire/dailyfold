"""Shared lightweight stand-ins for testing the GTK block editor."""

from blocks_view import BlocksView
from model import Block


class StubView:
    _grab_canvas_focus = BlocksView._grab_canvas_focus
    _on_click = BlocksView._on_click
    _block_index = BlocksView._block_index
    _parent_index = BlocksView._parent_index
    _subtree_end = BlocksView._subtree_end
    _selection_indices = BlocksView._selection_indices
    _expand_block_selection = BlocksView._expand_block_selection
    _shift_levels = BlocksView._shift_levels
    _move_range = BlocksView._move_range
    _visible_neighbor = BlocksView._visible_neighbor
    _append_area_hit = BlocksView._append_area_hit
    _task_label_hit = BlocksView._task_label_hit
    _completes_edit_activation_click = BlocksView._completes_edit_activation_click
    _insert_pasted_blocks = BlocksView._insert_pasted_blocks
    _maybe_handle_delete_empty = BlocksView._maybe_handle_delete_empty
    _paste_internal_blocks_from_editor = (
        BlocksView._paste_internal_blocks_from_editor
    )
    _copy_block_selection = BlocksView._copy_block_selection
    _handle_enter = BlocksView._handle_enter

    def get_ancestor(self, widget_type):
        return None


class StubCanvas:
    def __init__(self):
        self.focus_callback = None

    def queue_draw(self):
        pass

    def grab_focus(self):
        if self.focus_callback is not None:
            self.focus_callback()


class StubAdjustment:
    def __init__(self, value):
        self.value = value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


class StubScroller:
    def __init__(self, adjustment):
        self.adjustment = adjustment

    def get_vadjustment(self):
        return self.adjustment


class StubPangoContext:
    def __init__(self, font):
        self.font = font

    def get_font_description(self):
        return self.font


class StubFontWidget:
    def __init__(self, font):
        self.context = StubPangoContext(font)

    def get_pango_context(self):
        return self.context


def view(*levels_and_texts):
    result = StubView()
    result.blocks = [Block(level, text) for level, text in levels_and_texts]
    result.selection = None
    result.canvas = StubCanvas()
    return result


def levels(view_under_test):
    return [block.level for block in view_under_test.blocks]


def shape(view_under_test):
    return [
        (block.level, block.text) for block in view_under_test.blocks
    ]
