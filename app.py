import argparse
import os
import signal
from dataclasses import dataclass

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from markdown import (
    display_char_from_byte,
    runs_to_markup,
    source_offset_from_display,
    tokenize_inline,
)


BG = (1.0, 1.0, 1.0)
FG = (0.13, 0.13, 0.13)
DIM = (0.55, 0.55, 0.57)
GUIDE = (0.87, 0.87, 0.89)
SELECTION_BG = (0.83, 0.90, 0.99)

X0 = 32
INDENT = 22
BULLET_GAP = 16
TEXT_PAD = 4
TOP_PAD = 28
HEADER_GAP = 8
RIGHT_PAD = 16


@dataclass(eq=False)
class Block:
    level: int
    text: str


@dataclass
class BlockLayout:
    block: Block
    y: float
    height: float
    text_x: float
    text_width: float


@dataclass
class HeaderLayout:
    text: str
    y: float
    height: float
    text_x: float
    text_width: float


HEADER = "Wednesday, 24 April 2026"

BLOCKS = [
    Block(0, "dailyfold — hello, **world**"),
    Block(1, "GTK3 window open"),
    Block(1, "*custom* Cairo rendering"),
    Block(1, "snapshot → PNG for feedback"),
    Block(0, "click a bullet to edit — tab away or click elsewhere to commit"),
    Block(0, "inline markdown: **bold**, *italic*, `code`"),
    Block(0, "multi-line block\n(shift+enter later; for now any \\n in text)\nrenders across lines"),
    Block(1, "styling **carries**\nacross *line* breaks too"),
]


def resolve_body_font(widget=None):
    if widget is not None:
        return widget.get_pango_context().get_font_description().copy()
    settings = Gtk.Settings.get_default()
    name = settings.get_property("gtk-font-name") if settings else None
    return Pango.FontDescription(name or "Sans 11")


def _header_font_of(body_font):
    hf = body_font.copy()
    size = hf.get_size() or 11 * Pango.SCALE
    hf.set_size(int(size * 1.3))
    hf.set_weight(Pango.Weight.BOLD)
    return hf


def compute_layouts(pango_context, width, body_font, header_text, blocks):
    header_font = _header_font_of(body_font)

    sample = Pango.Layout.new(pango_context)
    sample.set_font_description(body_font)
    sample.set_text("Ag", -1)
    _, body_ext = sample.get_pixel_extents()
    body_line_h = body_ext.height

    y = TOP_PAD

    h_tx = X0
    h_tw = max(1, width - h_tx - RIGHT_PAD)
    h_lay = Pango.Layout.new(pango_context)
    h_lay.set_font_description(header_font)
    h_lay.set_width(h_tw * Pango.SCALE)
    h_lay.set_wrap(Pango.WrapMode.WORD_CHAR)
    h_lay.set_text(header_text, -1)
    _, h_ext = h_lay.get_pixel_extents()
    header_layout = HeaderLayout(
        text=header_text,
        y=y,
        height=h_ext.height + TEXT_PAD * 2,
        text_x=h_tx,
        text_width=h_tw,
    )
    y += header_layout.height + HEADER_GAP

    layouts = []
    for block in blocks:
        tx = X0 + block.level * INDENT + BULLET_GAP
        tw = max(1, width - tx - RIGHT_PAD)

        lay = Pango.Layout.new(pango_context)
        lay.set_font_description(body_font)
        lay.set_width(tw * Pango.SCALE)
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        lay.set_markup(runs_to_markup(tokenize_inline(block.text)), -1)
        _, ext = lay.get_pixel_extents()
        content_h = max(ext.height, body_line_h)
        block_h = content_h + TEXT_PAD * 2

        layouts.append(
            BlockLayout(
                block=block,
                y=y,
                height=block_h,
                text_x=tx,
                text_width=tw,
            )
        )
        y += block_h
    return header_layout, layouts


