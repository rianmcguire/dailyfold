import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Pango

from blocks_view import (
    BlocksView,
    _block_task_state,
    _task_markup,
    append_area_hit,
    completes_edit_activation_click,
    resolve_body_font,
    task_label_hit,
    task_state,
    toggle_task_text,
)
from model import Block
from outline import CursorPosition


class TestCanvasFocus(unittest.TestCase):
    def test_preserves_scroll_position_when_focus_scrolls_canvas_to_top(self):
        adjustment = Mock()
        adjustment.get_value.return_value = 420
        canvas = Mock()
        canvas.grab_focus.side_effect = lambda: adjustment.set_value(0)
        scroller = SimpleNamespace(get_vadjustment=lambda: adjustment)
        view = SimpleNamespace(
            canvas=canvas,
            get_ancestor=lambda _widget_type: scroller,
        )

        BlocksView._grab_canvas_focus(view)

        self.assertEqual(
            adjustment.set_value.call_args_list,
            [call(0), call(420)],
        )

    def test_grabs_focus_without_a_scroller(self):
        canvas = Mock()
        view = SimpleNamespace(
            canvas=canvas,
            get_ancestor=lambda _widget_type: None,
        )

        BlocksView._grab_canvas_focus(view)

        canvas.grab_focus.assert_called_once_with()


class TestAppendAreaHit(unittest.TestCase):
    def setUp(self):
        self.blocks = [Block(0, "last")]
        self.layouts = [SimpleNamespace(y=50, height=24)]
        self.header_layout = SimpleNamespace(y=10, height=20)

    def hit(self, y):
        return append_area_hit(
            self.blocks,
            self.layouts,
            self.header_layout,
            24,
            y,
        )

    def test_covers_one_row_below_last_item(self):
        self.assertTrue(self.hit(74))
        self.assertTrue(self.hit(97.999))

    def test_excludes_items_and_space_beyond_one_row(self):
        self.assertFalse(self.hit(73.999))
        self.assertFalse(self.hit(98))

    def test_disabled_when_document_ends_in_empty_top_level_block(self):
        self.blocks[-1].text = ""
        self.assertFalse(self.hit(74))

    def test_enabled_when_document_ends_in_empty_indented_block(self):
        self.blocks[-1].level = 1
        self.blocks[-1].text = ""
        self.assertTrue(self.hit(74))

    def test_starts_below_header_when_document_has_no_items(self):
        self.blocks = []
        self.layouts = []
        self.assertFalse(self.hit(37.999))
        self.assertTrue(self.hit(38))


class TestTaskLabelHit(unittest.TestCase):
    def setUp(self):
        self.bl = SimpleNamespace(
            text_x=70,
            y=50,
            task_label_width=42,
        )

    def test_hits_colored_label_on_first_row(self):
        self.assertTrue(task_label_hit(self.bl, 24, 70, 50))
        self.assertTrue(task_label_hit(self.bl, 24, 111.999, 73.999))

    def test_excludes_body_text_and_other_rows(self):
        self.assertFalse(task_label_hit(self.bl, 24, 112, 60))
        self.assertFalse(task_label_hit(self.bl, 24, 80, 74))

    def test_non_task_layout_has_no_label_target(self):
        self.bl.task_label_width = None
        self.assertFalse(task_label_hit(self.bl, 24, 80, 60))


class TestControlClickLink(unittest.TestCase):
    def test_opens_link_without_entering_editor(self):
        block = Block(0, "[docs](https://example.com)")
        block_layout = SimpleNamespace(block=block)
        finished = []
        opened = []
        canvas = Mock()
        view = SimpleNamespace(
            canvas=canvas,
            selection=(0, 0),
            _block_at_y=lambda _y: block_layout,
            _link_url_from_click=(
                lambda _target, _x, _y: "https://example.com"
            ),
            _finish_editing=lambda: finished.append(True),
            _open_link=lambda url, timestamp: opened.append((url, timestamp)),
        )
        event = SimpleNamespace(
            state=Gdk.ModifierType.CONTROL_MASK,
            button=1,
            type=Gdk.EventType.BUTTON_PRESS,
            x=25,
            y=40,
            time=1234,
        )

        self.assertTrue(BlocksView._on_click(view, canvas, event))

        self.assertEqual(finished, [True])
        self.assertIsNone(view.selection)
        self.assertEqual(opened, [("https://example.com", 1234)])


class TestEditActivationDoubleClick(unittest.TestCase):
    def setUp(self):
        self.block = Block(0, "alpha bravo")
        self.first_click = (
            1000,
            50.0,
            80.0,
            self.block,
            3,
        )

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
            completes_edit_activation_click(
                self.first_click, self.event(), self.block, 250, 5
            )
        )

    def test_rejects_late_or_distant_click(self):
        self.assertFalse(
            completes_edit_activation_click(
                self.first_click,
                self.event(time=1251),
                self.block,
                250,
                5,
            )
        )
        self.assertFalse(
            completes_edit_activation_click(
                self.first_click,
                self.event(x_root=56.0),
                self.block,
                250,
                5,
            )
        )

    def test_rejects_another_button_or_block(self):
        self.assertFalse(
            completes_edit_activation_click(
                self.first_click,
                self.event(button=3),
                self.block,
                250,
                5,
            )
        )
        self.assertFalse(
            completes_edit_activation_click(
                self.first_click,
                self.event(),
                Block(0, "different"),
                250,
                5,
            )
        )


