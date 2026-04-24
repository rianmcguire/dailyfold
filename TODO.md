# TODO

Everything we've discussed but haven't built yet. Grouped roughly in order of what we'd probably want next.

## Editor

- **Enter splits a block** — at cursor position, split `block.text` at source offset; left half stays in current block, right half becomes a new sibling at same level immediately after. Cursor moves to `(new_block, 0, 0)`. Currently Enter inserts a `\n` inside the TextView (which gives us a multi-line block — fine, just not what Enter should do).
- **Backspace-at-start joins** — at `(b, 0, 0)` with `b > 0`: append current block's text directly to the end of previous block's last source line (no separator `\n`), cursor lands at the join point `(b-1, last_line, len(last_line_before_join))`, current block is deleted. If current block has children, they re-parent to previous block. Does NOT outdent — Shift-Tab does that.
- **Tab / Shift-Tab indent/outdent** — re-parents the current block within the tree. Tab: increase `level` by 1 (only valid if previous sibling exists to become new parent). Shift-Tab: decrease `level` by 1 (only valid if `level > 1`; level 0 is the date header). Cursor position within block preserved.
- **Block-level selection** — select one or more whole blocks (shift+click, shift+arrow) to move/delete/indent/outdent as a group. Logseq/Workflowy style. Confirmed scope, not yet built.
- **Move blocks** — drag or keyboard (alt+up/down) to reorder within siblings; also "move into" / "move out of" parent.
- **Folding** — collapse/expand a block's descendants. Toggle via click on bullet (bullet style changes to indicate collapsed state) and/or keyboard (Logseq uses Tab on a non-editing block, or a dedicated shortcut — pick one that doesn't collide with indent). Navigation (↑/↓) should skip over hidden descendants. Selecting/moving/deleting a folded block acts on the whole subtree. Persistence: two options worth weighing — (a) Logseq-compatible `collapsed:: true` block property, which round-trips folds through shared files but adds visible noise to the `.md`; (b) a sidecar (JSON next to each day's file, or single file in XDG state dir) that keeps the markdown clean but means folds don't survive Logseq edits of the same file. Could also do both: read/write `collapsed::` when present, fall back to sidecar otherwise.
- **TODO/DONE checkboxes** — Logseq-style block task state: a block prefixed with `TODO ` or `DONE ` renders with a checkbox (unchecked / checked); clicking the checkbox or a keyboard shortcut (Logseq uses Ctrl+Enter to cycle) toggles between `TODO` ↔ `DONE`, or cycles through more states (`LATER`, `NOW`, `DOING`, `WAITING`, `CANCELED`) if we grow the set. The prefix lives in the markdown source so it round-trips through Logseq. Scope question for v1: just TODO/DONE, or the full Logseq set? Rendering: preserve the literal `TODO ` / `DONE ` prefix in the view (so what you see matches the source), but style it — e.g. a colored badge / pill, strikethrough for DONE, dimmed text for the body of a DONE block.
- **Undo/redo** — global stack across both text edits and structural changes (Enter-split, Backspace-join, Tab-indent, move, delete). GTK's per-TextView undo isn't enough: the buffer is discarded on block switch and structural ops aren't tracked at all. Design note: probably an operation log (insert-block, delete-block, set-text, set-level, move-block) with inverse ops; coalesce adjacent text edits within a single block into one entry. Ctrl+Z / Ctrl+Shift+Z (or Ctrl+Y).

## Markdown rendering

- **More inline syntax** — links `[text](url)`, autolinks, strikethrough, backslash escapes. Current parser handles `**bold**`, `*italic*`, `` `code` ``; no nesting.
- **Code styling** — `<tt>` gets monospace but no background; once we have theme-aware colors, give code a subtle bg.
- **File-format parser** — parsing a whole `YYYY-MM-DD.md` into the `Block(level, text)` tree (nested bullets via indentation) is the other place markdown shows up. Re-evaluate `markdown-it-py` here when we build the loader; its token stream + line maps suit block parsing better than hand-rolling.

## Polish / known issues

- **Header editing font** — clicking a level-0 header mounts a TextView with body font instead of header font; text size jumps on focus. Either render the TextView with the header font, or disable editing of level-0 blocks, or rethink what level-0 means (is it really just the date header?).
- **Broadway assertion on abrupt client disconnect** — SIGTERM handler now quits cleanly, but any crash (OOM, unhandled exception) will still kill broadwayd. Consider `systemd --user` or a supervisor for the dev loop.

## Persistence / journaling (the actual app)

We are a "daily journal" but have none of this yet:

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
