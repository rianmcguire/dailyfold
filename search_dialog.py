"""Keyboard-first journal search dialog."""

import re
from html import escape as html_escape

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk, Pango

from search import search_journals


SEARCH_RESULT_LIMIT = 50
SEARCH_MATCH_BG = "#fff0a8"
SEARCH_MATCH_FG = "#222222"


def _search_result_markup(text, query):
    """Return escaped, single-line text with every query match highlighted."""
    display_text = " ".join(text.splitlines())
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    parts = []
    position = 0
    for match in pattern.finditer(display_text):
        parts.append(html_escape(display_text[position : match.start()]))
        parts.append(
            f'<span background="{SEARCH_MATCH_BG}" '
            f'foreground="{SEARCH_MATCH_FG}">'
            f"{html_escape(match.group(0))}</span>"
        )
        position = match.end()
    parts.append(html_escape(display_text[position:]))
    return "".join(parts)


def format_journal_date(day):
    return f"{day.isoformat()} {day.strftime('%A')}"


class SearchDialog(Gtk.Dialog):
    """Keyboard-first cross-journal search palette."""

    def __init__(self, parent, data_dir):
        super().__init__(title="Search", transient_for=parent, modal=True)
        self.data_dir = data_dir
        self.selected_result = None
        self.result_rows = []

        self.set_default_size(680, 440)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)

        content = self.get_content_area()
        content.set_spacing(10)
        content.set_border_width(14)

        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("Search blocks")
        self.entry.connect("search-changed", self._on_search_changed)
        self.entry.connect("key-press-event", self._on_entry_key_press)
        content.pack_start(self.entry, False, False, 0)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        self.scroller.set_hexpand(True)
        self.scroller.set_vexpand(True)
        content.pack_start(self.scroller, True, True, 0)

        self.results = Gtk.ListBox()
        self.results.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.results.set_activate_on_single_click(True)
        self.results.connect("row-activated", self._on_row_activated)
        self.scroller.add(self.results)

        self.status = Gtk.Label(label="Type to search")
        self.status.set_xalign(0)
        self.status.get_style_context().add_class("dim-label")
        content.pack_start(self.status, False, False, 0)

        self.show_all()
        self.entry.grab_focus()

    def _clear_results(self):
        for child in self.results.get_children():
            self.results.remove(child)
        self.result_rows = []

    def _on_search_changed(self, entry):
        query = entry.get_text()
        self._clear_results()
        if not query:
            self.status.set_text("Type to search")
            return

        try:
            matches = search_journals(
                self.data_dir,
                query,
                limit=SEARCH_RESULT_LIMIT + 1,
            )
        except OSError as error:
            self.status.set_text(f"Could not search journals: {error}")
            return

        capped = len(matches) > SEARCH_RESULT_LIMIT
        visible_matches = matches[:SEARCH_RESULT_LIMIT]
        for result in visible_matches:
            row = self._result_row(result, query)
            self.results.add(row)
            self.result_rows.append(row)

        if visible_matches:
            count = len(visible_matches)
            suffix = "+" if capped else ""
            self.status.set_text(
                f"{count}{suffix} result{'s' if count != 1 else ''}"
            )
            self.results.select_row(self.result_rows[0])
        else:
            self.status.set_text("No matches")
        self.results.show_all()

    def _result_row(self, result, query):
        row = Gtk.ListBoxRow()
        row.search_result = result

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(10)
        box.set_margin_end(10)
        row.add(box)

        breadcrumb_parts = [format_journal_date(result.day)]
        breadcrumb_parts.extend(
            part for part in result.ancestors if part
        )
        breadcrumb = Gtk.Label(label=" › ".join(breadcrumb_parts))
        breadcrumb.set_xalign(0)
        breadcrumb.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        breadcrumb.get_style_context().add_class("dim-label")
        box.pack_start(breadcrumb, False, False, 0)

        matched_block = Gtk.Label()
        matched_block.set_xalign(0)
        matched_block.set_line_wrap(True)
        matched_block.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        matched_block.set_lines(2)
        matched_block.set_ellipsize(Pango.EllipsizeMode.END)
        matched_block.set_markup(_search_result_markup(result.text, query))
        box.pack_start(matched_block, False, False, 0)
        return row

    def _on_row_activated(self, listbox, row):
        self.selected_result = row.search_result
        self.response(Gtk.ResponseType.OK)

    def _move_selection(self, direction):
        if not self.result_rows:
            return
        selected = self.results.get_selected_row()
        if selected is None:
            index = 0 if direction > 0 else len(self.result_rows) - 1
        else:
            index = self.result_rows.index(selected)
            index = max(0, min(len(self.result_rows) - 1, index + direction))
        row = self.result_rows[index]
        self.results.select_row(row)

        allocation = row.get_allocation()
        adjustment = self.scroller.get_vadjustment()
        if allocation.y < adjustment.get_value():
            adjustment.set_value(allocation.y)
        elif allocation.y + allocation.height > (
            adjustment.get_value() + adjustment.get_page_size()
        ):
            adjustment.set_value(
                allocation.y + allocation.height - adjustment.get_page_size()
            )

    def _on_entry_key_press(self, entry, event):
        if event.keyval == Gdk.KEY_Down:
            self._move_selection(+1)
            return True
        if event.keyval == Gdk.KEY_Up:
            self._move_selection(-1)
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            row = self.results.get_selected_row()
            if row is not None:
                self._on_row_activated(self.results, row)
                return True
        if event.keyval == Gdk.KEY_Escape:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        return False

