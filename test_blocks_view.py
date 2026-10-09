import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Pango, PangoCairo

from blocks_view import (
    BlocksView,
    _block_task_state,
    _edit_view_geometry,
    _task_markup,
    append_area_hit,
    completes_edit_activation_click,
    compute_layouts,
    resolve_body_font,
    task_label_hit,
    task_state,
    toggle_task_text,
)
from model import Block
from outline import CursorPosition, subtree_end


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


class TestFoldClick(unittest.TestCase):
    def test_double_click_event_does_not_toggle_fold_a_third_time(self):
        block = Block(0, "parent")
        block_layout = SimpleNamespace(block=block)
        toggle_fold = Mock(return_value=True)
        canvas = SimpleNamespace(queue_draw=Mock())
        view = SimpleNamespace(
            canvas=canvas,
            selection=None,
            editing_block=None,
            edit_view=None,
            _block_at_y=lambda _y: block_layout,
            _checkbox_hit=lambda _bl, _x, _y: False,
            _task_label_hit=lambda _bl, _x, _y: False,
            _bullet_hit=lambda _bl, _x, _y: True,
            _block_index=lambda _block: 0,
            _toggle_fold=toggle_fold,
            _grab_canvas_focus=Mock(),
        )

        def click(event_type):
            return BlocksView._on_click(
                view,
                canvas,
                SimpleNamespace(
                    state=0,
                    button=1,
                    type=event_type,
                    x=20,
                    y=40,
                ),
            )

        self.assertTrue(click(Gdk.EventType.BUTTON_PRESS))
        self.assertTrue(click(Gdk.EventType.BUTTON_PRESS))
        self.assertTrue(click(Gdk.EventType.DOUBLE_BUTTON_PRESS))

        self.assertEqual(toggle_fold.call_args_list, [call(0), call(0)])


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


class TestBackspaceJoin(unittest.TestCase):
    def test_selected_text_is_deleted_instead_of_joining_blocks(self):
        block = Block(0, "item 2")
        current_position = Mock(return_value=(1, 0, 0))
        begin_structural = Mock()
        view = SimpleNamespace(
            editing_block=block,
            edit_view=SimpleNamespace(
                get_buffer=lambda: SimpleNamespace(
                    get_selection_bounds=lambda: (object(), object())
                )
            ),
            _current_position=current_position,
            _begin_structural=begin_structural,
        )

        self.assertFalse(BlocksView._maybe_handle_backspace_join(view))

        current_position.assert_not_called()
        begin_structural.assert_not_called()