def paint_blocks(
    cr,
    width,
    height,
    body_font,
    header_layout,
    layouts,
    fg=FG,
    skip_text_for=None,
    selected_blocks=None,
):
    selected_blocks = selected_blocks or set()
    cr.set_source_rgb(*BG)
    cr.paint()

    layout = PangoCairo.create_layout(cr)
    header_font = _header_font_of(body_font)

    sample = Pango.Layout.new(layout.get_context())
    sample.set_font_description(body_font)
    sample.set_text("Ag", -1)
    _, body_ext = sample.get_pixel_extents()
    body_line_h = body_ext.height

    layout.set_font_description(header_font)
    layout.set_width(header_layout.text_width * Pango.SCALE)
    layout.set_wrap(Pango.WrapMode.WORD_CHAR)
    layout.set_text(header_layout.text, -1)
    cr.set_source_rgb(*fg)
    cr.move_to(header_layout.text_x, header_layout.y + TEXT_PAD)
    PangoCairo.show_layout(cr, layout)

    for bl in layouts:
        block = bl.block

        if block in selected_blocks:
            cr.set_source_rgb(*SELECTION_BG)
            cr.rectangle(0, bl.y, width, bl.height)
            cr.fill()

        if block.level > 0:
            cr.set_source_rgb(*GUIDE)
            cr.set_line_width(1)
            for g in range(1, block.level + 1):
                gxi = X0 + g * INDENT - INDENT // 2
                cr.move_to(gxi + 0.5, bl.y)
                cr.line_to(gxi + 0.5, bl.y + bl.height)
                cr.stroke()

        cr.set_source_rgb(*DIM)
        bullet_x = X0 + block.level * INDENT + 5
        bullet_y = bl.y + TEXT_PAD + body_line_h / 2
        cr.arc(bullet_x, bullet_y, 2.5, 0, 2 * 3.14159)
        cr.fill()

        if block is skip_text_for:
            continue

        layout.set_font_description(body_font)
        layout.set_width(bl.text_width * Pango.SCALE)
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_markup(runs_to_markup(tokenize_inline(block.text)), -1)
        cr.set_source_rgb(*fg)
        cr.move_to(bl.text_x, bl.y + TEXT_PAD)
        PangoCairo.show_layout(cr, layout)


