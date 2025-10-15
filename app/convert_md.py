"""
Markdown to Confluence Storage Format conversion utilities.

This module provides a minimal renderer that covers the required Markdown features.
It intentionally leaves several advanced edge cases as TODOs for future iterations.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import unquote

from markdown_it import MarkdownIt

BLOCK_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "blockquote",
}


def markdown_to_confluence_storage(markdown: str) -> str:
    """Convert Markdown text to Confluence storage format (XHTML subset)."""
    md = MarkdownIt("commonmark", {"linkify": True})
    rendered_html = md.render(markdown)
    translator = ConfluenceHTMLTranslator()
    translator.feed(rendered_html)
    translator.close()
    return translator.output()


class ConfluenceHTMLTranslator(HTMLParser):
    """Translate simple HTML emitted by markdown-it into Confluence storage markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._buffer: List[str] = []
        self._link_stack: List[LinkContext] = []
        self._tag_stack: List[str] = []
        self._code_block: Optional[CodeBlockContext] = None

    # HTMLParser overrides ----------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "a":
            self._link_stack.append(LinkContext.from_attrs(attrs_dict))
            return
        if tag == "pre":
            self._tag_stack.append("pre")
            return
        if tag == "code":
            if self._tag_stack and self._tag_stack[-1] == "code-inline":
                # Nested backticks; treat as literal text.
                return
            if self._is_inside_pre():
                language = _extract_language(attrs_dict.get("class"))
                self._code_block = CodeBlockContext(language=language)
                return
            self._tag_stack.append("code-inline")
            self._buffer.append("<code>")
            return
        if tag == "img":
            self._handle_image(attrs_dict)
            return

        self._tag_stack.append(tag)
        if tag in BLOCK_TAGS:
            self._buffer.append(f"<{tag}>")
        else:
            attrs_serialized = "".join(
                f' {name}="{html.escape(value)}"' for name, value in attrs if value is not None
            )
            self._buffer.append(f"<{tag}{attrs_serialized}>")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            ctx = self._link_stack.pop()
            self._buffer.append(ctx.render())
            return
        if tag == "pre":
            if self._tag_stack and self._tag_stack[-1] == "pre":
                self._tag_stack.pop()
            return
        if tag == "code":
            if self._code_block:
                self._buffer.append(self._code_block.render())
                self._code_block = None
                return
            if self._tag_stack and self._tag_stack[-1] == "code-inline":
                self._buffer.append("</code>")
                self._tag_stack.pop()
                return
        if not self._tag_stack:
            return
        last_tag = self._tag_stack.pop()
        if last_tag in BLOCK_TAGS:
            self._buffer.append(f"</{last_tag}>")
        else:
            self._buffer.append(f"</{last_tag}>")

    def handle_data(self, data: str) -> None:
        if self._code_block:
            self._code_block.append(data)
            return
        if self._link_stack:
            self._link_stack[-1].append(data)
            return
        if self._tag_stack and self._tag_stack[-1] == "code-inline":
            self._buffer.append(html.escape(data, quote=False))
            return
        self._buffer.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")

    def output(self) -> str:
        return "".join(self._buffer)

    # Helpers ----------------------------------------------------------------------

    def _is_inside_pre(self) -> bool:
        return any(tag == "pre" for tag in self._tag_stack)

    def _handle_image(self, attrs: dict[str, Optional[str]]) -> None:
        src = attrs.get("src", "") or ""
        alt = attrs.get("alt", "") or ""
        if src.startswith("attachment://"):
            filename = src.replace("attachment://", "")
            tag = (
                "<ac:image>"
                f'<ri:attachment ri:filename="{html.escape(filename)}" />'
                f"{_render_alt_parameter(alt)}"
                "</ac:image>"
            )
        else:
            tag = (
                "<ac:image>"
                f'<ri:url ri:value="{html.escape(src)}" />'
                f"{_render_alt_parameter(alt)}"
                "</ac:image>"
            )
        self._buffer.append(tag)


class LinkContext:
    """Track link metadata while parsing."""

    def __init__(self, href: str, accum: Optional[List[str]] = None):
        self.href = href
        self._buffer: List[str] = accum or []

    @classmethod
    def from_attrs(cls, attrs: dict[str, Optional[str]]) -> "LinkContext":
        return cls(href=attrs.get("href", "") or "")

    def append(self, text: str) -> None:
        self._buffer.append(text)

    def render(self) -> str:
        body = "".join(self._buffer).strip()
        if self.href.startswith("wikilink://"):
            title = unquote(self.href.replace("wikilink://", ""))
            if not body:
                body = title
            return (
                "<ac:link>"
                f'<ri:page ri:content-title="{html.escape(title)}" />'
                f"{_render_plain_text_body(body)}"
                "</ac:link>"
            )
        return (
            "<ac:link>"
            f'<ri:url ri:value="{html.escape(self.href)}" />'
            f"{_render_plain_text_body(body)}"
            "</ac:link>"
        )


class CodeBlockContext:
    """Collect fenced code content for later rendering as a Confluence macro."""

    def __init__(self, language: Optional[str]):
        self.language = language
        self._buffer: List[str] = []

    def append(self, text: str) -> None:
        self._buffer.append(text)

    def render(self) -> str:
        code_content = "".join(self._buffer)
        params = ""
        if self.language:
            params = (
                f'<ac:parameter ac:name="language">{html.escape(self.language)}</ac:parameter>'
            )
        # TODO: handle code blocks that already contain CDATA end markers.
        return (
            '<ac:structured-macro ac:name="code">'
            f"{params}"
            f"<ac:plain-text-body><![CDATA[{code_content}]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )


def _extract_language(class_attr: Optional[str]) -> Optional[str]:
    if not class_attr:
        return None
    parts = class_attr.split()
    for part in parts:
        if part.startswith("language-"):
            return part.replace("language-", "", 1)
    return None


def _render_plain_text_body(text: str) -> str:
    if not text:
        return ""
    return f"<ac:plain-text-link-body><![CDATA[{text}]]></ac:plain-text-link-body>"


def _render_alt_parameter(alt: str) -> str:
    if not alt:
        return ""
    return f'<ac:parameter ac:name="alt-text">{html.escape(alt)}</ac:parameter>'
