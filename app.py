"""Dailyfold entry point."""

import argparse
import os
import signal
import sys
from datetime import date

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from storage import default_data_dir, seed_journal_from_template
from window import AppWindow


APPLICATION_NAME = "dailyfold"
PROGRAM_NAME = "dailyfold"
EXAMPLE_JOURNAL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "example.md"
)


def main():
    GLib.set_prgname(PROGRAM_NAME)
    GLib.set_application_name(APPLICATION_NAME)
    Gdk.set_program_class(APPLICATION_NAME)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help=(
            "journal directory (default: $DAILYFOLD_DATA_DIR, then "
            "$XDG_DATA_HOME/dailyfold)"
        ),
    )
    args = parser.parse_args()

    data_dir = args.data_dir or default_data_dir()
    today = date.today()
    try:
        seed_journal_from_template(data_dir, today, EXAMPLE_JOURNAL_PATH)
    except OSError as error:
        print(f"Could not initialize {data_dir}: {error}", file=sys.stderr)

    window = AppWindow(data_dir, initial_day=today)
    window.show_all()

    def graceful_quit():
        window.close()
        return GLib.SOURCE_REMOVE

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, graceful_quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, graceful_quit)

    Gtk.main()


if __name__ == "__main__":
    main()
