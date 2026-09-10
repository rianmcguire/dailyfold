# dailyfold

A daily-journal outliner. GTK3 + Cairo; markdown on disk, one file per day.

Very early. See [TODO.md](TODO.md) for what's planned.

The GUI currently loads `example.md` from the repository and automatically
saves edits back to it after a short debounce. This hard-coded path is temporary
until XDG storage configuration and calendar navigation are added.

## Dependencies

- Python 3
- GTK 3 with Broadway backend (`libgtk-3-0`, `gir1.2-gtk-3.0`, `libgtk-3-bin` for `broadwayd`)
- `python3-gi`, `python3-cairo`, `gir1.2-pangocairo-1.0`

On Debian/Ubuntu:

```
sudo apt install python3-gi python3-cairo gir1.2-gtk-3.0 gir1.2-pangocairo-1.0 libgtk-3-bin
```

## Running

### Native GTK

```
python3 app.py
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

### Snapshot mode

Render the current `BLOCKS` to a PNG without opening a window:

```
python3 app.py --snapshot [path]
```

Defaults to `snapshots/latest.png`. Useful for quick visual diffs in CI or when no display is available.

### Native UI harness (for agent-driven testing)

The repo includes a persistent Xvfb harness that sends native X11 mouse and
keyboard events with `xdotool`. Each input command automatically captures the
resulting GTK window to `.ui-harness/latest.png`.

On Fedora, install the harness and app dependencies with:

```
sudo dnf install gtk3 python3-gobject python3-cairo xorg-x11-server-Xvfb xdotool
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
