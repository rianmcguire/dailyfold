# TODO

Everything we've discussed but haven't built yet. Grouped roughly in order of what we'd probably want next.

## Editor

- **Folding** — collapse/expand a block's descendants. Toggle via click on bullet (bullet style changes to indicate collapsed state) and/or keyboard (Logseq uses Tab on a non-editing block, or a dedicated shortcut — pick one that doesn't collide with indent). Navigation (↑/↓) should skip over hidden descendants. Selecting/moving/deleting a folded block acts on the whole subtree. Persistence: two options worth weighing — (a) Logseq-compatible `collapsed:: true` block property, which round-trips folds through shared files but adds visible noise to the `.md`; (b) a sidecar (JSON next to each day's file, or single file in XDG state dir) that keeps the markdown clean but means folds don't survive Logseq edits of the same file. Could also do both: read/write `collapsed::` when present, fall back to sidecar otherwise.
- **TODO/DONE checkboxes** — Logseq-style block task state: a block prefixed with `TODO ` or `DONE ` renders with a checkbox (unchecked / checked); clicking the checkbox or a keyboard shortcut (Logseq uses Ctrl+Enter to cycle) toggles between `TODO` ↔ `DONE`, or cycles through more states (`LATER`, `NOW`, `DOING`, `WAITING`, `CANCELED`) if we grow the set. The prefix lives in the markdown source so it round-trips through Logseq. Scope question for v1: just TODO/DONE, or the full Logseq set? Rendering: preserve the literal `TODO ` / `DONE ` prefix in the view (so what you see matches the source), but style it — e.g. a colored badge / pill, strikethrough for DONE, dimmed text for the body of a DONE block.
- **Select all** - ctrl-a selected the current textview, then expands to the current block and it's children, then additional presses expand to its parent
- **Clipboard** - we should be able to cut/copy/paste block(s), both for internal reorganization and external consumption
- **Double click to select word** - when not focused. Logseq sort of achieves this, but it's tricky.

## Markdown rendering

- **More inline syntax** — links `[text](url)`, autolinks, strikethrough, backslash escapes. Current parser handles `**bold**`, `*italic*`, `` `code` ``; no nesting.
- **Code styling** — `<tt>` gets monospace but no background; once we have theme-aware colors, give code a subtle bg.
- **File-format parser** — parsing a whole `YYYY-MM-DD.md` into the `Block(level, text)` tree (nested bullets via indentation) is the other place markdown shows up. Re-evaluate `markdown-it-py` here when we build the loader; its token stream + line maps suit block parsing better than hand-rolling.

## Persistence / journaling (the actual app)

We are a "daily journal" but have none of this yet:

- **Scrolling**
- **File format** — markdown on disk, one file per day (`YYYY-MM-DD.md`), nested bullets via indentation. Must load the user's existing Logseq files; follow Logseq conventions over CommonMark where they differ. Known divergence: a bare `\n` inside a block is a hard line break in Logseq (serialized as plain `\n`, no trailing `  ` or `\\`), not a CommonMark soft break. Test rendering + round-trip against real Logseq files.
- **Storage location** — configurable; default to something like `~/Documents/dailyfold/` or XDG data dir.
- **Load on startup** — today's file, or most recent.
- **Save on edit** — debounced write on every change; no explicit save action.
- **Date navigation** — jump to today, previous/next day via keyboard (probably Ctrl+. / Ctrl+, or similar). Always-visible "today" shortcut.
- **Calendar day picker** — month-grid popup (or persistent sidebar?) to jump to an arbitrary date. Highlight days that have a file on disk so empty days are visually distinct. Arrow keys navigate the grid; Enter opens. Consider showing a small content preview or block-count per day on hover.
- **Search** — cross-file full-text across all days. Triggered by keyboard shortcut (Ctrl+K / Ctrl+Shift+F). Modal/overlay with incremental results as you type; each result shows the date, the block, and surrounding context with the match highlighted. Enter jumps to the day + scrolls/focuses the block. Start naive (scan files on each query — fine up to thousands of days); add an index later if it gets slow. Scope: plain substring first, regex / token-based filtering later.
- **Backlinks / page links / tags** — deferred; decide later whether to mimic Logseq here or do something simpler.

## Deferred (explicit not-now)

- **Dark mode** — light colors only for v1. When revisited, pull colors from live `Gtk.StyleContext` rather than hardcoding a dark palette.
- **Partial cross-block selection** — explicitly out of scope per editor-model memory. Within-block selection uses TextView natively.
- **GTK4** — we chose GTK3 for simplicity. Revisit only if we hit CPU-rendering walls.
