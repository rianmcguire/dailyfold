"""Inline Markdown → rendered runs with source-offset click mapping.

Block-level markdown is irrelevant here: documents are split into Block(level, text)
at load time, so this module only sees the text inside one block. Supported:
emphasis, code, strikethrough, links, autolinks, and backslash escapes.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from html import escape as html_escape
import re
import string
import unicodedata
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape


ANGLE_EMAIL_RE = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
)
BARE_URL_RE = re.compile(r"https?://[^\s<>]+")


@dataclass(frozen=True)
class InlineRun:
    text: str
    source_start: int
    source_end: int
    style: frozenset = field(default_factory=frozenset)
    link_url: str | None = None


@dataclass(frozen=True)
class _Piece:
    text: str
    boundaries: tuple[int, ...]
    style: frozenset
    link_url: str | None


@dataclass(frozen=True)
class InlineParse:
    """Rendered inline runs and the source position of every display boundary."""

    runs: tuple[InlineRun, ...]
    display_text: str
    display_to_source: tuple[int, ...]

    def source_offset(self, display_char_idx: int) -> int:
        display_char_idx = max(0, min(display_char_idx, len(self.display_text)))
        return self.display_to_source[display_char_idx]


def _piece(
    text: str,
    start: int,
    end: int,
    style: frozenset,
    link_url: str | None,
    boundaries: tuple[int, ...] | None = None,
) -> _Piece:
    if boundaries is None:
        boundaries = tuple(range(start, end + 1))
    return _Piece(text, boundaries, style, link_url)


def _find_unescaped(source: str, needle: str, start: int, end: int) -> int:
    i = start
    while i < end:
        found = source.find(needle, i, end)
        if found < 0:
            return -1
        slashes = 0
        before = found - 1
        while before >= start and source[before] == "\\":
            slashes += 1
            before -= 1
        if slashes % 2 == 0:
            return found
        i = found + len(needle)
    return -1


def _unescape_punctuation(value: str) -> str:
    result = []
    i = 0
    while i < len(value):
        if (
            value[i] == "\\"
            and i + 1 < len(value)
            and value[i + 1] in string.punctuation
        ):
            i += 1
        result.append(value[i])
        i += 1
    return "".join(result)


def _is_punctuation(char: str) -> bool:
    return char in string.punctuation or unicodedata.category(char).startswith(
        "P"
    )


def _underscore_flanking(
    source: str, start: int, length: int
) -> tuple[bool, bool, bool, bool]:
    """Return CommonMark-style left/right flanking for an underscore run."""
    before = source[start - 1] if start > 0 else "\n"
    after_pos = start + length
    after = source[after_pos] if after_pos < len(source) else "\n"
    before_punctuation = _is_punctuation(before)
    after_punctuation = _is_punctuation(after)
    left_flanking = not after.isspace() and (
        not after_punctuation or before.isspace() or before_punctuation
    )
    right_flanking = not before.isspace() and (
        not before_punctuation or after.isspace() or after_punctuation
    )
    return left_flanking, right_flanking, before_punctuation, after_punctuation


def _underscore_can_open(source: str, start: int, length: int) -> bool:
    left, right, before_punctuation, _ = _underscore_flanking(
        source, start, length
    )
    return left and (not right or before_punctuation)


def _underscore_can_close(source: str, start: int, length: int) -> bool:
    left, right, _, after_punctuation = _underscore_flanking(
        source, start, length
    )
    return right and (not left or after_punctuation)


def _safe_link_destination(value: str) -> bool:
    """Allow web/email and relative links, but reject active URI schemes."""
    try:
        scheme = urlsplit(value).scheme.lower()
    except ValueError:
        return False
    return not scheme or scheme in {"http", "https", "mailto"}


def _link_at(source: str, start: int, end: int):
    if start > 0 and source[start - 1] == "!":
        return None

    label_end = _find_unescaped(source, "]", start + 1, end)
    if label_end <= start + 1 or label_end + 1 >= end:
        return None
    if source[label_end + 1] != "(":
        return None

    destination_start = label_end + 2
    depth = 0
    i = destination_start
    while i < end:
        if source[i] == "\\" and i + 1 < end:
            i += 2
            continue
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            if depth == 0:
                destination = source[destination_start:i]
                if destination.startswith("<") and destination.endswith(">"):
                    destination = destination[1:-1]
                if not destination or any(char.isspace() for char in destination):
                    return None
                destination = _unescape_punctuation(destination)
                if not _safe_link_destination(destination):
                    return None
                return label_end, destination, i + 1
            depth -= 1
        i += 1
    return None


def _angle_autolink_at(source: str, start: int, end: int):
    close = source.find(">", start + 1, end)
    if close < 0:
        return None
    value = source[start + 1 : close]
    if value.startswith(("http://", "https://", "mailto:")):
        if any(char.isspace() for char in value):
            return None
        return value, value, close + 1
    if ANGLE_EMAIL_RE.fullmatch(value):
        return value, f"mailto:{value}", close + 1
    return None


def _bare_url_at(source: str, start: int, end: int):
    if start > 0 and (source[start - 1].isalnum() or source[start - 1] in "_/"):
        return None
    match = BARE_URL_RE.match(source, start, end)
    if match is None:
        return None

    url_end = match.end()
    while url_end > start and source[url_end - 1] in ".,;:!?":
        url_end -= 1
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        while (
            url_end > start
            and source[url_end - 1] == closing
            and source[start:url_end].count(closing)
            > source[start:url_end].count(opening)
        ):
            url_end -= 1
    if url_end == start:
        return None
    return source[start:url_end], url_end


def _parse_sequence(
    source: str,
    start: int,
    end: int,
    style: frozenset,
    link_url: str | None = None,
    stop: str | None = None,
):
    pieces = []
    i = start
    while i < end:
        if source[i] == "\\" and i + 1 < end and source[i + 1] in string.punctuation:
            pieces.append(
                _piece(
                    source[i + 1],
                    i,
                    i + 2,
                    style,
                    link_url,
                    boundaries=(i, i + 2),
                )
            )
            i += 2
            continue

        # A double asterisk inside italic text may either open bold or begin
        # the italic close followed by an outer close. Prefer bold only when a
        # complete bold span can be parsed.
        if stop == "*" and source.startswith("**", i):
            inner, after, closed = _parse_sequence(
                source, i + 2, end, style | {"bold"}, link_url, "**"
            )
            if closed and any(piece.text for piece in inner):
                pieces.extend(inner)
                i = after
                continue
            return pieces, i + 1, True

        if (
            stop is not None
            and source.startswith(stop, i)
            and (
                not stop.startswith("_")
                or _underscore_can_close(source, i, len(stop))
            )
        ):
            return pieces, i + len(stop), True

        if source[i] == "`":
            close = source.find("`", i + 1, end)
            if close > i + 1:
                pieces.append(
                    _piece(
                        source[i + 1 : close],
                        i + 1,
                        close,
                        style | {"code"},
                        link_url,
                    )
                )
                i = close + 1
                continue

        if source[i] == "[" and link_url is None:
            link = _link_at(source, i, end)
            if link is not None:
                label_end, destination, after = link
                label, _, _ = _parse_sequence(
                    source, i + 1, label_end, style, destination
                )
                if any(piece.text for piece in label):
                    pieces.extend(label)
                    i = after
                    continue

        if source[i] == "<" and link_url is None:
            autolink = _angle_autolink_at(source, i, end)
            if autolink is not None:
                text, destination, after = autolink
                pieces.append(
                    _piece(text, i + 1, after - 1, style, destination)
                )
                i = after
                continue

        if link_url is None and source.startswith(("http://", "https://"), i):
            bare_url = _bare_url_at(source, i, end)
            if bare_url is not None:
                destination, after = bare_url
                pieces.append(
                    _piece(destination, i, after, style, destination)
                )
                i = after
                continue

        matched_delimiter = False
        for delimiter, name in (
            ("**", "bold"),
            ("~~", "strike"),
            ("*", "italic"),
            ("_", "italic"),
        ):
            if not source.startswith(delimiter, i):
                continue
            if delimiter == "_" and (
                (i > 0 and source[i - 1] == "_")
                or (i + 1 < end and source[i + 1] == "_")
            ):
                continue
            if delimiter.startswith("_") and not _underscore_can_open(
                source, i, len(delimiter)
            ):
                continue
            inner, after, closed = _parse_sequence(
                source,
                i + len(delimiter),
                end,
                style | {name},
                link_url,
                delimiter,
            )
            if closed and any(piece.text for piece in inner):
                pieces.extend(inner)
                i = after
            else:
                pieces.append(
                    _piece(delimiter, i, i + len(delimiter), style, link_url)
                )
                i += len(delimiter)
            matched_delimiter = True
            break
        if matched_delimiter:
            continue

        pieces.append(_piece(source[i], i, i + 1, style, link_url))
        i += 1

    return pieces, i, False


def parse_inline(source: str) -> InlineParse:
    pieces, _, _ = _parse_sequence(source, 0, len(source), frozenset())
    runs: list[InlineRun] = []
    display_parts = []
    display_to_source = [0]

    for piece in pieces:
        display_parts.append(piece.text)
        display_to_source[-1] = piece.boundaries[0]
        display_to_source.extend(piece.boundaries[1:])

        if (
            runs
            and runs[-1].style == piece.style
            and runs[-1].link_url == piece.link_url
        ):
            previous = runs[-1]
            runs[-1] = InlineRun(
                previous.text + piece.text,
                previous.source_start,
                piece.boundaries[-1],
                piece.style,
                piece.link_url,
            )
        else:
            runs.append(
                InlineRun(
                    piece.text,
                    piece.boundaries[0],
                    piece.boundaries[-1],
                    piece.style,
                    piece.link_url,
                )
            )

    return InlineParse(
        tuple(runs), "".join(display_parts), tuple(display_to_source)
    )


def tokenize_inline(source: str) -> list[InlineRun]:
    """Return inline runs; retained as a compatibility wrapper."""
    return list(parse_inline(source).runs)


def link_url_at_display_offset(parsed: InlineParse, display_char_idx: int):
    """Return the link covering a displayed character, if any."""
    if display_char_idx < 0:
        return None
    offset = 0
    for run in parsed.runs:
        end = offset + len(run.text)
        if offset <= display_char_idx < end:
            return run.link_url
        offset = end
    return None


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
        if "strike" in run.style:
            t = f"<s>{t}</s>"
        if run.link_url is not None:
            t = f'<span foreground="#1a5fb4" underline="single">{t}</span>'
        parts.append(t)
    return "".join(parts)


def runs_to_html(runs: Iterable[InlineRun]) -> str:
    parts = []
    for run in runs:
        value = html_escape(run.text).replace("\n", "<br>\n")
        if "code" in run.style:
            value = f"<code>{value}</code>"
        if "italic" in run.style:
            value = f"<em>{value}</em>"
        if "bold" in run.style:
            value = f"<strong>{value}</strong>"
        if "strike" in run.style:
            value = f"<del>{value}</del>"
        if run.link_url is not None:
            destination = html_escape(run.link_url, quote=True)
            value = f'<a href="{destination}">{value}</a>'
        parts.append(value)
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
