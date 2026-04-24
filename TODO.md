# TODO

Everything we've discussed but haven't built yet. Grouped roughly in order of what we'd probably want next.

## Editor

- **Caret-carrying navigation across blocks** — per Logseq: there's no "focused but not editing" state for a single block. The cursor lives inside a block at all times; ↑/↓/←/→ carry it across block boundaries, continuing edit mode in the new block.
  - Position model: `(block_idx, line_idx, col)` where `line_idx` indexes `\n`-separated source lines within the block (not Pango visual lines — wrapping is ignored for navigation). `col` is a character offset into that source line.
  - ↑/↓ preserve a sticky `desired_col` across vertical moves; reset it on ←/→ or typing. Clamp actual col to `len(target_line)` but keep `desired_col` unchanged so long→short→long restores.
  - ↑ from `(b, 0, c)` → `(b-1, last_line_of(b-1), min(desired_col, len))`. ↓ symmetric. Within a multi-line block, ↑/↓ walks source lines before crossing blocks.
  - ← at `(b, 0, 0)` → end of `(b-1)`'s last line. ← at `(b, l>0, 0)` → end of line `l-1` in same block. → symmetric.
  - Top of document: ↑ at `(0, 0, _)` does nothing (or moves to col 0). Bottom: ↓ at last block's last line does nothing (or moves to end).
- **Enter splits a block** — at cursor position, split `block.text` at source offset; left half stays in current block, right half becomes a new sibling at same level immediately after. Cursor moves to `(new_block, 0, 0)`. Currently Enter inserts a `\n` inside the TextView (which gives us a multi-line block — fine, just not what Enter should do).
- **Backspace-at-start joins** — at `(b, 0, 0)` with `b > 0`: append current block's text directly to the end of previous block's last source line (no separator `\n`), cursor lands at the join point `(b-1, last_line, len(last_line_before_join))`, current block is deleted. If current block has children, they re-parent to previous block. Does NOT outdent — Shift-Tab does that.
- **Tab / Shift-Tab indent/outdent** — re-parents the current block within the tree. Tab: increase `level` by 1 (only valid if previous sibling exists to become new parent). Shift-Tab: decrease `level` by 1 (only valid if `level > 1`; level 0 is the date header). Cursor position within block preserved.
- **Block-level selection** — select one or more whole blocks (shift+click, shift+arrow) to move/delete/indent/outdent as a group. Logseq/Workflowy style. Confirmed scope, not yet built.
- **Move blocks** — drag or keyboard (alt+up/down) to reorder within siblings; also "move into" / "move out of" parent.

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
- **Date navigation** — jump to today, previous/next day, specific date picker.
- **Backlinks / page links / tags** — deferred; decide later whether to mimic Logseq here or do something simpler.

## Deferred (explicit not-now)

- **Dark mode** — light colors only for v1. When revisited, pull colors from live `Gtk.StyleContext` rather than hardcoding a dark palette.
- **Partial cross-block selection** — explicitly out of scope per editor-model memory. Within-block selection uses TextView natively.
- **GTK4** — we chose GTK3 for simplicity. Revisit only if we hit CPU-rendering walls.
