"""Logseq-compatible Markdown loading and daily journal storage."""

from datetime import date
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field

from model import Block


BLOCK_RE = re.compile(r"^([ \t]*)-(?:[ \t](.*))?$")
CODE_FENCE_RE = re.compile(r"^```([a-zA-Z0-9_+\-]*)$")
PROPERTY_RE = re.compile(r"^[^:\s][^:]*::(?:\s.*)?$")
COLLAPSED_PROPERTY_RE = re.compile(r"^collapsed::\s*(.*)$", re.IGNORECASE)
JOURNAL_FILE_RE = re.compile(r"^(\d{4})_(\d{2})_(\d{2})\.md$")
DATA_DIR_ENV = "DAILYFOLD_DATA_DIR"


@dataclass
class MarkdownDocument:
    blocks: list[Block] = field(default_factory=list)
    preamble: list[str] = field(default_factory=list)
    trailing_newline: bool = True


def default_data_dir(environ=None):
    """Return the configured journal directory, following the XDG convention."""
    environ = os.environ if environ is None else environ
    configured = environ.get(DATA_DIR_ENV)
    if configured:
        return os.path.abspath(os.path.expanduser(configured))

    xdg_data_home = environ.get("XDG_DATA_HOME")
    if not xdg_data_home:
        xdg_data_home = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.abspath(
        os.path.join(os.path.expanduser(xdg_data_home), "dailyfold")
    )


def journal_path(data_dir, day):
    """Return the Markdown path for a calendar day."""
    return os.path.join(
        os.path.abspath(os.path.expanduser(data_dir)),
        f"{day.strftime('%Y_%m_%d')}.md",
    )


def journal_dates(data_dir):
    """Return all valid Logseq-dated Markdown pages in *data_dir*."""
    try:
        names = os.listdir(data_dir)
    except FileNotFoundError:
        return set()

    days = set()
    for name in names:
        match = JOURNAL_FILE_RE.match(name)
        if match is None:
            continue
        try:
            day = date(*(int(part) for part in match.groups()))
        except ValueError:
            continue
        if os.path.isfile(os.path.join(data_dir, name)):
            days.add(day)
    return days


def _indent_width(indent):
    return sum(2 if char == "\t" else 1 for char in indent)


def _strip_indent(text, width):
    consumed = 0
    i = 0
    while i < len(text) and consumed < width and text[i] in " \t":
        consumed += 2 if text[i] == "\t" else 1
        i += 1
    return text[i:]


def _block_level(indent_stack, width):
    if not indent_stack:
        indent_stack.append(width)
    elif width > indent_stack[-1]:
        indent_stack.append(width)
    else:
        while indent_stack and width < indent_stack[-1]:
            indent_stack.pop()
        if not indent_stack or width != indent_stack[-1]:
            indent_stack.append(width)
    return len(indent_stack) - 1


def _is_collapsed(properties):
    for prop in properties:
        match = COLLAPSED_PROPERTY_RE.match(_property_body(prop))
        if match is not None:
            return match.group(1).strip().lower() == "true"
    return False


def _property_body(line):
    return line[2:] if line.startswith("* ") else line


def _is_property(line):
    return PROPERTY_RE.match(_property_body(line)) is not None


def _split_raw_block(level, lines):
    properties = []
    content = []
    in_code = False
    for i, line in enumerate(lines):
        fence = CODE_FENCE_RE.match(line)
        if fence is not None:
            in_code = not in_code
            content.append(line)
        elif i > 0 and not in_code and _is_property(line):
            properties.append(line)
        else:
            content.append(line)

    props = tuple(properties)
    collapsed = _is_collapsed(props)
    result = []
    prose = []
    code_lines = None
    code_lang = None

    def flush_prose():
        nonlocal prose
        if prose or not result:
            result.append(Block(level, "\n".join(prose)))
        prose = []

    for line in content:
        fence = CODE_FENCE_RE.match(line)
        if code_lines is None:
            if fence is None:
                prose.append(line)
            else:
                if prose:
                    flush_prose()
                code_lang = fence.group(1)
                code_lines = []
        elif line == "```":
            result.append(Block(level, "\n".join(code_lines), code_lang=code_lang))
            code_lines = None
            code_lang = None
        else:
            code_lines.append(line)

    if code_lines is not None:
        result.append(Block(level, "\n".join(code_lines), code_lang=code_lang))
    elif prose:
        flush_prose()
    if not result:
        result.append(Block(level, ""))

    result[0].properties = props
    result[-1].collapsed = collapsed
    return result


def parse_document(text):
    """Parse a Logseq-style Markdown page into a document and flat block tree."""
    trailing_newline = text.endswith(("\n", "\r"))
    lines = text.splitlines()
    preamble = []
    blocks = []
    indent_stack = []
    current_level = None
    current_indent = 0
    current_lines = []
    in_code = False

    def flush_current():
        nonlocal current_lines
        if current_level is not None:
            blocks.extend(_split_raw_block(current_level, current_lines))
        current_lines = []

    for line in lines:
        if current_level is not None and in_code:
            body = _strip_indent(line, current_indent + 2)
            current_lines.append(body)
            if body == "```":
                in_code = False
            continue

        match = BLOCK_RE.match(line)
        if match is not None:
            flush_current()
            indent, body = match.groups()
            current_indent = _indent_width(indent)
            current_level = _block_level(indent_stack, current_indent)
            body = body or ""
            current_lines = [body]
            in_code = CODE_FENCE_RE.match(body) is not None
            continue

        if current_level is None:
            preamble.append(line)
            continue

        body = _strip_indent(line, current_indent + 2)
        current_lines.append(body)
        if CODE_FENCE_RE.match(body) is not None:
            in_code = True

    flush_current()
    return MarkdownDocument(blocks, preamble, trailing_newline)


def _serialized_properties(block):
    properties = []
    found_collapsed = False
    for prop in block.properties:
        if COLLAPSED_PROPERTY_RE.match(_property_body(prop)):
            if block.collapsed and not found_collapsed:
                prefix = "* " if prop.startswith("* ") else ""
                properties.append(prefix + "collapsed:: true")
                found_collapsed = True
        else:
            properties.append(prop)
    if block.collapsed and not found_collapsed:
        properties.append("collapsed:: true")
    return properties


def serialize_document(document):
    """Serialize a document using canonical two-space Logseq indentation."""
    lines = list(document.preamble)
    for block in document.blocks:
        indent = "  " * block.level
        continuation = indent + "  "
        properties = _serialized_properties(block)
        if block.code_lang is not None:
            lines.append(f"{indent}- ```{block.code_lang}")
            lines.extend(continuation + line for line in block.text.split("\n"))
            lines.append(continuation + "```")
            lines.extend(continuation + prop for prop in properties)
        else:
            text_lines = block.text.split("\n")
            lines.append(f"{indent}- {text_lines[0]}")
            lines.extend(continuation + prop for prop in properties)
            lines.extend(continuation + line for line in text_lines[1:])

    result = "\n".join(lines)
    if document.trailing_newline and lines:
        result += "\n"
    return result


def load_document(path):
    with open(path, encoding="utf-8", newline=None) as handle:
        return parse_document(handle.read())


def save_document(path, document):
    """Atomically replace path with the serialized document."""
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    existing_mode = None
    try:
        existing_mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        pass

    fd, temporary_path = tempfile.mkstemp(
        dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp"
    )
    try:
        if existing_mode is not None:
            os.fchmod(fd, existing_mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialize_document(document))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise
