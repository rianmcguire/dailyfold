"""Portable clipboard formats for Dailyfold blocks."""

import json
import re
from html import escape as html_escape

from markdown import parse_inline, runs_to_html
from model import Block


CLIPBOARD_BULLET_RE = re.compile(r"^([ \t]*)[-*+] (.*)$")
CLIPBOARD_CODE_FENCE_RE = re.compile(r"^```([a-zA-Z0-9_+\-]*)$")
CLIPBOARD_BLOCKS_TARGET = "application/x-dailyfold-blocks+json"
CLIPBOARD_HTML_TARGET = "text/html"
CLIPBOARD_BLOCKS_INFO = 1
CLIPBOARD_HTML_INFO = 2
CLIPBOARD_TEXT_INFO = 3


def link_from_paste(selected_text, clipboard_text):
    """Return a Markdown link when the clipboard contains one web URL."""
    if not selected_text or clipboard_text is None:
        return None
    url = clipboard_text.strip()
    inline = parse_inline(url)
    if (
        not url
        or not inline.runs
        or inline.display_text != url
        or any(run.link_url != url for run in inline.runs)
    ):
        return None

    label = selected_text.replace("]", r"\]")
    destination = (
        url.replace("\\", r"\\")
        .replace("(", r"\(")
        .replace(")", r"\)")
    )
    return f"[{label}]({destination})"


def copy_blocks(blocks):
    """Clone blocks and normalize them into a self-contained outline."""
    if not blocks:
        return []
    base_level = blocks[0].level
    return [
        Block(
            max(0, block.level - base_level),
            block.text,
            block.code_lang,
            block.collapsed,
            block.properties,
        )
        for block in blocks
    ]


def blocks_to_clipboard_text(blocks):
    """Serialize blocks as a portable Markdown list."""
    lines = []
    for block in copy_blocks(blocks):
        bullet_indent = "  " * block.level
        continuation_indent = "  " * (block.level + 1)
        if block.code_lang is not None:
            lines.append(f"{bullet_indent}- ```{block.code_lang}")
            lines.extend(continuation_indent + line for line in block.text.split("\n"))
            lines.append(f"{continuation_indent}```")
            continue

        text_lines = block.text.split("\n")
        lines.append(f"{bullet_indent}- {text_lines[0]}")
        lines.extend(continuation_indent + line for line in text_lines[1:])
    return "\n".join(lines)


def _inline_html(text):
    return runs_to_html(parse_inline(text).runs)


def blocks_to_clipboard_html(blocks):
    """Serialize blocks as a semantic nested HTML list."""
    normalized = copy_blocks(blocks)
    if not normalized:
        return ""

    def render_level(start, level):
        parts = ["<ul>"]
        i = start
        while i < len(normalized):
            block = normalized[i]
            if block.level < level:
                break
            if block.level > level:
                children, i = render_level(i, level + 1)
                parts.append(children)
                continue

            if block.code_lang is not None:
                language = (
                    f' class="language-{html_escape(block.code_lang, quote=True)}"'
                    if block.code_lang
                    else ""
                )
                content = (
                    f"<pre><code{language}>{html_escape(block.text)}</code></pre>"
                )
            else:
                content = _inline_html(block.text)
            parts.append(f"<li>{content}")
            i += 1
            if i < len(normalized) and normalized[i].level > level:
                children, i = render_level(i, level + 1)
                parts.append(children)
            parts.append("</li>")
        parts.append("</ul>")
        return "".join(parts), i

    rendered, _ = render_level(0, 0)
    return rendered


def blocks_to_clipboard_payload(blocks):
    normalized = copy_blocks(blocks)
    return json.dumps(
        {
            "version": 1,
            "blocks": [
                {
                    "level": block.level,
                    "text": block.text,
                    "code_lang": block.code_lang,
                    "collapsed": block.collapsed,
                    "properties": list(block.properties),
                }
                for block in normalized
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def blocks_from_clipboard_payload(payload):
    try:
        value = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or value.get("version") != 1:
        return None
    raw_blocks = value.get("blocks")
    if not isinstance(raw_blocks, list):
        return None

    blocks = []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            return None
        level = raw.get("level")
        text = raw.get("text")
        code_lang = raw.get("code_lang")
        collapsed = raw.get("collapsed")
        properties = raw.get("properties", [])
        if isinstance(level, bool) or not isinstance(level, int) or level < 0:
            return None
        if not isinstance(text, str):
            return None
        if code_lang is not None and not isinstance(code_lang, str):
            return None
        if not isinstance(collapsed, bool):
            return None
        if not isinstance(properties, list) or not all(
            isinstance(prop, str) for prop in properties
        ):
            return None
        blocks.append(Block(level, text, code_lang, collapsed, tuple(properties)))
    return blocks


def _indent_width(indent):
    return sum(2 if char == "\t" else 1 for char in indent)


def _strip_indent(text, width):
    consumed = 0
    i = 0
    while i < len(text) and consumed < width and text[i] in " \t":
        consumed += 2 if text[i] == "\t" else 1
        i += 1
    return text[i:]


def blocks_from_clipboard_text(text):
    """Parse a Markdown list, or return non-list text as one block."""
    if text is None:
        return []
    lines = text.split("\n")
    blocks = []
    indent_stack = []
    block_indents = []
    code_block = None
    code_lines = []

    for line in lines:
        if code_block is not None:
            body = _strip_indent(line, block_indents[-1] + 2)
            if body == "```":
                code_block.text = "\n".join(code_lines)
                code_block = None
                code_lines = []
            else:
                code_lines.append(body)
            continue

        match = CLIPBOARD_BULLET_RE.match(line)
        if match is not None:
            indent, body = match.groups()
            width = _indent_width(indent)
            if not indent_stack:
                indent_stack.append(width)
            elif width > indent_stack[-1]:
                indent_stack.append(width)
            else:
                while indent_stack and width < indent_stack[-1]:
                    indent_stack.pop()
                if not indent_stack or width != indent_stack[-1]:
                    indent_stack.append(width)
            level = len(indent_stack) - 1
            fence = CLIPBOARD_CODE_FENCE_RE.match(body)
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
        return [Block(0, text)] if text else []
    if code_block is not None:
        code_block.text = "\n".join(code_lines)
    return copy_blocks(blocks)
