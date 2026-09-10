# TODO

Everything we've discussed but haven't built yet. Grouped roughly in order of what we'd probably want next.

## Editor

- **Clipboard** - we should be able to cut/copy/paste block(s), both for internal reorganization and external consumption
- **Double click to select word** - when not focused. Logseq sort of achieves this, but it's tricky.
- **More advanced multi-line code editing** - tab intent/unindent, auto-indent, syntax highlighting. consider enriching TextView vs dropping in GtkSource.View

## Markdown rendering

- **More inline syntax** — links `[text](url)`, autolinks, strikethrough, backslash escapes. Current parser handles `**bold**`, `*italic*`, `` `code` ``; no nesting.
- **Code styling** — `<tt>` gets monospace but no background; once we have theme-aware colors, give code a subtle bg.
- **File-format parser** — parsing a whole `YYYY-MM-DD.md` into the `Block(level, text)` tree (nested bullets via indentation) is the other place markdown shows up. Re-evaluate `markdown-it-py` here when we build the loader; its token stream + line maps suit block parsing better than hand-rolling.

## Persistence / journaling (the actual app)

We are a "daily journal" but have none of this yet:

- **Scrolling**
- **File format** — markdown on disk, one file per day (`YYYY-MM-DD.md`), nested bullets via indentation. Must load the user's existing Logseq files; follow Logseq conventions over CommonMark where they differ. Known divergence: a bare `\n` inside a block is a hard line break in Logseq (serialized as plain `\n`, no trailing `  ` or `\\`), not a CommonMark soft break. Test rendering + round-trip against real Logseq files.
  - blocks with multi-line code blocks can't have other content. the loader should handle this and split the input if needed
- **Storage location** — configurable; default to something like `~/Documents/dailyfold/` or XDG data dir.
- **Load on startup** — today's file, or most recent.
- **Save on edit** — debounced write on every change; no explicit save action.
- **Fold persistence** — decide whether the in-memory fold state becomes a Logseq-compatible `collapsed:: true` block property or sidecar state when loading/saving is built.
- **Date navigation** — jump to today, previous/next day via keyboard (probably Ctrl+. / Ctrl+, or similar). Always-visible "today" shortcut.
- **Calendar day picker** — month-grid popup (or persistent sidebar?) to jump to an arbitrary date. Highlight days that have a file on disk so empty days are visually distinct. Arrow keys navigate the grid; Enter opens. Consider showing a small content preview or block-count per day on hover.
- **Search** — cross-file full-text across all days. Triggered by keyboard shortcut (Ctrl+K / Ctrl+Shift+F). Modal/overlay with incremental results as you type; each result shows the date, the block, and surrounding context with the match highlighted. Enter jumps to the day + scrolls/focuses the block. Start naive (scan files on each query — fine up to thousands of days); add an index later if it gets slow. Scope: plain substring first, regex / token-based filtering later.
- **Backlinks / page links / tags** — deferred; decide later whether to mimic Logseq here or do something simpler.

## Deferred (explicit not-now)

- **Dark mode** — light colors only for v1. When revisited, pull colors from live `Gtk.StyleContext` rather than hardcoding a dark palette.
- **Partial cross-block selection** — explicitly out of scope per editor-model memory. Within-block selection uses TextView natively.
- **GTK4** — we chose GTK3 for simplicity. Revisit only if we hit CPU-rendering walls.