class TestBlockKeyboardShortcuts(unittest.TestCase):
    def test_plain_up_stays_in_block_when_a_previous_display_line_exists(self):
        probe = object()
        buffer = SimpleNamespace(
            get_insert=lambda: object(),
            get_iter_at_mark=lambda _mark: probe,
        )
        edit_view = SimpleNamespace(
            get_buffer=lambda: buffer,
            backward_display_line=Mock(return_value=True),
        )
        view = SimpleNamespace(
            editing_block=Block(0, "wrapped prose"),
            edit_view=edit_view,
            desired_col=8,
            _current_position=lambda: (0, 0, 8),
            _visible_neighbor=Mock(),
        )

        self.assertFalse(BlocksView._handle_up(view))
        edit_view.backward_display_line.assert_called_once_with(probe)
        self.assertIsNone(view.desired_col)
        view._visible_neighbor.assert_not_called()

    def test_plain_down_stays_in_block_when_a_next_display_line_exists(self):
        probe = object()
        buffer = SimpleNamespace(
            get_insert=lambda: object(),
            get_iter_at_mark=lambda _mark: probe,
        )
        edit_view = SimpleNamespace(
            get_buffer=lambda: buffer,
            forward_display_line=Mock(return_value=True),
        )
        view = SimpleNamespace(
            editing_block=Block(0, "wrapped prose"),
            edit_view=edit_view,
            desired_col=8,
            _current_position=lambda: (0, 0, 8),
            _visible_neighbor=Mock(),
        )

        self.assertFalse(BlocksView._handle_down(view))
        edit_view.forward_display_line.assert_called_once_with(probe)
        self.assertIsNone(view.desired_col)
        view._visible_neighbor.assert_not_called()

    def test_ctrl_shift_a_selects_all_from_editor_and_canvas(self):
        modifiers = (
            Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        )
        event = SimpleNamespace(state=modifiers, keyval=Gdk.KEY_a)

        for handler in (
            BlocksView._on_key_press,
            BlocksView._on_canvas_key_press,
        ):
            with self.subTest(handler=handler.__name__):
                select_all = Mock(return_value=True)
                view = SimpleNamespace(_select_all_blocks=select_all)

                self.assertTrue(handler(view, None, event))

                select_all.assert_called_once_with()

    def test_ctrl_arrows_dispatch_explicit_fold_commands(self):
        for handler in (
            BlocksView._on_key_press,
            BlocksView._on_canvas_key_press,
        ):
            for keyval, collapsed in (
                (Gdk.KEY_Up, True),
                (Gdk.KEY_Down, False),
            ):
                with self.subTest(handler=handler.__name__, keyval=keyval):
                    fold = Mock(return_value=True)
                    view = SimpleNamespace(_handle_fold_command=fold)
                    event = SimpleNamespace(
                        state=Gdk.ModifierType.CONTROL_MASK,
                        keyval=keyval,
                    )

                    self.assertTrue(handler(view, None, event))

                    fold.assert_called_once_with(collapsed=collapsed)

    def test_select_all_blocks_enters_document_wide_selection(self):
        blocks = [Block(0, "one"), Block(0, "two")]
        finish_editing = Mock()
        grab_canvas_focus = Mock()
        canvas = SimpleNamespace(queue_draw=Mock())
        view = SimpleNamespace(
            blocks=blocks,
            selection=None,
            _finish_editing=finish_editing,
            _grab_canvas_focus=grab_canvas_focus,
            canvas=canvas,
        )

        self.assertTrue(BlocksView._select_all_blocks(view))

        self.assertEqual(view.selection, (0, 1))
        finish_editing.assert_called_once_with()
        grab_canvas_focus.assert_called_once_with()
        canvas.queue_draw.assert_called_once_with()

    def test_fold_commands_apply_only_to_focused_block(self):
        blocks = [
            Block(0, "parent"),
            Block(1, "nested parent"),
            Block(2, "child"),
            Block(0, "leaf"),
        ]
        end_structural = Mock()
        view = SimpleNamespace(
            blocks=blocks,
            selection=None,
            editing_block=blocks[1],
            _block_index=lambda block: blocks.index(block),
            _subtree_end=lambda index: subtree_end(blocks, index),
            _begin_structural=lambda: "before",
            _end_structural=end_structural,
            canvas=SimpleNamespace(queue_draw=Mock()),
            queue_resize=Mock(),
        )

        self.assertTrue(
            BlocksView._handle_fold_command(view, collapsed=True)
        )
        self.assertEqual(
            [block.collapsed for block in blocks],
            [False, True, False, False],
        )

        self.assertTrue(
            BlocksView._handle_fold_command(view, collapsed=False)
        )
        self.assertEqual(
            [block.collapsed for block in blocks],
            [False, False, False, False],
        )
        self.assertEqual(
            end_structural.call_args_list,
            [call("before"), call("before")],
        )

    def test_fold_commands_do_not_apply_to_multi_block_selection(self):
        begin_structural = Mock()
        view = SimpleNamespace(
            blocks=[Block(0, "one"), Block(0, "two")],
            selection=(0, 1),
            editing_block=None,
            _begin_structural=begin_structural,
        )

        self.assertFalse(
            BlocksView._handle_fold_command(view, collapsed=True)
        )

        begin_structural.assert_not_called()


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


