"""GTK block editor widget."""

import re
from dataclasses import dataclass

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("GtkSource", "4")
from gi.repository import Gdk, GLib, Gtk, GtkSource, Pango, PangoCairo

from block_markdown import CODE_FENCE_RE
from clipboard import (
    CLIPBOARD_BLOCKS_INFO,
    CLIPBOARD_BLOCKS_TARGET,
    CLIPBOARD_HTML_INFO,
    CLIPBOARD_HTML_TARGET,
    CLIPBOARD_TEXT_INFO,
    blocks_from_clipboard_payload,
    blocks_from_clipboard_text,
    blocks_to_clipboard_html,
    blocks_to_clipboard_payload,
    blocks_to_clipboard_text,
    copy_blocks,
    link_from_paste,
)
from history import History
from inline_markdown import (
    display_char_from_byte,
    link_url_at_display_offset,
    parse_inline,
    runs_to_markup,
    source_offset_from_display,
)
from model import Block
from outline import (
    delete_empty_forward,
    delete_range,
    expand_selection,
    insert_blocks,
    join_with_previous,
    move_range,
    parent_index,
    selection_indices,
    shift_levels,
    split_block,
    subtree_end,
    visible_block_indices,
    visible_neighbor,
)


CODE_INDENT_WIDTH = 4


BG = (1.0, 1.0, 1.0)
FG = (0.13, 0.13, 0.13)
DIM = (0.55, 0.55, 0.57)
COLLAPSED_INDICATOR = (0.34, 0.34, 0.36)
GUIDE = (0.87, 0.87, 0.89)
SELECTION_BG = (0.83, 0.90, 0.99)
CODE_BG = (0xfd / 255, 0xf6 / 255, 0xe3 / 255)
TODO_ACCENT = (0x04 / 255, 0x55 / 255, 0x91 / 255)
DONE_ACCENT = (0.27, 0.57, 0.38)
CODE_BG_CSS = b"""
textview.code-block, textview.code-block text {
    background-color: #fdf6e3;
}
"""

TASK_RE = re.compile(r"^(TODO|DONE) ")

X0 = 32
INDENT = 22
BULLET_GAP = 16
TEXT_PAD = 4
TOP_PAD = 4
HEADER_GAP = 8
RIGHT_PAD = 32
BOTTOM_PAD = 28
TASK_CHECKBOX_SIZE = 13
TASK_CHECKBOX_GAP = 7
THIN_SPACE = "\u2009"


CONTENT_FONT_SCALE = 1.1


@dataclass
class BlockLayout:
    block: Block
    y: float
    height: float
    text_x: float
    text_width: float
    checkbox_x: float | None = None
    checkbox_y: float | None = None
    task_label_width: float | None = None
    has_children: bool = False


@dataclass
class HeaderLayout:
    text: str
    y: float
    height: float
    text_x: float
    text_width: float


def task_state(text):
    match = TASK_RE.match(text)
    return match.group(1) if match is not None else None


def toggle_task_text(text):
    state = task_state(text)
    if state is None:
        return None
    replacement = "DONE" if state == "TODO" else "TODO"
    return replacement + text[4:]


def _task_label_markup(state):
    if state == "TODO":
        return (
            '<span foreground="#045591" background="#e1f0f7" '
            f'weight="bold">{THIN_SPACE}TODO{THIN_SPACE}</span>'
        )
    return (
        '<span foreground="#2f6f44" background="#def3e5" '
        f'weight="bold">{THIN_SPACE}DONE{THIN_SPACE}</span>'
    )


def _task_markup(text, inline=None):
    state = task_state(text)
    if state is None:
        if inline is None:
            inline = parse_inline(text)
        return runs_to_markup(inline.runs)

    body_markup = runs_to_markup(parse_inline(text[5:]).runs)
    if state == "DONE":
        body_markup = (
            '<span foreground="#88898c" strikethrough="true">'
            f"{body_markup}</span>"
        )
    return _task_label_markup(state) + " " + body_markup


def _block_task_state(block):
    if block.code_lang is not None:
        return None
    return task_state(block.text)


def _block_markup(block, inline=None):
    return _task_markup(block.text, inline)


def resolve_body_font(widget=None):
    if widget is not None:
        font = widget.get_pango_context().get_font_description().copy()
    else:
        settings = Gtk.Settings.get_default()
        name = settings.get_property("gtk-font-name") if settings else None
        font = Pango.FontDescription(name or "Sans 11")

    size = font.get_size() or 11 * Pango.SCALE
    scaled_size = round(size * CONTENT_FONT_SCALE)
    if font.get_size_is_absolute():
        font.set_absolute_size(scaled_size)
    else:
        font.set_size(scaled_size)
    return font


def _header_font_of(body_font):
    hf = body_font.copy()
    size = hf.get_size() or 11 * Pango.SCALE
    hf.set_size(int(size * 1.5))
    hf.set_weight(Pango.Weight.BOLD)
    return hf


def _code_font_of(body_font):
    cf = body_font.copy()
    cf.set_family("monospace")
    return cf


_CODE_CSS_PROVIDER = None


def _code_css_provider():
    global _CODE_CSS_PROVIDER
    if _CODE_CSS_PROVIDER is None:
        p = Gtk.CssProvider()
        p.load_from_data(CODE_BG_CSS)
        _CODE_CSS_PROVIDER = p
    return _CODE_CSS_PROVIDER