class BlocksView(Gtk.Overlay):
    def __init__(self, header_text, blocks):
        super().__init__()
        self.header_text = header_text
        self.blocks = blocks
        self.header_layout = None
        self.layouts = []
        self.editing_block = None
        self.edit_view = None
        self.desired_col = None
        self.selection = None

        self.canvas = Gtk.DrawingArea()
        self.canvas.set_can_focus(True)
        self.canvas.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.canvas.connect("draw", self._on_draw)
        self.canvas.connect("button-press-event", self._on_click)
        self.canvas.connect("key-press-event", self._on_canvas_key_press)
        self.add(self.canvas)

        self.connect("get-child-position", self._position_overlay)

    def _recompute_layouts(self, width):
        body_font = resolve_body_font(self.canvas)
        self.header_layout, self.layouts = compute_layouts(
            self.canvas.get_pango_context(),
            width,
            body_font,
            self.header_text,
            self.blocks,
        )

    def _on_draw(self, widget, cr):
        alloc = widget.get_allocation()
        self._recompute_layouts(alloc.width)
        sc = widget.get_style_context()
        found, rgba = sc.lookup_color("theme_text_color")
        if not found:
            rgba = sc.get_color(Gtk.StateFlags.NORMAL)
        selected_blocks = set()
        if self.selection is not None:
            for i in self._selection_indices():
                selected_blocks.add(self.blocks[i])
        paint_blocks(
            cr,
            alloc.width,
            alloc.height,
            resolve_body_font(widget),
            self.header_layout,
            self.layouts,
            fg=(rgba.red, rgba.green, rgba.blue),
            skip_text_for=self.editing_block,
            selected_blocks=selected_blocks,
        )
        return False

    def _on_click(self, widget, event):
        if self.edit_view is not None:
            self._finish_editing()
        if self.selection is not None:
            self.selection = None
            self.canvas.queue_draw()
        for bl in self.layouts:
            if bl.y <= event.y < bl.y + bl.height:
                cursor = self._cursor_from_click(bl, event.x, event.y)
                self._start_editing(bl, cursor)
                return True
        return False

    def _cursor_from_click(self, bl, click_x, click_y):
        body_font = resolve_body_font(self.canvas)

        lay = Pango.Layout.new(self.canvas.get_pango_context())
        lay.set_font_description(body_font)
        lay.set_width(bl.text_width * Pango.SCALE)
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        runs = tokenize_inline(bl.block.text)
        lay.set_markup(runs_to_markup(runs), -1)

        local_x = max(0, click_x - bl.text_x)
        local_y = max(0, click_y - (bl.y + TEXT_PAD))
        _, byte_idx, trailing = lay.xy_to_index(
            int(local_x * Pango.SCALE), int(local_y * Pango.SCALE)
        )

        display_text = lay.get_text()
        char_idx = display_char_from_byte(display_text, byte_idx) + trailing
        char_idx = min(char_idx, len(display_text))
        return source_offset_from_display(runs, char_idx)

    def _start_editing(self, bl, cursor_source_idx=None):
        tv = Gtk.TextView()
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.set_left_margin(0)
        tv.set_right_margin(0)
        tv.set_top_margin(0)
        tv.set_bottom_margin(0)
        buf = tv.get_buffer()
        buf.set_text(bl.block.text)
        if cursor_source_idx is not None:
            offset = max(0, min(cursor_source_idx, buf.get_char_count()))
            buf.place_cursor(buf.get_iter_at_offset(offset))
        buf.connect("changed", self._on_buffer_changed)
        tv.connect("focus-out-event", self._on_edit_focus_out)
        tv.connect("key-press-event", self._on_key_press)

        self.editing_block = bl.block
        self.edit_view = tv
        self.desired_col = None

        self.add_overlay(tv)
        tv.show()
        tv.grab_focus()
        self.canvas.queue_draw()

    def _position_overlay(self, overlay, widget, allocation):
        if widget is not self.edit_view or self.editing_block is None:
            return False
        overlay_alloc = overlay.get_allocation()
        self._recompute_layouts(overlay_alloc.width)
        for bl in self.layouts:
            if bl.block is self.editing_block:
                allocation.x = int(bl.text_x)
                allocation.y = int(bl.y + TEXT_PAD)
                allocation.width = int(bl.text_width)
                allocation.height = int(bl.height - TEXT_PAD * 2)
                return True
        return False

    def _on_buffer_changed(self, buf):
        if self.editing_block is None:
            return
        self.desired_col = None
        start, end = buf.get_bounds()
        self.editing_block.text = buf.get_text(start, end, True)
        self.canvas.queue_draw()
        self.queue_resize()

    def _on_key_press(self, tv, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        if state == 0:
            if event.keyval == Gdk.KEY_Up:
                return self._handle_up()
            if event.keyval == Gdk.KEY_Down:
                return self._handle_down()
            if event.keyval == Gdk.KEY_Left:
                return self._handle_left()
            if event.keyval == Gdk.KEY_Right:
                return self._handle_right()
            if event.keyval == Gdk.KEY_Tab:
                return self._handle_tab(shift=False)
            if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                return self._handle_enter()
            if event.keyval == Gdk.KEY_BackSpace:
                if self._maybe_handle_backspace_join():
                    return True
        if state == Gdk.ModifierType.SHIFT_MASK and event.keyval in (
            Gdk.KEY_Tab,
            Gdk.KEY_ISO_Left_Tab,
        ):
            return self._handle_tab(shift=True)
        if state == Gdk.ModifierType.MOD1_MASK and event.keyval in (
            Gdk.KEY_Up,
            Gdk.KEY_Down,
        ):
            return self._enter_selection_mode()
        self.desired_col = None
        return False

    def _block_index(self, block):
        for i, b in enumerate(self.blocks):
            if b is block:
                return i
        return -1

    def _current_position(self):
        buf = self.edit_view.get_buffer()
        offset = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        text = self.editing_block.text
        prefix = text[:offset]
        line_idx = prefix.count("\n")
        last_nl = prefix.rfind("\n")
        col = offset - (last_nl + 1) if last_nl >= 0 else offset
        return self._block_index(self.editing_block), line_idx, col

    def _source_offset(self, text, line_idx, col):
        lines = text.split("\n")
        line_idx = max(0, min(line_idx, len(lines) - 1))
        col = max(0, min(col, len(lines[line_idx])))
        return sum(len(l) + 1 for l in lines[:line_idx]) + col

    def _set_cursor_in_current_block(self, line_idx, col):
        buf = self.edit_view.get_buffer()
        offset = self._source_offset(self.editing_block.text, line_idx, col)
        buf.place_cursor(buf.get_iter_at_offset(offset))

    def _move_to_block(self, target_idx, line_idx, col):
        desired_col = self.desired_col
        self._finish_editing()
        target_block = self.blocks[target_idx]
        alloc = self.canvas.get_allocation()
        self._recompute_layouts(alloc.width)
        for bl in self.layouts:
            if bl.block is target_block:
                offset = self._source_offset(target_block.text, line_idx, col)
                self._start_editing(bl, offset)
                self.desired_col = desired_col
                return

    def _handle_up(self):
        b, l, c = self._current_position()
        if self.desired_col is None:
            self.desired_col = c
        if l > 0:
            self._set_cursor_in_current_block(l - 1, self.desired_col)
            return True
        if b > 0:
            prev_lines = self.blocks[b - 1].text.split("\n")
            self._move_to_block(b - 1, len(prev_lines) - 1, self.desired_col)
            return True
        return True

    def _handle_down(self):
        b, l, c = self._current_position()
        if self.desired_col is None:
            self.desired_col = c
        lines = self.editing_block.text.split("\n")
        if l < len(lines) - 1:
            self._set_cursor_in_current_block(l + 1, self.desired_col)
            return True
        if b < len(self.blocks) - 1:
            self._move_to_block(b + 1, 0, self.desired_col)
            return True
        return True

    def _handle_left(self):
        b, l, c = self._current_position()
        self.desired_col = None
        if c > 0:
            return False
        if l > 0:
            lines = self.editing_block.text.split("\n")
            self._set_cursor_in_current_block(l - 1, len(lines[l - 1]))
            return True
        if b > 0:
            prev_lines = self.blocks[b - 1].text.split("\n")
            self._move_to_block(b - 1, len(prev_lines) - 1, len(prev_lines[-1]))
            return True
        return True

    def _subtree_end(self, b):
        base = self.blocks[b].level
        end = b + 1
        while end < len(self.blocks) and self.blocks[end].level > base:
            end += 1
        return end

    def _handle_tab(self, shift):
        if self.editing_block is None:
            return False
        b = self._block_index(self.editing_block)
        block = self.editing_block

        if shift:
            if block.level <= 0:
                return True
            delta = -1
        else:
            prev_sibling = None
            for i in range(b - 1, -1, -1):
                if self.blocks[i].level < block.level:
                    break
                if self.blocks[i].level == block.level:
                    prev_sibling = i
                    break
            if prev_sibling is None:
                return True
            delta = 1

        end = self._subtree_end(b)
        for i in range(b, end):
            self.blocks[i].level += delta

        self.canvas.queue_draw()
        self.queue_resize()
        return True

    def _handle_enter(self):
        if self.editing_block is None:
            return False
        b = self._block_index(self.editing_block)
        block = self.editing_block

        buf = self.edit_view.get_buffer()
        offset = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        left = block.text[:offset]
        right = block.text[offset:]

        new_block = Block(level=block.level, text=right)
        insert_idx = self._subtree_end(b)
        self.blocks.insert(insert_idx, new_block)

        buf.set_text(left)
        self._move_to_block(insert_idx, 0, 0)
        return True

    def _maybe_handle_backspace_join(self):
        if self.editing_block is None:
            return False
        b, l, c = self._current_position()
        if b <= 0 or l != 0 or c != 0:
            return False

        prev = self.blocks[b - 1]

        block = self.editing_block
        prev_lines = prev.text.split("\n")
        join_line = len(prev_lines) - 1
        join_col = len(prev_lines[-1])

        end = self._subtree_end(b)
        delta = prev.level - block.level
        for i in range(b + 1, end):
            self.blocks[i].level += delta

        prev.text = prev.text + block.text
        del self.blocks[b]

        self._move_to_block(b - 1, join_line, join_col)
        return True

    def _handle_right(self):
        b, l, c = self._current_position()
        self.desired_col = None
        lines = self.editing_block.text.split("\n")
        if c < len(lines[l]):
            return False
        if l < len(lines) - 1:
            self._set_cursor_in_current_block(l + 1, 0)
            return True
        if b < len(self.blocks) - 1:
            self._move_to_block(b + 1, 0, 0)
            return True
        return True

    def _selection_indices(self):
        if self.selection is None:
            return range(0, 0)
        anchor, head = self.selection
        lo = min(anchor, head)
        hi = max(anchor, head)
        end = hi + 1
        for i in range(lo, hi + 1):
            end = max(end, self._subtree_end(i))
        return range(lo, end)

    def _enter_selection_mode(self):
        if self.editing_block is None:
            return False
        idx = self._block_index(self.editing_block)
        self._finish_editing()
        self.selection = (idx, idx)
        self.canvas.grab_focus()
        self.canvas.queue_draw()
        return True

    def _on_canvas_key_press(self, widget, event):
        if self.selection is None:
            return False
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        anchor, head = self.selection
        n = len(self.blocks)
        if n == 0:
            return False

        if state == 0:
            if event.keyval == Gdk.KEY_Up:
                indices = self._selection_indices()
                new = max(0, indices[0] - 1)
                self.selection = (new, new)
                self.canvas.queue_draw()
                return True
            if event.keyval == Gdk.KEY_Down:
                indices = self._selection_indices()
                new = min(n - 1, indices[-1] + 1)
                self.selection = (new, new)
                self.canvas.queue_draw()
                return True
            if event.keyval == Gdk.KEY_Left:
                return self._exit_selection_to_edit(at_end=False)
            if event.keyval == Gdk.KEY_Right:
                return self._exit_selection_to_edit(at_end=True)
            if event.keyval == Gdk.KEY_Escape:
                self.selection = None
                self.canvas.queue_draw()
                return True

        if state in (Gdk.ModifierType.SHIFT_MASK, Gdk.ModifierType.MOD1_MASK):
            if event.keyval == Gdk.KEY_Up:
                self.selection = (anchor, max(0, head - 1))
                self.canvas.queue_draw()
                return True
            if event.keyval == Gdk.KEY_Down:
                self.selection = (anchor, min(n - 1, head + 1))
                self.canvas.queue_draw()
                return True

        return False

    def _exit_selection_to_edit(self, at_end):
        indices = self._selection_indices()
        target_idx = indices[-1] if at_end else indices[0]
        target = self.blocks[target_idx]
        self.selection = None
        if at_end:
            lines = target.text.split("\n")
            self._move_to_block(target_idx, len(lines) - 1, len(lines[-1]))
        else:
            self._move_to_block(target_idx, 0, 0)
        return True

    def _on_edit_focus_out(self, widget, event):
        self._finish_editing()
        return False

    def _finish_editing(self):
        if self.edit_view is None:
            return
        tv = self.edit_view
        block = self.editing_block
        self.edit_view = None
        self.editing_block = None
        buf = tv.get_buffer()
        start, end = buf.get_bounds()
        block.text = buf.get_text(start, end, True)
        self.remove(tv)
        self.canvas.queue_draw()


class AppWindow(Gtk.Window):
    def __init__(self, header_text, blocks):
        super().__init__(title="dailyfold")
        self.set_default_size(720, 480)
        self.connect("destroy", Gtk.main_quit)
        self.add(BlocksView(header_text, blocks))


DEFAULT_SNAPSHOT = os.path.join(os.path.dirname(__file__), "snapshots", "latest.png")


def snapshot(path, width=720, height=480):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    body_font = resolve_body_font()
    pango_context = PangoCairo.create_layout(cr).get_context()
    header_layout, layouts = compute_layouts(
        pango_context, width, body_font, HEADER, BLOCKS
    )
    paint_blocks(cr, width, height, body_font, header_layout, layouts)
    surface.write_to_png(path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--snapshot",
        nargs="?",
        const=DEFAULT_SNAPSHOT,
        default=None,
        metavar="PATH",
        help=f"render to PNG and exit (default: {DEFAULT_SNAPSHOT})",
    )
    p.add_argument("--width", type=int, default=720)
    p.add_argument("--height", type=int, default=480)
    args = p.parse_args()

    if args.snapshot:
        snapshot(args.snapshot, args.width, args.height)
        return

    win = AppWindow(HEADER, BLOCKS)
    win.show_all()

    def _graceful_quit():
        win.close()
        return GLib.SOURCE_REMOVE

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _graceful_quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, _graceful_quit)

    Gtk.main()


if __name__ == "__main__":
    main()