class TestEnter(unittest.TestCase):
    def test_moves_to_cursor_returned_by_split(self):
        block = Block(0, "text")
        buffer = SimpleNamespace(
            get_insert=lambda: None,
            get_iter_at_mark=lambda _mark: SimpleNamespace(
                get_offset=lambda: 0
            ),
            set_text=Mock(),
        )
        moved = []
        view = SimpleNamespace(
            blocks=[block],
            editing_block=block,
            edit_view=SimpleNamespace(get_buffer=lambda: buffer),
            _block_index=lambda _block: 0,
            _subtree_end=lambda _index: 1,
            _begin_structural=lambda: "before",
            _end_structural=Mock(),
            _move_to_cursor=moved.append,
            _suppress_text_snapshot=False,
        )
        cursor = CursorPosition(0)

        with patch("blocks_view.split_block", return_value=cursor) as split:
            self.assertTrue(BlocksView._handle_enter(view))

        split.assert_called_once_with(view.blocks, 0, 0)
        view._end_structural.assert_called_once_with("before")
        self.assertEqual(moved, [cursor])


class TestDeleteEmpty(unittest.TestCase):
    def test_moves_to_cursor_returned_by_delete(self):
        blocks = [Block(0, ""), Block(0, "next")]
        moved = []
        view = SimpleNamespace(
            blocks=blocks,
            editing_block=blocks[0],
            _block_index=lambda _block: 0,
            _begin_structural=lambda: "before",
            _end_structural=Mock(),
            _move_to_cursor=moved.append,
        )
        cursor = CursorPosition(0)

        with patch(
            "blocks_view.delete_empty_forward", return_value=cursor
        ) as delete:
            self.assertTrue(BlocksView._maybe_handle_delete_empty(view))

        delete.assert_called_once_with(blocks, 0)
        view._end_structural.assert_called_once_with("before")
        self.assertEqual(moved, [cursor])


class TestReorderVisibility(unittest.TestCase):
    def test_reveals_edited_block_after_reorder(self):
        block = Block(0, "moving")
        view = SimpleNamespace(
            blocks=[block, Block(0, "other")],
            editing_block=block,
            _block_index=lambda _block: 0,
            _subtree_end=lambda _index: 1,
            _begin_structural=lambda: "before",
            _move_range=lambda _start, _end, _direction: (1, 2),
            _end_structural=Mock(),
            canvas=SimpleNamespace(queue_draw=Mock()),
            queue_resize=Mock(),
            ensure_block_visible=Mock(),
        )

        self.assertTrue(BlocksView._handle_move_block_in_edit(view, +1))

        view.ensure_block_visible.assert_called_once_with(block)

    def test_reveals_selection_head_after_reorder(self):
        blocks = [Block(0, text) for text in ("first", "moving", "last")]
        view = SimpleNamespace(
            blocks=blocks,
            selection=(1, 1),
            _selection_indices=lambda: [1],
            _begin_structural=lambda: "before",
            _move_range=lambda _start, _end, _direction: (2, 3),
            _end_structural=Mock(),
            canvas=SimpleNamespace(queue_draw=Mock()),
            queue_resize=Mock(),
            ensure_block_visible=Mock(),
        )

        self.assertTrue(BlocksView._handle_move_selection(view, +1))

        self.assertEqual(view.selection, (2, 2))
        view.ensure_block_visible.assert_called_once_with(blocks[2])


class TestContentFont(unittest.TestCase):
    def test_body_font_is_ten_percent_larger_than_widget_default(self):
        default_font = Pango.FontDescription("Sans 10")
        widget = SimpleNamespace(
            get_pango_context=lambda: SimpleNamespace(
                get_font_description=lambda: default_font
            )
        )

        body_font = resolve_body_font(widget)

        self.assertEqual(body_font.get_size(), 11 * Pango.SCALE)
        self.assertEqual(default_font.get_size(), 10 * Pango.SCALE)


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
        self.assertIn(f">\u2009TODO\u2009</span> ", todo)
        self.assertIn('foreground="#045591"', todo)
        self.assertIn('background="#e1f0f7"', todo)
        self.assertIn("<b>ship</b>", todo)
        self.assertIn(f">\u2009DONE\u2009</span> ", done)
        self.assertIn('foreground="#2f6f44"', done)
        self.assertIn('background="#def3e5"', done)
        self.assertIn('strikethrough="true"', done)
        self.assertIn("<b>ship</b>", done)
