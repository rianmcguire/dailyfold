# TODO

Everything we've discussed but haven't built yet. Grouped roughly in order of what we'd probably want next.

## Editor

- **Keyboard navigation between blocks** — up/down arrows move focus between blocks; left/right at a block boundary should probably move to adjacent block's end/start.
- **Enter splits a block** — currently Enter inserts a newline inside the TextView. Should create a new sibling block below and move focus there.
- **Backspace-on-empty joins/outdents** — at start of block: merge into previous block, or if at deeper level, outdent first.
- **Tab / Shift-Tab to indent/outdent** the focused block.
- **Block-level selection** — select one or more whole blocks (shift+click, shift+arrow) to move/delete/indent/outdent as a group. Logseq/Workflowy style. Confirmed scope, not yet built.
- **Move blocks** — drag or keyboard (alt+up/down) to reorder within siblings; also "move into" / "move out of" parent.

## Markdown rendering

- **Render inline markdown for non-focused blocks** — bold, italic, code via Pango markup to start. Links and code blocks later.
- **Rendered → source character mapping** — when user clicks inside rendered text (`**bold**` display), the TextView must open with the cursor at the equivalent source offset. Build the Pango markup with an offset map alongside it; use `Pango.Layout.xy_to_index` then translate.
- **Markdown parser** — pick one (mistune, markdown-it-py, or hand-rolled inline parser — we may only need inline for v1). Block-level parsing is irrelevant since each Block is its own unit.

## Polish / known issues

- **Header editing font** — clicking a level-0 header mounts a TextView with body font instead of header font; text size jumps on focus. Either render the TextView with the header font, or disable editing of level-0 blocks, or rethink what level-0 means (is it really just the date header?).
- **Broadway assertion on abrupt client disconnect** — SIGTERM handler now quits cleanly, but any crash (OOM, unhandled exception) will still kill broadwayd. Consider `systemd --user` or a supervisor for the dev loop.

## Persistence / journaling (the actual app)

We are a "daily journal" but have none of this yet:

- **File format** — markdown on disk, one file per day (`YYYY-MM-DD.md`), nested bullets via indentation. Compatible with Logseq where practical so migration is cheap.
- **Storage location** — configurable; default to something like `~/Documents/dailyfold/` or XDG data dir.
- **Load on startup** — today's file, or most recent.
- **Save on edit** — debounced write on every change; no explicit save action.
- **Date navigation** — jump to today, previous/next day, specific date picker.
- **Backlinks / page links / tags** — deferred; decide later whether to mimic Logseq here or do something simpler.

## Deferred (explicit not-now)

- **Dark mode** — light colors only for v1. When revisited, pull colors from live `Gtk.StyleContext` rather than hardcoding a dark palette.
- **Partial cross-block selection** — explicitly out of scope per editor-model memory. Within-block selection uses TextView natively.
- **GTK4** — we chose GTK3 for simplicity. Revisit only if we hit CPU-rendering walls.