class TestEditingLayout(unittest.TestCase):
    def test_edit_view_geometry_includes_task_checkbox_space(self):
        layout = SimpleNamespace(
            text_x=120,
            text_width=240,
            checkbox_x=100,
            y=30,
            height=50,
        )

        self.assertEqual(_edit_view_geometry(layout), (100, 34, 260, 42))

    def test_probe_measures_real_editor_at_final_width(self):
        allocation = SimpleNamespace(width=1, height=1)
        visible = SimpleNamespace(height=1)
        allocated = []

        def size_allocate(probe):
            allocated.append(probe)
            allocation.width = probe.width
            allocation.height = probe.height
            visible.height = probe.height

        text_view = SimpleNamespace(
            get_realized=lambda: True,
            get_allocation=lambda: allocation,
            get_buffer=lambda: SimpleNamespace(get_end_iter=lambda: object()),
            get_line_yrange=lambda _end: (0, 63),
            get_visible_rect=lambda: visible,
            size_allocate=size_allocate,
        )
        layout = SimpleNamespace(
            text_x=80,
            text_width=320,
            checkbox_x=None,
            y=30,
            height=25,
        )
        view = SimpleNamespace(
            edit_view=text_view,
            _editing_view_height=None,
        )
        view._measure_edit_view_height = lambda: (
            BlocksView._measure_edit_view_height(view)
        )

        self.assertTrue(BlocksView._probe_edit_view_height(view, layout))
        self.assertEqual(allocated[0].width, 320)
        self.assertEqual(view._editing_view_height, 63)

    def test_observed_editor_height_positions_following_blocks(self):
        link = Block(
            0,
            "[docs](https://example.com/"
            + "very-long-segment-" * 12
            + ")",
        )
        following = Block(0, "following")
        blocks = [link, following]
        context = PangoCairo.FontMap.get_default().create_context()
        font = Pango.FontDescription("Sans 11")

        _, initial = compute_layouts(
            context,
            320,
            font,
            "date",
            blocks,
            editing_block=link,
        )
        _, measured = compute_layouts(
            context,
            320,
            font,
            "date",
            blocks,
            editing_block=link,
            editing_view_height=63,
        )

        self.assertEqual(measured[0].height, 63 + 8)
        self.assertGreater(measured[0].height, initial[0].height)
        self.assertEqual(
            measured[1].y - initial[1].y,
            measured[0].height - initial[0].height,
        )

    def test_measures_full_wrapped_height_from_live_text_view(self):
        end = object()
        buffer = SimpleNamespace(get_end_iter=lambda: end)
        text_view = SimpleNamespace(
            get_realized=lambda: True,
            get_allocation=lambda: SimpleNamespace(width=609, height=21),
            get_buffer=lambda: buffer,
            get_line_yrange=lambda _end: (0, 42),
            get_visible_rect=lambda: SimpleNamespace(height=21),
        )
        view = SimpleNamespace(
            edit_view=text_view,
            _editing_view_height=None,
        )

        self.assertTrue(BlocksView._measure_edit_view_height(view))
        self.assertEqual(view._editing_view_height, 42)
        self.assertFalse(BlocksView._measure_edit_view_height(view))

    def test_measurement_includes_text_view_chrome(self):
        text_view = SimpleNamespace(
            get_realized=lambda: True,
            get_allocation=lambda: SimpleNamespace(width=300, height=25),
            get_buffer=lambda: SimpleNamespace(get_end_iter=lambda: object()),
            get_line_yrange=lambda _end: (0, 42),
            get_visible_rect=lambda: SimpleNamespace(height=21),
        )
        view = SimpleNamespace(
            edit_view=text_view,
            _editing_view_height=None,
        )

        self.assertTrue(BlocksView._measure_edit_view_height(view))
        self.assertEqual(view._editing_view_height, 46)


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

    def test_inline_code_uses_palette_background(self):
        palette = SimpleNamespace(
            link=(0.1, 0.2, 0.3),
            code_bg=(0x48 / 255, 0x40 / 255, 0x29 / 255),
        )

        self.assertEqual(
            _task_markup("before `code` after", palette=palette),
            'before <span background="#484029"><tt>code</tt></span> after',
        )
