"""Top-level Dailyfold application window."""

import os
import sys
from datetime import date

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from blocks_view import BlocksView
from block_markdown import MarkdownDocument
from model import Block
from search_dialog import SearchDialog, format_journal_date
from storage import (
    journal_dates,
    journal_path,
    load_document,
    save_journal_document,
)


SIDEBAR_WIDTH = 230


def empty_journal_document():
    # A visible empty block means a new day is immediately editable without
    # creating a file merely by visiting it.
    return MarkdownDocument([Block(0, "")])


class AppWindow(Gtk.Window):
    def __init__(self, data_dir, initial_day=None):
        super().__init__(title="dailyfold")
        self.set_icon_name("dailyfold")
        self.data_dir = os.path.abspath(os.path.expanduser(data_dir))
        self.current_day = initial_day or date.today()
        self.document = self._load_day(self.current_day)
        self.file_path = journal_path(self.data_dir, self.current_day)
        self._save_timer_id = None
        self._dirty = False
        self._calendar_syncing = False

        self.set_default_size(920, 600)
        self.connect("delete-event", self._on_delete)
        self.connect("destroy", self._on_destroy)
        self.connect("key-press-event", self._on_window_key_press)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(root)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar.set_size_request(SIDEBAR_WIDTH, -1)
        sidebar.set_hexpand(False)
        sidebar.set_border_width(12)
        root.pack_start(sidebar, False, False, 0)

        self.calendar = Gtk.Calendar()
        self._select_calendar_day(self.current_day)
        self.calendar.connect("day-selected", self._on_calendar_day_selected)
        self.calendar.connect("month-changed", self._on_calendar_month_changed)
        sidebar.pack_start(self.calendar, False, False, 0)

        today_button = Gtk.Button(label="Today")
        today_button.connect("clicked", self._on_today_clicked)
        sidebar.pack_start(today_button, False, False, 0)

        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(separator, False, False, 0)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_hexpand(True)
        self.scroller.set_vexpand(True)
        root.pack_start(self.scroller, True, True, 0)

        self.view = BlocksView(
            format_journal_date(self.current_day),
            self.document.blocks,
            on_change=self._schedule_save,
        )
        self.scroller.add(self.view)
        self._refresh_calendar_marks()

    def _load_day(self, day):
        try:
            document = load_document(journal_path(self.data_dir, day))
        except FileNotFoundError:
            return empty_journal_document()
        if not document.blocks:
            document.blocks.append(Block(0, ""))
        return document

    def _select_calendar_day(self, day):
        self._calendar_syncing = True
        self.calendar.select_month(day.month - 1, day.year)
        self.calendar.select_day(day.day)
        self._calendar_syncing = False

    def _refresh_calendar_marks(self):
        year, month_zero, _ = self.calendar.get_date()
        self.calendar.clear_marks()
        try:
            existing_days = journal_dates(self.data_dir)
        except OSError as error:
            print(f"Could not read {self.data_dir}: {error}", file=sys.stderr)
            return
        for day in existing_days:
            if day.year == year and day.month == month_zero + 1:
                self.calendar.mark_day(day.day)

    def _on_calendar_month_changed(self, calendar):
        self._refresh_calendar_marks()

    def _on_calendar_day_selected(self, calendar):
        if self._calendar_syncing:
            return
        year, month_zero, day_of_month = calendar.get_date()
        if not day_of_month:
            return
        selected_day = date(year, month_zero + 1, day_of_month)
        if not self._open_day(selected_day):
            self._select_calendar_day(self.current_day)
            self._refresh_calendar_marks()

    def _on_today_clicked(self, button):
        today = date.today()
        if self._open_day(today):
            self._select_calendar_day(today)
            self._refresh_calendar_marks()

    def _on_window_key_press(self, window, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        search_modifiers = (
            Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        )
        if state != search_modifiers or event.keyval not in (
            Gdk.KEY_f,
            Gdk.KEY_F,
        ):
            return False
        self._show_search()
        return True

    def _show_search(self):
        if not self._save_current():
            self._show_error(
                "Could not save this journal page",
                f"Search was not opened. Check that {self.file_path} is writable.",
            )
            return

        dialog = SearchDialog(self, self.data_dir)
        response = dialog.run()
        result = dialog.selected_result
        dialog.destroy()
        if response != Gtk.ResponseType.OK or result is None:
            return

        if self._open_day(result.day):
            self._select_calendar_day(result.day)
            self._refresh_calendar_marks()
            self.view.focus_search_result(
                result.block_index,
                result.match_start,
                result.match_end,
            )

    def _open_day(self, day):
        if day == self.current_day:
            return True
        if not self._save_current():
            self._show_error(
                "Could not save this journal page",
                f"The page was not changed. Check that {self.file_path} is writable.",
            )
            return False
        try:
            document = self._load_day(day)
        except OSError as error:
            self._show_error("Could not open journal page", str(error))
            return False

        self.current_day = day
        self.document = document
        self.file_path = journal_path(self.data_dir, day)
        self._dirty = False
        self.view.set_page(format_journal_date(day), document.blocks)
        GLib.idle_add(self._scroll_to_top)
        return True

    def _scroll_to_top(self):
        adjustment = self.scroller.get_vadjustment()
        adjustment.set_value(adjustment.get_lower())
        return GLib.SOURCE_REMOVE

    def _show_error(self, title, detail):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
        )
        dialog.format_secondary_text(detail)
        dialog.run()
        dialog.destroy()

    def _schedule_save(self):
        self._dirty = True
        if self._save_timer_id is not None:
            GLib.source_remove(self._save_timer_id)
        self._save_timer_id = GLib.timeout_add(500, self._save_now)

    def _save_now(self):
        self._save_timer_id = None
        self._write_current_document()
        return GLib.SOURCE_REMOVE

    def _write_current_document(self):
        if not self._dirty:
            return True
        self.document.blocks = self.view.blocks
        try:
            save_journal_document(self.file_path, self.document)
        except OSError as error:
            print(f"Could not save {self.file_path}: {error}", file=sys.stderr)
            return False
        self._dirty = False
        self._refresh_calendar_marks()
        return True

    def _save_current(self):
        if self._save_timer_id is not None:
            GLib.source_remove(self._save_timer_id)
            self._save_timer_id = None
        return self._write_current_document()

    def _on_delete(self, widget, event):
        if self._save_current():
            return False
        self._show_error(
            "Could not save this journal page",
            f"dailyfold will stay open. Check that {self.file_path} is writable.",
        )
        return True

    def _on_destroy(self, widget):
        Gtk.main_quit()
