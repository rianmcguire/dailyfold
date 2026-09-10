"""Inline markdown → Pango markup, with source-offset mapping for click-to-edit.

Block-level markdown is irrelevant here: documents are split into Block(level, text)
at load time, so this module only sees the text inside one block. Supported:
**bold**, *italic*, `code`. No nesting, no escapes (yet).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from xml.sax.saxutils import escape as xml_escape


@dataclass(frozen=True)
class InlineRun:
    text: str
    source_start: int
    source_end: int
    style: frozenset = field(default_factory=frozenset)


@dataclass(frozen=True)
class InlineParse:
    """Rendered inline runs and the source position of every display boundary."""

    runs: tuple[InlineRun, ...]
    display_text: str
    display_to_source: tuple[int, ...]

    def source_offset(self, display_char_idx: int) -> int:
        display_char_idx = max(0, min(display_char_idx, len(self.display_text)))
        return self.display_to_source[display_char_idx]


def parse_inline(source: str) -> InlineParse:
    runs: list[InlineRun] = []
    display_parts: list[str] = []
    display_to_source = [0]
    n = len(source)
    i = 0
    plain_start = 0

    def append_run(start: int, end: int, style=frozenset()) -> None:
        text = source[start:end]
        runs.append(InlineRun(text, start, end, style))
        display_parts.append(text)

        # A visual boundary beside hidden Markdown belongs to the run on its
        # right. This preserves the existing click behaviour: clicking the
        # leading edge of styled text places the editor cursor just inside its
        # opening marker. Keeping every boundary explicit lets future syntax
        # (escapes and links, for example) provide non-contiguous mappings.
        display_to_source[-1] = start
        display_to_source.extend(range(start + 1, end + 1))

    def flush_plain(end: int) -> None:
        nonlocal plain_start
        if plain_start < end:
            append_run(plain_start, end)
        plain_start = end

    while i < n:
        ch = source[i]
        if ch == "`":
            j = source.find("`", i + 1)
            if j != -1 and j > i + 1:
                flush_plain(i)
                append_run(i + 1, j, frozenset({"code"}))
                i = j + 1
                plain_start = i
                continue
        elif source.startswith("**", i):
            j = source.find("**", i + 2)
            if j != -1 and j > i + 2:
                flush_plain(i)
                append_run(i + 2, j, frozenset({"bold"}))
                i = j + 2
                plain_start = i
                continue
        elif ch == "*":
            j = source.find("*", i + 1)
            if j != -1 and j > i + 1:
                flush_plain(i)
                append_run(i + 1, j, frozenset({"italic"}))
                i = j + 1
                plain_start = i
                continue
        i += 1
    flush_plain(n)
    return InlineParse(
        tuple(runs), "".join(display_parts), tuple(display_to_source)
    )


def tokenize_inline(source: str) -> list[InlineRun]:
    """Return inline runs; retained as a compatibility wrapper."""
    return list(parse_inline(source).runs)


def runs_to_markup(runs: Iterable[InlineRun]) -> str:
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


def source_offset_from_display(
    parsed: InlineParse | list[InlineRun], display_char_idx: int
) -> int:
    """Map a display cursor position to source.

    Passing runs is supported for callers of the original API. New code should
    pass InlineParse so syntax with non-contiguous source text can be mapped.
    """
    if isinstance(parsed, InlineParse):
        return parsed.source_offset(display_char_idx)

    runs = parsed
    display_char_idx = max(0, display_char_idx)
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
