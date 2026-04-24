# dailyfold

A daily-journal outliner. GTK3 + Cairo; markdown on disk, one file per day.

Very early. See [TODO.md](TODO.md) for what's planned.

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
