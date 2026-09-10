# TODO

Everything we've discussed but haven't built yet. Grouped roughly in order of what we'd probably want next.

## Editor

- **Double click to select word** - when not focused. Logseq sort of achieves this, but it's tricky.
- **More advanced multi-line code editing** - tab intent/unindent, auto-indent, syntax highlighting. consider enriching TextView vs dropping in GtkSource.View

## Markdown rendering

- **More inline syntax** — links `[text](url)`, autolinks, and strikethrough. Current parser handles `**bold**`, `*italic*`, `` `code` ``, and backslash escapes; no nesting.
- **Code styling** — `<tt>` gets monospace but no background; once we have theme-aware colors, give code a subtle bg.

## Persistence / journaling (the actual app)

The app now stores one ISO-dated Markdown file per day in an XDG data directory,
with a configurable override, a persistent calendar sidebar, and a scrolling
editor. Remaining:

- **Search** — cross-file full-text across all days. Triggered by keyboard shortcut (Ctrl+K / Ctrl+Shift+F). Modal/overlay with incremental results as you type; each result shows the date, the block, and surrounding context with the match highlighted. Enter jumps to the day + scrolls/focuses the block. Start naive (scan files on each query — fine up to thousands of days); add an index later if it gets slow. Scope: plain substring first, regex / token-based filtering later.
- **Backlinks / page links / tags** — deferred; decide later whether to mimic Logseq here or do something simpler.

## Deferred (explicit not-now)

- **Dark mode** — light colors only for v1. When revisited, pull colors from live `Gtk.StyleContext` rather than hardcoding a dark palette.
- **Partial cross-block selection** — explicitly out of scope per editor-model memory. Within-block selection uses TextView natively.
- **GTK4** — we chose GTK3 for simplicity. Revisit only if we hit CPU-rendering walls.
