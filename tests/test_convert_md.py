from __future__ import annotations

from app.convert_md import markdown_to_confluence_storage


def test_headings_and_paragraphs():
    storage = markdown_to_confluence_storage("# Title\n\nSome text.")
    assert "<h1>Title</h1>" in storage
    assert "<p>Some text.</p>" in storage


def test_wikilink_placeholder_renders_confluence_link():
    storage = markdown_to_confluence_storage("[Example](wikilink://Example%20Title)")
    assert "<ac:link>" in storage
    assert 'ri:content-title="Example Title"' in storage


def test_code_block_uses_macro():
    storage = markdown_to_confluence_storage("```python\nprint('hi')\n```")
    assert "<ac:structured-macro ac:name=\"code\">" in storage
    assert "<ac:parameter ac:name=\"language\">python</ac:parameter>" in storage


def test_attachment_image_renders_expected_markup():
    storage = markdown_to_confluence_storage("![Alt](attachment://diagram.png)")
    assert '<ri:attachment ri:filename="diagram.png"' in storage
    assert '<ac:parameter ac:name="alt-text">Alt</ac:parameter>' in storage