def _apply_code_textview_style(tv, on):
    ctx = tv.get_style_context()
    if on:
        ctx.add_class("code-block")
        ctx.add_provider(_code_css_provider(), Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    else:
        ctx.remove_class("code-block")
        ctx.remove_provider(_code_css_provider())


def append_area_hit(blocks, layouts, header_layout, body_row_height, y):
    """Return whether *y* is in the row used to append a root block."""
    if blocks and blocks[-1].level == 0 and not blocks[-1].text:
        return False
    if layouts:
        top = layouts[-1].y + layouts[-1].height
    elif header_layout is not None:
        top = header_layout.y + header_layout.height + HEADER_GAP
    else:
        return False
    return top <= y < top + body_row_height


def task_label_hit(block_layout, body_row_height, x, y):
    """Return whether a point hits the task badge on a block's first row."""
    if block_layout.task_label_width is None:
        return False
    return (
        block_layout.text_x
        <= x
        < block_layout.text_x + block_layout.task_label_width
        and block_layout.y <= y < block_layout.y + body_row_height
    )


def completes_edit_activation_click(
    first_click,
    event,
    block,
    max_time,
    max_distance,
):
    """Return whether *event* completes the remembered activation click."""
    if first_click is None or event.button != 1 or first_click[3] is not block:
        return False

    elapsed = (int(event.time) - first_click[0]) & 0xFFFFFFFF
    return (
        elapsed <= max_time
        and abs(float(event.x_root) - first_click[1]) <= max_distance
        and abs(float(event.y_root) - first_click[2]) <= max_distance
    )


def publish_clipboard(canvas, targets, plain_text):
    """Publish clipboard targets after claiming ownership of the selection."""
    if Gtk.selection_owner_set(
        canvas, Gdk.SELECTION_CLIPBOARD, Gdk.CURRENT_TIME
    ):
        # On Wayland, publishing targets creates the compositor-facing data
        # source. Do it only after the realized canvas owns the selection so
        # ownership loss can cancel that source normally.
        Gtk.selection_clear_targets(canvas, Gdk.SELECTION_CLIPBOARD)
        Gtk.selection_add_targets(
            canvas,
            Gdk.SELECTION_CLIPBOARD,
            targets,
        )
    else:
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(plain_text, -1)


def compute_layouts(
    pango_context,
    width,
    body_font,
    header_text,
    blocks,
    editing_block=None,
):
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

    code_font = _code_font_of(body_font)
    layouts = []
    for block_idx in visible_block_indices(blocks):
        block = blocks[block_idx]
        tx = X0 + block.level * INDENT + BULLET_GAP
        checkbox_x = None
        checkbox_y = None
        task_label_width = None
        state = _block_task_state(block)
        if state is not None:
            checkbox_x = tx
            checkbox_y = y + TEXT_PAD + max(
                0, (body_line_h - TASK_CHECKBOX_SIZE) / 2
            )
            tx += TASK_CHECKBOX_SIZE + TASK_CHECKBOX_GAP
            task_label = Pango.Layout.new(pango_context)
            task_label.set_font_description(body_font)
            task_label.set_markup(_task_label_markup(state), -1)
            _, task_label_ext = task_label.get_pixel_extents()
            task_label_width = task_label_ext.width
        tw = max(1, width - tx - RIGHT_PAD)

        lay = Pango.Layout.new(pango_context)
        editing_width = tw
        if block is editing_block and checkbox_x is not None:
            editing_width += tx - checkbox_x
        lay.set_width(
            (editing_width if block is editing_block else tw) * Pango.SCALE
        )
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        if block is editing_block:
            lay.set_font_description(
                code_font if block.code_lang is not None else body_font
            )
            lay.set_text(block.text, -1)
        elif block.code_lang is not None:
            lay.set_font_description(code_font)
            lay.set_text(block.text, -1)
        else:
            lay.set_font_description(body_font)
            lay.set_markup(_block_markup(block), -1)
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
                checkbox_x=checkbox_x,
                checkbox_y=checkbox_y,
                task_label_width=task_label_width,
                has_children=(
                    block_idx + 1 < len(blocks)
                    and blocks[block_idx + 1].level > block.level
                ),
            )
        )
        y += block_h
    return header_layout, layouts


def _rounded_rectangle(cr, x, y, width, height, radius):
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -1.5708, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
    cr.arc(x + radius, y + height - radius, radius, 1.5708, 3.14159)
    cr.arc(x + radius, y + radius, radius, 3.14159, 4.71239)
    cr.close_path()


def _paint_task_checkbox(cr, bl, state):
    x = bl.checkbox_x
    y = bl.checkbox_y
    size = TASK_CHECKBOX_SIZE
    accent = DONE_ACCENT if state == "DONE" else TODO_ACCENT

    cr.save()
    _rounded_rectangle(cr, x + 0.5, y + 0.5, size - 1, size - 1, 2.5)
    cr.set_line_width(1.5)
    cr.set_source_rgb(*accent)
    if state == "DONE":
        cr.fill_preserve()
    cr.stroke()

    if state == "DONE":
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(1.7)
        cr.set_line_cap(cairo.LineCap.ROUND)
        cr.set_line_join(cairo.LineJoin.ROUND)
        cr.move_to(x + 3.0, y + 6.7)
        cr.line_to(x + 5.4, y + 9.0)
        cr.line_to(x + 10.2, y + 3.8)
        cr.stroke()
    cr.restore()


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
    hovered_bullet=None,
):
    selected_blocks = selected_blocks or set()
    cr.set_source_rgb(*BG)
    cr.paint()

    layout = PangoCairo.create_layout(cr)
    header_font = _header_font_of(body_font)
    code_font = _code_font_of(body_font)

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
        elif block.code_lang is not None:
            cr.set_source_rgb(*CODE_BG)
            cr.rectangle(
                bl.text_x - TEXT_PAD,
                bl.y + 2,
                width - RIGHT_PAD - (bl.text_x - TEXT_PAD),
                bl.height - 4,
            )
            cr.fill()

        if block.level > 0:
            cr.set_source_rgb(*GUIDE)
            cr.set_line_width(1)
            for g in range(1, block.level + 1):
                gxi = X0 + (g - 1) * INDENT + 5
                cr.move_to(gxi + 0.5, bl.y)
                cr.line_to(gxi + 0.5, bl.y + bl.height)
                cr.stroke()

        bullet_x = X0 + block.level * INDENT + 5.5
        bullet_y = bl.y + TEXT_PAD + body_line_h / 2
        if bl.has_children:
            if block.collapsed:
                color = FG if block is hovered_bullet else COLLAPSED_INDICATOR
                cr.set_source_rgb(*color)
                cr.move_to(bullet_x - 4.0, bullet_y - 4.0)
                cr.line_to(bullet_x + 3.5, bullet_y)
                cr.line_to(bullet_x - 4.0, bullet_y + 3.5)
            else:
                cr.set_source_rgb(*(FG if block is hovered_bullet else DIM))
                cr.move_to(bullet_x - 4.0, bullet_y - 4.0)
                cr.line_to(bullet_x + 3.5, bullet_y - 4.0)
                cr.line_to(bullet_x, bullet_y + 3.5)
            cr.close_path()
            cr.fill()
        else:
            cr.set_source_rgb(*(FG if block is hovered_bullet else DIM))
            cr.arc(bullet_x, bullet_y, 2.5, 0, 2 * 3.14159)
            cr.fill()

        if block is skip_text_for:
            continue

        state = _block_task_state(block)
        if state is not None:
            _paint_task_checkbox(cr, bl, state)

        layout.set_width(bl.text_width * Pango.SCALE)
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        if block.code_lang is not None:
            layout.set_font_description(code_font)
            layout.set_attributes(Pango.AttrList())
            layout.set_text(block.text, -1)
        else:
            layout.set_font_description(body_font)
            layout.set_markup(_block_markup(block), -1)
        cr.set_source_rgb(*fg)
        cr.move_to(bl.text_x, bl.y + TEXT_PAD)
        PangoCairo.show_layout(cr, layout)


class BlocksView(Gtk.Overlay):
    def __init__(self, header_text, blocks, on_change=None):
        super().__init__()
        self.header_text = header_text
        self.blocks = blocks
        self.header_layout = None
        self.layouts = []
        self.editing_block = None
        self.edit_view = None
        self.desired_col = None
        self.selection = None
        self.on_change = on_change
        self.history = History(cap=1000)
        self._coalesce_timer_id = None
        self._suppress_text_snapshot = False
        self._drag_anchor_idx = None
        self._drag_anchor_offset = None
        self._edit_activation_click = None
        self._hovered_bullet = None
        self._pointer_cursor = None
        self._pointer_active = False
        self._clipboard_plain_text = None
        self._clipboard_html = None
        self._clipboard_payload = None
        self._content_height = 1

        self.canvas = Gtk.DrawingArea()
        self.canvas.set_can_focus(True)
        self.canvas.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.canvas.connect("draw", self._on_draw)
        self.canvas.connect("button-press-event", self._on_click)
        self.canvas.connect("button-release-event", self._on_button_release)
        self.canvas.connect("motion-notify-event", self._on_canvas_motion)
        self.canvas.connect("leave-notify-event", self._on_canvas_leave)
        self.canvas.connect("key-press-event", self._on_canvas_key_press)
        self.canvas.connect("selection-get", self._on_clipboard_selection_get)
        self._clipboard_atoms = {
            CLIPBOARD_BLOCKS_INFO: Gdk.Atom.intern(
                CLIPBOARD_BLOCKS_TARGET, False
            ),
            CLIPBOARD_HTML_INFO: Gdk.Atom.intern(CLIPBOARD_HTML_TARGET, False),
        }
        self._clipboard_targets = [
            Gtk.TargetEntry.new(target, 0, info)
            for target, info in [
                (CLIPBOARD_BLOCKS_TARGET, CLIPBOARD_BLOCKS_INFO),
                (CLIPBOARD_HTML_TARGET, CLIPBOARD_HTML_INFO),
                ("text/plain;charset=utf-8", CLIPBOARD_TEXT_INFO),
                ("text/plain", CLIPBOARD_TEXT_INFO),
                ("UTF8_STRING", CLIPBOARD_TEXT_INFO),
                ("TEXT", CLIPBOARD_TEXT_INFO),
                ("STRING", CLIPBOARD_TEXT_INFO),
            ]
        ]
        self.add(self.canvas)

        self.connect("get-child-position", self._position_overlay)

    def set_page(self, header_text, blocks):
        """Replace the current day and discard per-page editing history."""
        self._finish_editing()
        self._cancel_coalesce_timer()
        self.header_text = header_text
        self.blocks = blocks
        self.header_layout = None
        self.layouts = []
        self.selection = None
        self.desired_col = None
        self._set_interaction_hover(None, False)
        self.history = History(cap=1000)
        self._content_height = 1
        self.canvas.set_size_request(-1, 1)
        self.canvas.queue_draw()
        self.queue_resize()

    def _recompute_layouts(self, width):
        body_font = resolve_body_font(self.canvas)
        self.header_layout, self.layouts = compute_layouts(
            self.canvas.get_pango_context(),
            width,
            body_font,
            self.header_text,
            self.blocks,
            editing_block=self.editing_block,
        )
        if self.layouts:
            content_bottom = self.layouts[-1].y + self.layouts[-1].height
        else:
            content_bottom = self.header_layout.y + self.header_layout.height
        content_height = max(1, int(content_bottom + BOTTOM_PAD))
        if content_height != self._content_height:
            self._content_height = content_height
            self.canvas.set_size_request(-1, content_height)

    def _ensure_block_visible(self, block):
        if block not in self.blocks:
            return GLib.SOURCE_REMOVE
        alloc = self.canvas.get_allocation()
        self._recompute_layouts(alloc.width)
        block_layout = next(
            (layout for layout in self.layouts if layout.block is block), None
        )
        scroller = self.get_ancestor(Gtk.ScrolledWindow)
        if block_layout is None or scroller is None:
            return GLib.SOURCE_REMOVE

        adjustment = scroller.get_vadjustment()
        top = block_layout.y - TEXT_PAD
        bottom = block_layout.y + block_layout.height + TEXT_PAD
        value = adjustment.get_value()
        page_size = adjustment.get_page_size()
        if top < value:
            adjustment.set_value(max(adjustment.get_lower(), top))
        elif bottom > value + page_size:
            maximum = max(
                adjustment.get_lower(),
                adjustment.get_upper() - page_size,
            )
            adjustment.set_value(min(maximum, bottom - page_size))
        return GLib.SOURCE_REMOVE

    def ensure_block_visible(self, block):
        GLib.idle_add(self._ensure_block_visible, block)

    def _grab_canvas_focus(self):
        scroller = self.get_ancestor(Gtk.ScrolledWindow)
        adjustment = (
            scroller.get_vadjustment() if scroller is not None else None
        )
        scroll_position = (
            adjustment.get_value() if adjustment is not None else None
        )
        self.canvas.grab_focus()
        if adjustment is not None:
            # GtkScrolledWindow tries to reveal the focused widget. The canvas
            # spans the whole document, so focusing it otherwise reveals its
            # top edge and jumps to the beginning of the journal.
            adjustment.set_value(scroll_position)

    def focus_search_result(self, block_index, match_start, match_end):
        """Reveal a search hit, enter editing, and select its first match."""
        if not (0 <= block_index < len(self.blocks)):
            return False

        target = self.blocks[block_index]
        ancestor_level = target.level
        collapsed_ancestors = []
        for index in range(block_index - 1, -1, -1):
            block = self.blocks[index]
            if block.level < ancestor_level:
                if block.collapsed:
                    collapsed_ancestors.append(block)
                ancestor_level = block.level
                if ancestor_level == 0:
                    break

        if collapsed_ancestors:
            pre = self._begin_structural()
            for block in collapsed_ancestors:
                block.collapsed = False
            self._end_structural(pre)

        self._finish_editing()
        self.selection = None
        self._recompute_layouts(self.canvas.get_allocation().width)
        layout = next(
            (item for item in self.layouts if item.block is target),
            None,
        )
        if layout is None:
            return False

        self._start_editing(layout, match_start)
        buffer = self.edit_view.get_buffer()
        start = buffer.get_iter_at_offset(match_start)
        end = buffer.get_iter_at_offset(match_end)
        buffer.select_range(start, end)
        self.ensure_block_visible(target)
        return True

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
            hovered_bullet=self._hovered_bullet,
        )
        return False

    def _block_at_y(self, y):
        for bl in self.layouts:
            if bl.y <= y < bl.y + bl.height:
                return bl
        return None

    def _body_row_height(self):
        body_font = resolve_body_font(self.canvas)
        sample = Pango.Layout.new(self.canvas.get_pango_context())
        sample.set_font_description(body_font)
        sample.set_text("Ag", -1)
        _, extents = sample.get_pixel_extents()
        return extents.height + TEXT_PAD * 2

    def _append_area_hit(self, y):
        return append_area_hit(
            self.blocks,
            self.layouts,
            self.header_layout,
            self._body_row_height(),
            y,
        )

    def _on_click(self, widget, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        target_bl = self._block_at_y(event.y)

        if (
            target_bl is not None
            and state & Gdk.ModifierType.CONTROL_MASK
            and event.button == 1
            and event.type == Gdk.EventType.BUTTON_PRESS
        ):
            url = self._link_url_from_click(target_bl, event.x, event.y)
            if url is not None:
                self._finish_editing()
                self.selection = None
                self.canvas.queue_draw()
                self._open_link(url, event.time)
                return True

        if (
            target_bl is None
            and state == 0
            and event.button == 1
            and event.type == Gdk.EventType.BUTTON_PRESS
            and self._append_area_hit(event.y)
        ):
            pre = self._begin_structural()
            self._finish_editing()
            self.selection = None
            block = Block(0, "")
            self.blocks.append(block)
            self._recompute_layouts(self.canvas.get_allocation().width)
            new_bl = next(bl for bl in self.layouts if bl.block is block)
            self._start_editing(new_bl, 0)
            self._drag_anchor_idx = len(self.blocks) - 1
            self._drag_anchor_offset = 0
            self._end_structural(pre)
            return True

        if state == Gdk.ModifierType.SHIFT_MASK and target_bl is not None:
            target_idx = self._block_index(target_bl.block)
            if self.editing_block is not None:
                anchor_idx = self._block_index(self.editing_block)
                self._finish_editing()
                self.selection = (anchor_idx, target_idx)
                self._grab_canvas_focus()
                self.canvas.queue_draw()
                return True
            if self.selection is not None:
                anchor, _ = self.selection
                self.selection = (anchor, target_idx)
                self.canvas.queue_draw()
                return True

        if target_bl is not None and (
            self._checkbox_hit(target_bl, event.x, event.y)
            or self._task_label_hit(target_bl, event.x, event.y)
        ):
            target_idx = self._block_index(target_bl.block)
            if self._toggle_task_blocks([target_idx]):
                self.selection = None
                self._grab_canvas_focus()
                return True

        if (
            target_bl is not None
            and event.button == 1
            and self._bullet_hit(target_bl, event.x, event.y)
        ):
            # GTK sends a normal press for the second click, followed by a
            # synthesized double-click press. The normal press has already
            # toggled the fold, so consume the synthesized event without
            # toggling it a third time.
            if event.type != Gdk.EventType.BUTTON_PRESS:
                return True
            target_idx = self._block_index(target_bl.block)
            if self._toggle_fold(target_idx):
                self.selection = None
                self._grab_canvas_focus()
                return True

        if self.edit_view is not None:
            self._finish_editing()
        if self.selection is not None:
            self.selection = None
            self.canvas.queue_draw()
        if target_bl is not None:
            cursor = self._cursor_from_click(target_bl, event.x, event.y)
            completes_double_click = self._completes_edit_activation_click(
                event, target_bl.block
            )
            self._start_editing(target_bl, cursor)
            if completes_double_click:
                self._select_word_at_offset(self.edit_view, cursor)
                self._edit_activation_click = None
            else:
                self._remember_edit_activation_click(
                    event, target_bl.block, cursor
                )
            self._drag_anchor_idx = self._block_index(target_bl.block)
            self._drag_anchor_offset = cursor
            return True
        return False

    def _remember_edit_activation_click(self, event, block, offset):
        if (
            event.button == 1
            and event.type == Gdk.EventType.BUTTON_PRESS
        ):
            self._edit_activation_click = (
                int(event.time),
                float(event.x_root),
                float(event.y_root),
                block,
                offset,
            )
        else:
            self._edit_activation_click = None

    def _completes_edit_activation_click(self, event, block):
        first_click = self._edit_activation_click
        if (
            first_click is None
            or event.button != 1
            or first_click[3] is not block
        ):
            return False
        max_time, max_distance = self._double_click_thresholds()
        return completes_edit_activation_click(
            first_click,
            event,
            block,
            max_time,
            max_distance,
        )

    def _double_click_thresholds(self):
        settings = Gtk.Settings.get_default()
        max_time = settings.get_property("gtk-double-click-time")
        max_distance = settings.get_property("gtk-double-click-distance")
        return max_time, max_distance

    def _select_word_at_offset(self, tv, offset):
        buf = tv.get_buffer()
        location = buf.get_iter_at_offset(
            max(0, min(offset, buf.get_char_count()))
        )
        start = location.copy()
        end = location.copy()
        if not Gtk.TextView.do_extend_selection(
            tv, Gtk.TextExtendSelection.WORD, location, start, end
        ):
            return False
        if start.compare(end) > 0:
            start, end = end, start
        buf.select_range(end, start)
        return True

    def _checkbox_hit(self, bl, x, y):
        if bl.checkbox_x is None or bl.checkbox_y is None:
            return False
        hit_pad = 4
        return (
            bl.checkbox_x - hit_pad
            <= x
            <= bl.checkbox_x + TASK_CHECKBOX_SIZE + hit_pad
            and bl.checkbox_y - hit_pad
            <= y
            <= bl.checkbox_y + TASK_CHECKBOX_SIZE + hit_pad
        )

    def _task_label_hit(self, bl, x, y):
        return task_label_hit(bl, self._body_row_height(), x, y)

    def _bullet_hit(self, bl, x, y):
        if not bl.has_children:
            return False
        bullet_x = X0 + bl.block.level * INDENT + 5.5
        hit_radius = 8
        return (
            abs(x - bullet_x) <= hit_radius
            and bl.y <= y < bl.y + bl.height
        )

    def _set_interaction_hover(self, hovered_bullet, pointer_active):
        bullet_changed = hovered_bullet is not self._hovered_bullet
        pointer_changed = pointer_active != self._pointer_active
        if not bullet_changed and not pointer_changed:
            return
        self._hovered_bullet = hovered_bullet
        self._pointer_active = pointer_active
        window = self.canvas.get_window()
        if window is not None and pointer_changed:
            if pointer_active and self._pointer_cursor is None:
                self._pointer_cursor = Gdk.Cursor.new_from_name(
                    window.get_display(), "pointer"
                )
            window.set_cursor(
                self._pointer_cursor if pointer_active else None
            )
        if bullet_changed:
            self.canvas.queue_draw()

    def _update_interaction_hover(self, x, y):
        target_bl = self._block_at_y(y)
        hovered_bullet = None
        pointer_active = False
        if target_bl is not None and self._bullet_hit(target_bl, x, y):
            hovered_bullet = target_bl.block
            pointer_active = True
        elif target_bl is not None:
            pointer_active = self._checkbox_hit(
                target_bl, x, y
            ) or self._task_label_hit(target_bl, x, y)
        self._set_interaction_hover(hovered_bullet, pointer_active)

    def _on_canvas_leave(self, widget, event):
        self._set_interaction_hover(None, False)
        return False

    def _layout_position_from_click(self, bl, click_x, click_y):
        body_font = resolve_body_font(self.canvas)
        block = bl.block

        lay = Pango.Layout.new(self.canvas.get_pango_context())
        lay.set_width(bl.text_width * Pango.SCALE)
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        if block.code_lang is not None:
            lay.set_font_description(_code_font_of(body_font))
            lay.set_text(block.text, -1)
            inline = None
        else:
            lay.set_font_description(body_font)
            inline = parse_inline(block.text)
            lay.set_markup(_block_markup(block, inline), -1)

        local_x = max(0, click_x - bl.text_x)
        local_y = max(0, click_y - (bl.y + TEXT_PAD))
        inside, byte_idx, trailing = lay.xy_to_index(
            int(local_x * Pango.SCALE), int(local_y * Pango.SCALE)
        )

        display_text = lay.get_text()
        char_idx = min(
            display_char_from_byte(display_text, byte_idx), len(display_text)
        )
        return inside, inline, char_idx, trailing

    def _cursor_from_click(self, bl, click_x, click_y):
        _, inline, char_idx, trailing = self._layout_position_from_click(
            bl, click_x, click_y
        )
        char_idx += trailing
        if inline is None:
            return char_idx
        if _block_task_state(bl.block) is not None:
            # The status badge has one display-only thin space on each side.
            char_idx = max(0, char_idx - 2)
        return source_offset_from_display(inline, char_idx)

    def _link_url_from_click(self, bl, click_x, click_y):
        inside, inline, char_idx, _ = self._layout_position_from_click(
            bl, click_x, click_y
        )
        if not inside or inline is None:
            return None
        if _block_task_state(bl.block) is not None:
            char_idx = max(0, char_idx - 2)
        url = link_url_at_display_offset(inline, char_idx)
        if url is None or not url.startswith(
            ("http://", "https://", "mailto:")
        ):
            return None
        return url

    def _open_link(self, url, timestamp):
        parent = self.get_toplevel()
        if not isinstance(parent, Gtk.Window):
            parent = None
        try:
            return Gtk.show_uri_on_window(parent, url, timestamp)
        except GLib.Error as error:
            print(f"Could not open {url}: {error}", file=sys.stderr)
            return False

    def _start_editing(self, bl, cursor_source_idx=None):
        is_code = bl.block.code_lang is not None
        tv = GtkSource.View() if is_code else Gtk.TextView()
        body_font = resolve_body_font(self.canvas)
        tv.override_font(_code_font_of(body_font) if is_code else body_font)
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.set_left_margin(0)
        tv.set_right_margin(0)
        tv.set_top_margin(0)
        tv.set_bottom_margin(0)
        if is_code:
            tv.set_monospace(True)
            tv.set_auto_indent(True)
            tv.set_indent_on_tab(True)
            tv.set_indent_width(CODE_INDENT_WIDTH)
            tv.set_tab_width(CODE_INDENT_WIDTH)
            tv.set_insert_spaces_instead_of_tabs(True)
            tv.set_smart_backspace(True)
            tv.set_smart_home_end(GtkSource.SmartHomeEndType.BEFORE)
            _apply_code_textview_style(tv, True)
        buf = tv.get_buffer()
        if is_code:
            # GtkSourceView remains useful without language-aware colouring: its
            # buffer still provides bracket matching and its view supplies the
            # source-editing indentation behaviour configured above. Dailyfold's
            # document history remains the sole undo manager.
            buf.set_highlight_syntax(False)
            buf.set_highlight_matching_brackets(True)
            buf.set_max_undo_levels(0)
        buf.set_text(bl.block.text)
        if cursor_source_idx is not None:
            offset = max(0, min(cursor_source_idx, buf.get_char_count()))
            buf.place_cursor(buf.get_iter_at_offset(offset))
        buf.connect("insert-text", self._commit_text_edit)
        buf.connect("delete-range", self._commit_text_edit)
        buf.connect("changed", self._on_buffer_changed)
        tv.connect("focus-out-event", self._on_edit_focus_out)
        tv.connect("key-press-event", self._on_key_press)
        tv.connect("paste-clipboard", self._on_textview_paste)
        tv.connect("button-press-event", self._on_textview_press)
        tv.connect("motion-notify-event", self._on_textview_motion)
        tv.connect("button-release-event", self._on_textview_release)

        self.editing_block = bl.block
        self.edit_view = tv
        self.desired_col = None

        self.add_overlay(tv)
        tv.show()
        tv.grab_focus()
        self.canvas.queue_draw()
        self.queue_resize()
        self.ensure_block_visible(bl.block)

    def _position_overlay(self, overlay, widget, allocation):
        if widget is not self.edit_view or self.editing_block is None:
            return False
        overlay_alloc = overlay.get_allocation()
        self._recompute_layouts(overlay_alloc.width)
        for bl in self.layouts:
            if bl.block is self.editing_block:
                text_x = bl.text_x
                text_width = bl.text_width
                if bl.checkbox_x is not None:
                    text_width += text_x - bl.checkbox_x
                    text_x = bl.checkbox_x
                allocation.x = int(text_x)
                allocation.y = int(bl.y + TEXT_PAD)
                allocation.width = int(text_width)
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
        if not self._suppress_text_snapshot:
            self._reset_coalesce_timer()
            self._notify_change()

    def _on_key_press(self, tv, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        if (
            state
            == Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
            and event.keyval in (Gdk.KEY_a, Gdk.KEY_A)
        ):
            return self._select_all_blocks()
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_a,
            Gdk.KEY_A,
        ):
            if self._buffer_is_fully_selected(tv.get_buffer()):
                return self._enter_selection_mode()
            return False
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_z,
            Gdk.KEY_Z,
        ):
            return self._do_undo()
        if (
            state == Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        ) and event.keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            return self._do_redo()
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_Return,
            Gdk.KEY_KP_Enter,
        ):
            return self._handle_enter(force_split=True)
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_Up,
            Gdk.KEY_Down,
        ):
            return self._handle_fold_command(
                collapsed=event.keyval == Gdk.KEY_Up
            )
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
            if event.keyval == Gdk.KEY_Delete:
                if self._maybe_handle_delete_empty():
                    return True
            if event.keyval == Gdk.KEY_BackSpace:
                if self._maybe_handle_backspace_join():
                    return True
        if state == Gdk.ModifierType.SHIFT_MASK and event.keyval in (
            Gdk.KEY_Tab,
            Gdk.KEY_ISO_Left_Tab,
        ):
            return self._handle_tab(shift=True)
        if state == Gdk.ModifierType.SHIFT_MASK and event.keyval in (
            Gdk.KEY_Up,
            Gdk.KEY_Down,
        ):
            _, l, _ = self._current_position()
            at_top = event.keyval == Gdk.KEY_Up and l == 0
            at_bottom = (
                event.keyval == Gdk.KEY_Down
                and l == self.editing_block.text.count("\n")
            )
            if at_top or at_bottom:
                return self._enter_selection_mode()
            return False
        if state == Gdk.ModifierType.MOD1_MASK and event.keyval in (
            Gdk.KEY_Up,
            Gdk.KEY_Down,
        ):
            return self._enter_selection_mode()
        if (
            state == Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SHIFT_MASK
        ) and event.keyval in (Gdk.KEY_Up, Gdk.KEY_Down):
            return self._handle_move_block_in_edit(
                +1 if event.keyval == Gdk.KEY_Down else -1
            )
        self.desired_col = None
        return False

    def _buffer_is_fully_selected(self, buf):
        start, end = buf.get_bounds()
        if start.equal(end):
            return True
        selected = buf.get_selection_bounds()
        if not selected:
            return False
        sel_start, sel_end = selected
        return sel_start.equal(start) and sel_end.equal(end)

    def _linkify_selection_from_clipboard(self, tv):
        if self.editing_block.code_lang is not None:
            return False
        buf = tv.get_buffer()
        selected = buf.get_selection_bounds()
        if not selected:
            return False
        start, end = selected
        label = buf.get_text(start, end, True)
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        replacement = link_from_paste(label, clipboard.wait_for_text())
        if replacement is None:
            return False

        buf.begin_user_action()
        buf.delete(start, end)
        buf.insert(start, replacement)
        buf.place_cursor(start)
        buf.end_user_action()
        return True

    def _on_textview_paste(self, tv):
        if (
            self._paste_internal_blocks_from_editor()
            or self._linkify_selection_from_clipboard(tv)
        ):
            tv.stop_emission_by_name("paste-clipboard")

    def _capture_cursor(self):
        if self.editing_block is not None:
            idx, line, col = self._current_position()
            return ("edit", idx, line, col)
        if self.selection is not None:
            return ("selection", self.selection[0], self.selection[1])
        return None

    def _begin_structural(self):
        return (
            [
                Block(
                    b.level,
                    b.text,
                    b.code_lang,
                    b.collapsed,
                    b.properties,
                )
                for b in self.blocks
            ],
            self._capture_cursor(),
        )

    def _end_structural(self, pre):
        self._cancel_coalesce_timer()
        pre_blocks, pre_cursor = pre
        self.history.commit_structural(pre_blocks, pre_cursor)
        self._notify_change()

    def _notify_change(self):
        if self.on_change is not None:
            self.on_change()

    def _toggle_task_blocks(self, indices):
        targets = [
            self.blocks[i]
            for i in indices
            if 0 <= i < len(self.blocks)
            and _block_task_state(self.blocks[i]) is not None
        ]
        if not targets:
            return False

        pre = self._begin_structural()
        if self.edit_view is not None:
            self._finish_editing()

        for block in targets:
            block.text = toggle_task_text(block.text)

        self._end_structural(pre)
        self.canvas.queue_draw()
        self.queue_resize()
        return True

    def _toggle_fold(self, block_idx):
        if not (0 <= block_idx < len(self.blocks)):
            return False
        if self._subtree_end(block_idx) == block_idx + 1:
            return False

        pre = self._begin_structural()
        if self.edit_view is not None:
            self._finish_editing()
        self.blocks[block_idx].collapsed = not self.blocks[block_idx].collapsed
        self._end_structural(pre)
        self.canvas.queue_draw()
        self.queue_resize()
        return True

    def _handle_fold_command(self, collapsed):
        if self.editing_block is not None:
            block_idx = self._block_index(self.editing_block)
        elif (
            self.selection is not None
            and self.selection[0] == self.selection[1]
        ):
            block_idx = self.selection[1]
        else:
            return False

        if not (0 <= block_idx < len(self.blocks)):
            return False
        if self._subtree_end(block_idx) == block_idx + 1:
            return True
        block = self.blocks[block_idx]
        if block.collapsed == collapsed:
            return True

        pre = self._begin_structural()
        block.collapsed = collapsed
        self._end_structural(pre)
        self.canvas.queue_draw()
        self.queue_resize()
        return True

    def _commit_text_edit(self, *_):
        if self._suppress_text_snapshot or self.editing_block is None:
            return
        idx = self._block_index(self.editing_block)
        self.history.commit_text(self.blocks, self._capture_cursor(), idx)

    def _cancel_coalesce_timer(self):
        if self._coalesce_timer_id is not None:
            GLib.source_remove(self._coalesce_timer_id)
            self._coalesce_timer_id = None

    def _reset_coalesce_timer(self):
        self._cancel_coalesce_timer()
        self._coalesce_timer_id = GLib.timeout_add(1000, self._on_coalesce_timeout)

    def _on_coalesce_timeout(self):
        self._coalesce_timer_id = None
        self.history.break_coalesce()
        return GLib.SOURCE_REMOVE

    def _do_undo(self):
        if not self.history.undo_stack:
            return True
        cursor = self._capture_cursor()
        if self.edit_view is not None:
            self._finish_editing()
        self.selection = None
        snap = self.history.undo(self.blocks, cursor)
        self._cancel_coalesce_timer()
        self.blocks[:] = snap.blocks
        self._notify_change()
        self._restore_cursor(snap.cursor)
        return True

    def _do_redo(self):
        if not self.history.redo_stack:
            return True
        cursor = self._capture_cursor()
        if self.edit_view is not None:
            self._finish_editing()
        self.selection = None
        snap = self.history.redo(self.blocks, cursor)
        self._cancel_coalesce_timer()
        self.blocks[:] = snap.blocks
        self._notify_change()
        self._restore_cursor(snap.cursor)
        return True

    def _restore_cursor(self, cursor):
        if not self.blocks or cursor is None:
            self.canvas.queue_draw()
            self.queue_resize()
            return
        kind = cursor[0]
        if kind == "selection":
            _, anchor, head = cursor
            n = len(self.blocks)
            self.selection = (max(0, min(anchor, n - 1)), max(0, min(head, n - 1)))
            self._grab_canvas_focus()
            self.canvas.queue_draw()
            self.queue_resize()
            self.ensure_block_visible(self.blocks[self.selection[1]])
            return
        if kind == "edit":
            _, idx, line, col = cursor
            idx = max(0, min(idx, len(self.blocks) - 1))
            self._move_to_block(idx, line, col)

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

    def _move_to_cursor(self, cursor):
        self._move_to_block(
            cursor.block_index,
            cursor.line,
            cursor.column,
        )

    def _visible_neighbor(self, block_idx, direction):
        return visible_neighbor(self.blocks, block_idx, direction)

    def _handle_up(self):
        b, l, c = self._current_position()
        if self.editing_block.code_lang is not None:
            probe = self.edit_view.get_buffer().get_iter_at_mark(
                self.edit_view.get_buffer().get_insert()
            )
            if self.edit_view.backward_display_line(probe):
                self.desired_col = None
                return False
        if self.desired_col is None:
            self.desired_col = c
        if l > 0:
            self._set_cursor_in_current_block(l - 1, self.desired_col)
            return True
        prev_idx = self._visible_neighbor(b, -1)
        if prev_idx is not None:
            prev_lines = self.blocks[prev_idx].text.split("\n")
            self._move_to_block(
                prev_idx, len(prev_lines) - 1, self.desired_col
            )
            return True
        return True

    def _handle_down(self):
        b, l, c = self._current_position()
        if self.editing_block.code_lang is not None:
            probe = self.edit_view.get_buffer().get_iter_at_mark(
                self.edit_view.get_buffer().get_insert()
            )
            if self.edit_view.forward_display_line(probe):
                self.desired_col = None
                return False
        if self.desired_col is None:
            self.desired_col = c
        lines = self.editing_block.text.split("\n")
        if l < len(lines) - 1:
            self._set_cursor_in_current_block(l + 1, self.desired_col)
            return True
        next_idx = self._visible_neighbor(b, +1)
        if next_idx is not None:
            self._move_to_block(next_idx, 0, self.desired_col)
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
        prev_idx = self._visible_neighbor(b, -1)
        if prev_idx is not None:
            prev_lines = self.blocks[prev_idx].text.split("\n")
            self._move_to_block(
                prev_idx, len(prev_lines) - 1, len(prev_lines[-1])
            )
            return True
        return True

    def _subtree_end(self, b):
        return subtree_end(self.blocks, b)

    def _parent_index(self, block_idx):
        return parent_index(self.blocks, block_idx)

    def _shift_levels(self, start, end, shift):
        return shift_levels(self.blocks, start, end, shift)

    def _handle_tab(self, shift):
        if self.editing_block is None:
            return False
        if self.editing_block.code_lang is not None:
            # Let GtkSourceView indent/unindent either the current line or every
            # selected line while preserving the selection.
            return False
        b = self._block_index(self.editing_block)
        pre = self._begin_structural()
        if self._shift_levels(b, self._subtree_end(b), shift):
            self._end_structural(pre)
            self.canvas.queue_draw()
            self.queue_resize()
        return True

    def _move_range(self, start, end, direction):
        return move_range(self.blocks, start, end, direction)

    def _handle_move_block_in_edit(self, direction):
        if self.editing_block is None:
            return False
        b = self._block_index(self.editing_block)
        pre = self._begin_structural()
        if self._move_range(b, self._subtree_end(b), direction) is None:
            return True
        self._end_structural(pre)
        self.canvas.queue_draw()
        self.queue_resize()
        self.ensure_block_visible(self.editing_block)
        return True

    def _handle_enter(self, force_split=False):
        if self.editing_block is None:
            return False
        is_code = self.editing_block.code_lang is not None
        if is_code and not force_split:
            return False
        block = self.editing_block
        b = self._block_index(block)
        has_children = self._subtree_end(b) > b + 1

        if (
            not force_split
            and not block.text
            and block.level > 0
            and not has_children
        ):
            pre = self._begin_structural()
            self._shift_levels(b, b + 1, shift=True)
            self._end_structural(pre)
            self.canvas.queue_draw()
            self.queue_resize()
            return True

        buf = self.edit_view.get_buffer()
        offset = buf.get_iter_at_mark(buf.get_insert()).get_offset()

        if not is_code and not force_split and offset == len(block.text):
            m = CODE_FENCE_RE.match(block.text)
            if m is not None:
                return self._convert_to_code_block(m.group(1))

        pre = self._begin_structural()

        cursor = split_block(self.blocks, b, offset)

        self._suppress_text_snapshot = True
        try:
            buf.set_text(block.text)
        finally:
            self._suppress_text_snapshot = False

        self._end_structural(pre)
        self._move_to_cursor(cursor)
        return True

    def _convert_to_code_block(self, lang):
        block = self.editing_block
        buf = self.edit_view.get_buffer()
        pre = self._begin_structural()
        block_idx = self._block_index(block)
        block.code_lang = lang
        self._suppress_text_snapshot = True
        try:
            buf.set_text("")
        finally:
            self._suppress_text_snapshot = False
        self._end_structural(pre)
        # The fence was entered in a plain TextView; replace it with the source
        # view now that the block has become code.
        self._move_to_block(block_idx, 0, 0)
        return True

    def _revert_code_block(self):
        block = self.editing_block
        pre = self._begin_structural()
        block_idx = self._block_index(block)
        block.code_lang = None
        self._end_structural(pre)
        # Empty-code Backspace turns the block back into prose, including its
        # editor widget and keyboard behaviour.
        self._move_to_block(block_idx, 0, 0)
        return True

    def _maybe_handle_backspace_join(self):
        if self.editing_block is None:
            return False
        if self.edit_view.get_buffer().get_selection_bounds():
            return False
        b, l, c = self._current_position()
        if l != 0 or c != 0:
            return False
        if self.editing_block.code_lang is not None and self.editing_block.text == "":
            return self._revert_code_block()
        prev_idx = self._visible_neighbor(b, -1)
        if prev_idx is None:
            return False

        pre = self._begin_structural()
        cursor = join_with_previous(self.blocks, b, prev_idx)

        self._end_structural(pre)
        self._move_to_cursor(cursor)
        return True

    def _maybe_handle_delete_empty(self):
        if self.editing_block is None or self.editing_block.text:
            return False
        b = self._block_index(self.editing_block)
        if b + 1 >= len(self.blocks):
            return False

        pre = self._begin_structural()
        cursor = delete_empty_forward(self.blocks, b)

        self._end_structural(pre)
        self._move_to_cursor(cursor)
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
        next_idx = self._visible_neighbor(b, +1)
        if next_idx is not None:
            self._move_to_block(next_idx, 0, 0)
            return True
        return True

    def _selection_indices(self):
        return selection_indices(self.blocks, self.selection)

    def _enter_selection_mode(self):
        if self.editing_block is None:
            return False
        idx = self._block_index(self.editing_block)
        self._finish_editing()
        self.selection = (idx, idx)
        self._grab_canvas_focus()
        self.canvas.queue_draw()
        return True

    def _select_all_blocks(self):
        if not self.blocks:
            return True
        self._finish_editing()
        self.selection = (0, len(self.blocks) - 1)
        self._grab_canvas_focus()
        self.canvas.queue_draw()
        return True

    def _on_canvas_key_press(self, widget, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        if (
            state
            == Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
            and event.keyval in (Gdk.KEY_a, Gdk.KEY_A)
        ):
            return self._select_all_blocks()
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_c,
            Gdk.KEY_C,
        ):
            return self._copy_block_selection(cut=False)
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_x,
            Gdk.KEY_X,
        ):
            return self._copy_block_selection(cut=True)
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_v,
            Gdk.KEY_V,
        ):
            return self._paste_blocks_from_clipboard()
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_a,
            Gdk.KEY_A,
        ):
            return self._expand_block_selection()
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_z,
            Gdk.KEY_Z,
        ):
            return self._do_undo()
        if (
            state == Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        ) and event.keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            return self._do_redo()
        if state == Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_Up,
            Gdk.KEY_Down,
        ):
            return self._handle_fold_command(
                collapsed=event.keyval == Gdk.KEY_Up
            )
        if self.selection is None:
            return False
        anchor, head = self.selection
        n = len(self.blocks)
        if n == 0:
            return False

        if state == 0:
            if event.keyval == Gdk.KEY_Up:
                indices = self._selection_indices()
                new = self._visible_neighbor(indices[0], -1)
                if new is None:
                    new = indices[0]
                self.selection = (new, new)
                self.canvas.queue_draw()
                self.ensure_block_visible(self.blocks[new])
                return True
            if event.keyval == Gdk.KEY_Down:
                indices = self._selection_indices()
                visible_in_selection = [
                    i for i in visible_block_indices(self.blocks) if i in indices
                ]
                new = self._visible_neighbor(visible_in_selection[-1], +1)
                if new is None:
                    new = visible_in_selection[-1]
                self.selection = (new, new)
                self.canvas.queue_draw()
                self.ensure_block_visible(self.blocks[new])
                return True
            if event.keyval == Gdk.KEY_Left:
                return self._exit_selection_to_edit(at_end=False)
            if event.keyval == Gdk.KEY_Right:
                return self._exit_selection_to_edit(at_end=True)
            if event.keyval == Gdk.KEY_Escape:
                self.selection = None
                self.canvas.queue_draw()
                return True
            if event.keyval == Gdk.KEY_Tab:
                return self._handle_selection_indent(shift=False)
            if event.keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete):
                return self._handle_selection_delete()

        if state in (Gdk.ModifierType.SHIFT_MASK, Gdk.ModifierType.MOD1_MASK):
            if event.keyval == Gdk.KEY_Up:
                new_head = self._visible_neighbor(head, -1)
                if new_head is not None:
                    self.selection = (anchor, new_head)
                    self.ensure_block_visible(self.blocks[new_head])
                self.canvas.queue_draw()
                return True
            if event.keyval == Gdk.KEY_Down:
                new_head = self._visible_neighbor(head, +1)
                if new_head is not None:
                    self.selection = (anchor, new_head)
                    self.ensure_block_visible(self.blocks[new_head])
                self.canvas.queue_draw()
                return True

        if state == Gdk.ModifierType.SHIFT_MASK and event.keyval in (
            Gdk.KEY_Tab,
            Gdk.KEY_ISO_Left_Tab,
        ):
            return self._handle_selection_indent(shift=True)

        if (
            state == Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SHIFT_MASK
        ) and event.keyval in (Gdk.KEY_Up, Gdk.KEY_Down):
            return self._handle_move_selection(
                +1 if event.keyval == Gdk.KEY_Down else -1
            )

        return False

    def _copy_block_selection(self, cut):
        if self.selection is None:
            return False
        indices = self._selection_indices()
        selected = [self.blocks[i] for i in indices]
        copied = copy_blocks(selected)
        self._clipboard_plain_text = blocks_to_clipboard_text(copied)
        self._clipboard_html = blocks_to_clipboard_html(copied)
        self._clipboard_payload = blocks_to_clipboard_payload(copied)
        publish_clipboard(
            self.canvas,
            self._clipboard_targets,
            self._clipboard_plain_text,
        )
        if cut:
            self._handle_selection_delete()
        return True

    def _on_clipboard_selection_get(self, widget, selection_data, info, time):
        if info == CLIPBOARD_BLOCKS_INFO and self._clipboard_payload is not None:
            data = self._clipboard_payload.encode("utf-8")
            selection_data.set(self._clipboard_atoms[info], 8, list(data))
        elif info == CLIPBOARD_HTML_INFO and self._clipboard_html is not None:
            data = self._clipboard_html.encode("utf-8")
            selection_data.set(self._clipboard_atoms[info], 8, list(data))
        elif self._clipboard_plain_text is not None:
            selection_data.set_text(self._clipboard_plain_text, -1)

    def _read_blocks_from_clipboard(self, allow_plain_text):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        blocks_atom = self._clipboard_atoms[CLIPBOARD_BLOCKS_INFO]
        pasted = None
        if clipboard.wait_is_target_available(blocks_atom):
            selection_data = clipboard.wait_for_contents(blocks_atom)
            if selection_data is not None:
                raw = selection_data.get_data()
                if raw is not None:
                    try:
                        payload = bytes(raw).decode("utf-8")
                    except (TypeError, UnicodeDecodeError):
                        payload = None
                    pasted = blocks_from_clipboard_payload(payload)

        if pasted is None and allow_plain_text:
            text = clipboard.wait_for_text()
            if text is None:
                return None
            pasted = blocks_from_clipboard_text(text)
        return pasted

    def _insert_pasted_blocks(self, pasted, insert_idx, destination_level, pre):
        self.selection = insert_blocks(
            self.blocks,
            pasted,
            insert_idx,
            destination_level,
        )
        self._end_structural(pre)
        self._grab_canvas_focus()
        self.canvas.queue_draw()
        self.queue_resize()
        return True

    def _paste_internal_blocks_from_editor(self):
        pasted = self._read_blocks_from_clipboard(allow_plain_text=False)
        if not pasted:
            return False

        target_idx = self._block_index(self.editing_block)
        target = self.blocks[target_idx]
        replace_empty_block = (
            target.text == ""
            and target.code_lang is None
            and not target.properties
        )
        pre = self._begin_structural()
        self._finish_editing()
        if replace_empty_block:
            insert_idx = target_idx
            destination_level = target.level
            del self.blocks[target_idx]
        else:
            insert_idx = self._subtree_end(target_idx)
            destination_level = target.level
        return self._insert_pasted_blocks(
            pasted, insert_idx, destination_level, pre
        )

    def _paste_blocks_from_clipboard(self):
        pasted = self._read_blocks_from_clipboard(allow_plain_text=True)
        if not pasted:
            return True

        pre = self._begin_structural()
        if self.selection is None:
            insert_idx = len(self.blocks)
            destination_level = 0
        else:
            indices = self._selection_indices()
            insert_idx = indices[-1] + 1
            destination_level = min(self.blocks[i].level for i in indices)

        return self._insert_pasted_blocks(
            pasted, insert_idx, destination_level, pre
        )

    def _expand_block_selection(self):
        expanded = expand_selection(self.blocks, self.selection)
        if expanded is None:
            return False
        self.selection = expanded
        self.canvas.queue_draw()
        return True

    def _handle_selection_indent(self, shift):
        if self.selection is None:
            return False
        indices = self._selection_indices()
        start, end = indices[0], indices[-1] + 1
        pre = self._begin_structural()
        if self._shift_levels(start, end, shift):
            self._end_structural(pre)
            self.canvas.queue_draw()
        return True

    def _handle_selection_delete(self):
        if self.selection is None:
            return False
        indices = self._selection_indices()
        start, end = indices[0], indices[-1] + 1
        pre = self._begin_structural()
        cursor = delete_range(self.blocks, start, end)
        self.selection = None
        self._end_structural(pre)
        if cursor is None:
            self.canvas.queue_draw()
            return True
        self._move_to_cursor(cursor)
        return True

    def _handle_move_selection(self, direction):
        if self.selection is None:
            return False
        indices = self._selection_indices()
        start, end = indices[0], indices[-1] + 1
        anchor, head = self.selection
        pre = self._begin_structural()
        result = self._move_range(start, end, direction)
        if result is None:
            return True
        self._end_structural(pre)
        new_start, _ = result
        delta = new_start - start
        self.selection = (anchor + delta, head + delta)
        self.canvas.queue_draw()
        self.queue_resize()
        self.ensure_block_visible(self.blocks[self.selection[1]])
        return True

    def _exit_selection_to_edit(self, at_end):
        indices = self._selection_indices()
        visible = [i for i in visible_block_indices(self.blocks) if i in indices]
        target_idx = visible[-1] if at_end else visible[0]
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

    def _on_textview_press(self, tv, event):
        if event.button != 1:
            return False
        if self.editing_block is None:
            return False
        if self._completes_edit_activation_click(event, self.editing_block):
            offset = self._edit_activation_click[4]
            self._edit_activation_click = None
            self._drag_anchor_idx = None
            self._drag_anchor_offset = None
            return self._select_word_at_offset(tv, offset)
        self._edit_activation_click = None
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        self._drag_anchor_idx = self._block_index(self.editing_block)
        self._drag_anchor_offset = None
        return False

    def _on_textview_motion(self, tv, event):
        if self._drag_anchor_idx is None or self.editing_block is None:
            return False
        coords = tv.translate_coordinates(self.canvas, event.x, event.y)
        if coords is None:
            return False
        cx, cy = coords
        target_bl = self._block_at_y(cy)
        if target_bl is None:
            return False
        cur_idx = self._block_index(target_bl.block)
        if cur_idx == self._drag_anchor_idx:
            return False
        anchor = self._drag_anchor_idx
        self._finish_editing()
        self.selection = (anchor, cur_idx)
        self._grab_canvas_focus()
        self.canvas.queue_draw()
        return True

    def _on_textview_release(self, tv, event):
        self._drag_anchor_idx = None
        self._drag_anchor_offset = None
        return False

    def _on_canvas_motion(self, widget, event):
        self._update_interaction_hover(event.x, event.y)
        if self._drag_anchor_idx is None:
            return False
        target_bl = self._block_at_y(event.y)
        if target_bl is None:
            return False
        cur_idx = self._block_index(target_bl.block)
        if self.editing_block is not None:
            if cur_idx == self._drag_anchor_idx:
                cur_offset = self._cursor_from_click(target_bl, event.x, event.y)
                buf = self.edit_view.get_buffer()
                anchor_iter = buf.get_iter_at_offset(self._drag_anchor_offset)
                cur_iter = buf.get_iter_at_offset(cur_offset)
                buf.select_range(cur_iter, anchor_iter)
                return False
            anchor = self._drag_anchor_idx
            self._finish_editing()
            self.selection = (anchor, cur_idx)
            self._grab_canvas_focus()
            self.canvas.queue_draw()
            return False
        if self.selection is not None:
            anchor = self.selection[0]
            if (anchor, cur_idx) != self.selection:
                self.selection = (anchor, cur_idx)
                self.canvas.queue_draw()
        return False

    def _on_button_release(self, widget, event):
        self._drag_anchor_idx = None
        self._drag_anchor_offset = None
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
        self.queue_resize()
