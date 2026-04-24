"""Inline markdown → Pango markup, with source-offset mapping for click-to-edit.

Block-level markdown is irrelevant here: documents are split into Block(level, text)
at load time, so this module only sees the text inside one block. Supported:
**bold**, *italic*, `code`. No nesting, no escapes (yet).
"""

from dataclasses import dataclass, field
from xml.sax.saxutils import escape as xml_escape


@dataclass(frozen=True)
class InlineRun:
    text: str
    source_start: int
    source_end: int
    style: frozenset = field(default_factory=frozenset)


def tokenize_inline(source: str) -> list[InlineRun]:
    runs: list[InlineRun] = []
    n = len(source)
    i = 0
    plain_start = 0

    def flush_plain(end: int) -> None:
        nonlocal plain_start
        if plain_start < end:
            runs.append(
                InlineRun(
                    text=source[plain_start:end],
                    source_start=plain_start,
                    source_end=end,
                    style=frozenset(),
                )
            )
        plain_start = end

    while i < n:
        ch = source[i]
        if ch == "`":
            j = source.find("`", i + 1)
            if j != -1 and j > i + 1:
                flush_plain(i)
                runs.append(
                    InlineRun(source[i + 1 : j], i + 1, j, frozenset({"code"}))
                )
                i = j + 1
                plain_start = i
                continue
        elif source.startswith("**", i):
            j = source.find("**", i + 2)
            if j != -1 and j > i + 2:
                flush_plain(i)
                runs.append(
                    InlineRun(source[i + 2 : j], i + 2, j, frozenset({"bold"}))
                )
                i = j + 2
                plain_start = i
                continue
        elif ch == "*":
            j = source.find("*", i + 1)
            if j != -1 and j > i + 1:
                flush_plain(i)
                runs.append(
                    InlineRun(source[i + 1 : j], i + 1, j, frozenset({"italic"}))
                )
                i = j + 1
                plain_start = i
                continue
        i += 1
    flush_plain(n)
    return runs


def runs_to_markup(runs: list[InlineRun]) -> str:
    parts = []
    for run in runs:
        t = xml_escape(run.text)
        if "code" in run.style:
            t = f"<tt>{t}</tt>"
        if "italic" in run.style:
            t = f"<i>{t}</i>"
        if "bold" in run.style:
            t = f"<b>{t}</b>"
        parts.append(t)
    return "".join(parts)


def runs_display_text(runs: list[InlineRun]) -> str:
    return "".join(run.text for run in runs)


def source_offset_from_display(runs: list[InlineRun], display_char_idx: int) -> int:
    # Position N in display belongs to the run that starts at N (if any),
    # i.e. run boundaries map to the *start* of the following run's source
    # range. This puts the cursor just inside the opening marker, which is
    # usually what the user wants after clicking at the visual edge.
    d = 0
    for run in runs:
        rlen = len(run.text)
        if display_char_idx < d + rlen:
            return run.source_start + (display_char_idx - d)
        d += rlen
    if runs:
        return runs[-1].source_end
    return 0


def display_char_from_byte(display_text: str, byte_idx: int) -> int:
    b = display_text.encode("utf-8")
    byte_idx = max(0, min(byte_idx, len(b)))
    try:
        return len(b[:byte_idx].decode("utf-8"))
    except UnicodeDecodeError:
        return byte_idx
