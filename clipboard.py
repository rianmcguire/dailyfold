"""Portable clipboard formats for Dailyfold blocks."""

import json
from html import escape as html_escape

from block_markdown import parse_block_fragment, serialize_block_fragment
from inline_markdown import parse_inline, runs_to_html
from model import Block


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
    return serialize_block_fragment(blocks)


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


def blocks_from_clipboard_text(text):
    """Parse a Markdown list, or return non-list text as one block."""
    if text is None:
        return []
    blocks = parse_block_fragment(text)
    if blocks is None:
        return [Block(0, text)] if text else []
    return blocks
