"""Block-level Markdown parsing and serialization for outlines."""

from dataclasses import dataclass, field
import re

from model import Block


DOCUMENT_BLOCK_RE = re.compile(r"^([ \t]*)-(?:[ \t](.*))?$")
FRAGMENT_BLOCK_RE = re.compile(r"^([ \t]*)[-*+] (.*)$")
CODE_FENCE_RE = re.compile(r"^```([a-zA-Z0-9_+\-]*)$")
PROPERTY_RE = re.compile(r"^[^:\s][^:]*::(?:\s.*)?$")
COLLAPSED_PROPERTY_RE = re.compile(r"^collapsed::\s*(.*)$", re.IGNORECASE)


@dataclass
class MarkdownDocument:
    blocks: list[Block] = field(default_factory=list)
    preamble: list[str] = field(default_factory=list)
    trailing_newline: bool = True


def _indent_width(indent):
    return sum(2 if char == "\t" else 1 for char in indent)


def _strip_indent(text, width):
    consumed = 0
    index = 0
    while index < len(text) and consumed < width and text[index] in " \t":
        consumed += 2 if text[index] == "\t" else 1
        index += 1
    return text[index:]


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


def _property_body(line):
    return line[2:] if line.startswith("* ") else line


def _is_property(line):
    return PROPERTY_RE.match(_property_body(line)) is not None


def _is_collapsed(properties):
    for prop in properties:
        match = COLLAPSED_PROPERTY_RE.match(_property_body(prop))
        if match is not None:
            return match.group(1).strip().lower() == "true"
    return False


def _split_document_block(level, lines):
    properties = []
    content = []
    in_code = False
    for index, line in enumerate(lines):
        fence = CODE_FENCE_RE.match(line)
        if fence is not None:
            in_code = not in_code
            content.append(line)
        elif index > 0 and not in_code and _is_property(line):
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
    """Parse a Logseq-style Markdown page into a document and block tree."""
    trailing_newline = text.endswith(("\n", "\r"))
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
            blocks.extend(_split_document_block(current_level, current_lines))
        current_lines = []

    for line in text.splitlines():
        if current_level is not None and in_code:
            body = _strip_indent(line, current_indent + 2)
            current_lines.append(body)
            if body == "```":
                in_code = False
            continue

        match = DOCUMENT_BLOCK_RE.match(line)
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


def parse_block_fragment(text):
    """Parse a portable Markdown list, or return ``None`` for plain text."""
    if text is None:
        return []

    blocks = []
    indent_stack = []
    block_indents = []
    code_block = None
    code_lines = []

    for line in text.split("\n"):
        if code_block is not None:
            body = _strip_indent(line, block_indents[-1] + 2)
            if body == "```":
                code_block.text = "\n".join(code_lines)
                code_block = None
                code_lines = []
            else:
                code_lines.append(body)
            continue

        match = FRAGMENT_BLOCK_RE.match(line)
        if match is not None:
            indent, body = match.groups()
            width = _indent_width(indent)
            level = _block_level(indent_stack, width)
            fence = CODE_FENCE_RE.match(body)
            block = Block(level, "", fence.group(1) if fence else None)
            if fence is None:
                block.text = body
            blocks.append(block)
            block_indents.append(width)
            if fence is not None:
                code_block = block
                code_lines = []
            continue

        if blocks:
            body = _strip_indent(line, block_indents[-1] + 2)
            blocks[-1].text += "\n" + body

    if not blocks:
        return None
    if code_block is not None:
        code_block.text = "\n".join(code_lines)
    return blocks


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


def _serialize_blocks(blocks, include_properties, base_level=0):
    lines = []
    for block in blocks:
        level = max(0, block.level - base_level)
        indent = "  " * level
        continuation = indent + "  "
        properties = _serialized_properties(block) if include_properties else ()
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
    return lines


def serialize_document(document):
    """Serialize a document using canonical two-space Logseq indentation."""
    lines = list(document.preamble)
    lines.extend(_serialize_blocks(document.blocks, include_properties=True))
    result = "\n".join(lines)
    if document.trailing_newline and lines:
        result += "\n"
    return result


def serialize_block_fragment(blocks):
    """Serialize blocks as a normalized portable Markdown list fragment."""
    if not blocks:
        return ""
    return "\n".join(
        _serialize_blocks(
            blocks,
            include_properties=False,
            base_level=blocks[0].level,
        )
    )
