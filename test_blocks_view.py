import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gtk, Pango

from _app_test_support import (
    StubAdjustment as _StubAdjustment,
    StubFontWidget as _StubFontWidget,
    StubScroller as _StubScroller,
    StubView as _StubView,
    shape,
    view,
)
from blocks_view import (
    _block_task_state,
    _task_markup,
    resolve_body_font,
    task_state,
    toggle_task_text,
)
from model import Block


class TestCanvasFocus(unittest.TestCase):
    def test_preserves_scroll_position_when_focus_scrolls_canvas_to_top(self):
        v = view((0, "block"))
        adjustment = _StubAdjustment(420)
        scroller = _StubScroller(adjustment)
        v.get_ancestor = lambda widget_type: scroller
        v.canvas.focus_callback = lambda: adjustment.set_value(0)

        v._grab_canvas_focus()

        self.assertEqual(adjustment.get_value(), 420)

    def test_grabs_focus_without_a_scroller(self):
        v = view((0, "block"))
        focused = []
        v.get_ancestor = lambda widget_type: None
        v.canvas.focus_callback = lambda: focused.append(True)

        v._grab_canvas_focus()

        self.assertEqual(focused, [True])


class TestAppendAreaHit(unittest.TestCase):
    def setUp(self):
        self.v = view((0, "last"))
        self.v.layouts = [SimpleNamespace(y=50, height=24)]
        self.v.header_layout = SimpleNamespace(y=10, height=20)
        self.v._body_row_height = lambda: 24

    def test_covers_one_row_below_last_item(self):
        self.assertTrue(self.v._append_area_hit(74))
        self.assertTrue(self.v._append_area_hit(97.999))

    def test_excludes_items_and_space_beyond_one_row(self):
        self.assertFalse(self.v._append_area_hit(73.999))
        self.assertFalse(self.v._append_area_hit(98))

    def test_disabled_when_document_ends_in_empty_top_level_block(self):
        self.v.blocks[-1].text = ""
        self.assertFalse(self.v._append_area_hit(74))

    def test_enabled_when_document_ends_in_empty_indented_block(self):
        self.v.blocks[-1].level = 1
        self.v.blocks[-1].text = ""
        self.assertTrue(self.v._append_area_hit(74))

    def test_starts_below_header_when_document_has_no_items(self):
        self.v.blocks = []
        self.v.layouts = []
        self.assertFalse(self.v._append_area_hit(37.999))
        self.assertTrue(self.v._append_area_hit(38))


class TestTaskLabelHit(unittest.TestCase):
    def setUp(self):
        self.v = view((0, "TODO task"))
        self.v._body_row_height = lambda: 24
        self.bl = SimpleNamespace(
            text_x=70,
            y=50,
            task_label_width=42,
        )

    def test_hits_colored_label_on_first_row(self):
        self.assertTrue(self.v._task_label_hit(self.bl, 70, 50))
        self.assertTrue(self.v._task_label_hit(self.bl, 111.999, 73.999))

    def test_excludes_body_text_and_other_rows(self):
        self.assertFalse(self.v._task_label_hit(self.bl, 112, 60))
        self.assertFalse(self.v._task_label_hit(self.bl, 80, 74))

    def test_non_task_layout_has_no_label_target(self):
        self.bl.task_label_width = None
        self.assertFalse(self.v._task_label_hit(self.bl, 80, 60))


class TestControlClickLink(unittest.TestCase):
    def test_opens_link_without_entering_editor(self):
        v = view((0, "[docs](https://example.com)"))
        bl = SimpleNamespace(block=v.blocks[0])
        v._block_at_y = lambda y: bl
        v._link_url_from_click = (
            lambda target, x, y: "https://example.com"
        )
        finished = []
        opened = []
        v._finish_editing = lambda: finished.append(True)
        v._open_link = lambda url, timestamp: opened.append((url, timestamp))
        v.edit_view = None
        v.selection = (0, 0)
        event = SimpleNamespace(
            state=Gdk.ModifierType.CONTROL_MASK,
            button=1,
            type=Gdk.EventType.BUTTON_PRESS,
            x=25,
            y=40,
            time=1234,
        )

        self.assertTrue(v._on_click(v.canvas, event))

        self.assertEqual(finished, [True])
        self.assertIsNone(v.selection)
        self.assertEqual(opened, [("https://example.com", 1234)])


