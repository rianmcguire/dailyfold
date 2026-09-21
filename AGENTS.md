## Features

The GUI opens today's journal, automatically saves edits after a short debounce,
and uses one `yyyy_mm_dd.md` Markdown file per day. The calendar sidebar navigates
between days and marks dates that already have a file.

Press `Ctrl+Shift+F` to search block text across every journal. Results are shown
newest day first, capped at 50, with their date and ancestor blocks as breadcrumb
context. Open a result to jump to the block with the matching text selected.

Inline Markdown supports `**bold**`, `*italic*`, `` `code` ``, `~~strikethrough~~`,
backslash escapes, `[label](destination)` links, angle-bracket autolinks, and bare
HTTP(S) URLs. Emphasis and strikethrough can be nested.
Hold Ctrl and click a rendered web or email link to open it with the system
handler; an ordinary click continues to enter editing mode.

## Development

### Running

```
python3 app.py
```

Journal files default to `$XDG_DATA_HOME/dailyfold/`, or
`~/.local/share/dailyfold/` when `XDG_DATA_HOME` is unset. Override that location
with either `--data-dir PATH` or the `DAILYFOLD_DATA_DIR` environment variable:

```
python3 app.py --data-dir ~/Documents/journal
```

### Via Broadway (for remote dev)

Broadway renders GTK to an HTTP/WebSocket client, which is useful when developing over SSH or in a sandboxed environment without a display.

Start the Broadway daemon (once; it runs in the background):

```
broadwayd --address 0.0.0.0 --port 8086 :5
```

Then run the app pointed at that display:

```
GDK_BACKEND=broadway BROADWAY_DISPLAY=:5 python3 app.py
```

Open `http://<host>:8086/` in a browser.

To restart after code changes, kill the `python3 app.py` process and re-run it; `broadwayd` can stay up.

### Native UI harness (for agent-driven testing)

The repo includes a persistent Xvfb harness that sends native X11 mouse and
keyboard events with `xdotool`. Each input command automatically captures the
resulting GTK window to `.ui-harness/latest.png`.

On Fedora, install the harness and app dependencies with:

```
sudo dnf install xorg-x11-server-Xvfb xdotool
```

Start a session, interact with window-relative coordinates, and stop it with:

```
scripts/ui.py start
scripts/ui.py click 180 78
scripts/ui.py type "edited text"
scripts/ui.py key ctrl+z
scripts/ui.py drag 100 80 100 160
scripts/ui.py shot snapshots/manual-check.png
scripts/ui.py stop
```

Use `scripts/ui.py status` for the display, process IDs, and window geometry,
or `scripts/ui.py logs` if the app exits. Set `DAILYFOLD_UI_DISPLAY=:N` before
`start` to request a particular free X display.