class TestEditActivationDoubleClick(unittest.TestCase):
    def setUp(self):
        self.v = view((0, "alpha bravo"))
        self.block = self.v.blocks[0]
        self.v._edit_activation_click = (
            1000,
            50.0,
            80.0,
            self.block,
            3,
        )
        self.v._double_click_thresholds = lambda: (250, 5)

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
            self.v._completes_edit_activation_click(
                self.event(), self.block
            )
        )

    def test_rejects_late_or_distant_click(self):
        self.assertFalse(
            self.v._completes_edit_activation_click(
                self.event(time=1251), self.block
            )
        )
        self.assertFalse(
            self.v._completes_edit_activation_click(
                self.event(x_root=56.0), self.block
            )
        )

    def test_rejects_another_button_or_block(self):
        self.assertFalse(
            self.v._completes_edit_activation_click(
                self.event(button=3), self.block
            )
        )
        self.assertFalse(
            self.v._completes_edit_activation_click(
                self.event(), Block(0, "different")
            )
        )


class TestEnter(unittest.TestCase):
    def test_split_parent_before_text_keeps_right_side_with_its_children(self):
        v = view((0, "a"), (1, "b"), (2, "c"), (2, "d"))
        v.editing_block = v.blocks[1]
        buf = SimpleNamespace(
            get_insert=lambda: None,
            get_iter_at_mark=lambda _mark: SimpleNamespace(
                get_offset=lambda: 0
            ),
            set_text=lambda text: setattr(v.blocks[1], "text", text),
        )
        v.edit_view = SimpleNamespace(get_buffer=lambda: buf)
        v._begin_structural = lambda: "before"
        v._end_structural = lambda _pre: None
        moved = []
        v._move_to_block = lambda *position: moved.append(position)

        self.assertTrue(v._handle_enter())

        self.assertEqual(
            shape(v),
            [(0, "a"), (1, ""), (1, "b"), (2, "c"), (2, "d")],
        )
        self.assertEqual(moved, [(1, 0, 0)])

    def test_nested_empty_block_outdents_instead_of_creating_a_block(self):
        v = view((0, "A"), (1, ""), (0, "B"))
        v.editing_block = v.blocks[1]
        v._begin_structural = lambda: "before"
        committed = []
        v._end_structural = committed.append
        v.queue_resize = lambda: None

        self.assertTrue(v._handle_enter())

        self.assertEqual(
            shape(v),
            [(0, "A"), (0, ""), (0, "B")],
        )
        self.assertEqual(committed, ["before"])

    def test_blank_parent_keeps_normal_enter_behavior(self):
        v = view((0, "A"), (1, ""), (2, "child"), (0, "B"))
        v.editing_block = v.blocks[1]
        buf = SimpleNamespace(
            get_insert=lambda: None,
            get_iter_at_mark=lambda _mark: SimpleNamespace(
                get_offset=lambda: 0
            ),
            set_text=lambda _text: None,
        )
        v.edit_view = SimpleNamespace(get_buffer=lambda: buf)
        v._begin_structural = lambda: "before"
        v._end_structural = lambda _pre: None
        moved = []
        v._move_to_block = lambda *position: moved.append(position)

        self.assertTrue(v._handle_enter())

        self.assertEqual(
            shape(v),
            [(0, "A"), (1, ""), (2, ""), (2, "child"), (0, "B")],
        )
        self.assertEqual(moved, [(2, 0, 0)])


class TestDeleteEmpty(unittest.TestCase):
    def prepare(self, v, editing_idx):
        v.editing_block = v.blocks[editing_idx]
        v._begin_structural = lambda: "before"
        v._end_structural = lambda _pre: None
        self.moved = []
        v._move_to_block = lambda *position: self.moved.append(position)

    def test_removes_empty_block_and_focuses_block_below(self):
        v = view((0, "A"), (1, ""), (1, "B"))
        self.prepare(v, 1)

        self.assertTrue(v._maybe_handle_delete_empty())

        self.assertEqual(shape(v), [(0, "A"), (1, "B")])
        self.assertEqual(self.moved, [(1, 0, 0)])

    def test_promotes_children_when_removing_empty_parent(self):
        v = view(
            (0, "A"),
            (1, ""),
            (2, "child"),
            (3, "grandchild"),
            (1, "B"),
        )
        self.prepare(v, 1)

        self.assertTrue(v._maybe_handle_delete_empty())

        self.assertEqual(
            shape(v),
            [(0, "A"), (1, "child"), (2, "grandchild"), (1, "B")],
        )
        self.assertEqual(self.moved, [(1, 0, 0)])

    def test_leaves_last_empty_block_in_place(self):
        v = view((0, "A"), (0, ""))
        self.prepare(v, 1)

        self.assertFalse(v._maybe_handle_delete_empty())

        self.assertEqual(shape(v), [(0, "A"), (0, "")])
        self.assertEqual(self.moved, [])


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


class TestContentFont(unittest.TestCase):
    def test_body_font_is_ten_percent_larger_than_widget_default(self):
        default_font = Pango.FontDescription("Sans 10")

        body_font = resolve_body_font(_StubFontWidget(default_font))

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
