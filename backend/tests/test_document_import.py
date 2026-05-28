import io
from unittest.mock import AsyncMock, patch

import pytest

from app.services.document_import import import_file, import_url


def _docx_bytes(paragraphs: list[str]) -> bytes:
    from docx import Document
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_import_docx():
    data = _docx_bytes(["AI 重大突破", "正文第一段", "正文第二段"])
    art = await import_file(data, "report.docx", vision_cfg=None)
    assert art["title"] == "AI 重大突破"
    assert "正文第一段" in art["content"]
    assert art["source"] == "report.docx"
    assert art["url"] == ""


@pytest.mark.asyncio
async def test_import_md_uses_heading_title():
    data = b"# \xe6\xa0\x87\xe9\xa2\x98\n\xe6\xad\xa3\xe6\x96\x87"  # "# 标题\n正文"
    art = await import_file(data, "note.md", vision_cfg=None)
    assert art["title"] == "标题"
    assert "正文" in art["content"]


@pytest.mark.asyncio
async def test_import_txt_title_from_filename():
    art = await import_file("hello world".encode(), "memo.txt", vision_cfg=None)
    assert art["title"] == "memo"
    assert art["content"] == "hello world"


@pytest.mark.asyncio
async def test_import_unsupported_ext_raises():
    with pytest.raises(ValueError):
        await import_file(b"x", "a.zip", vision_cfg=None)


@pytest.mark.asyncio
async def test_import_empty_content_raises():
    with pytest.raises(ValueError):
        await import_file(b"   ", "a.txt", vision_cfg=None)


@pytest.mark.asyncio
async def test_import_url():
    with patch("app.services.document_import.FullTextFetcher") as MockFetcher:
        inst = MockFetcher.return_value
        inst.fetch_with_title = AsyncMock(return_value=("网页标题", "网页正文内容"))
        art = await import_url("https://example.com/post")
    assert art["title"] == "网页标题"
    assert art["content"] == "网页正文内容"
    assert art["url"] == "https://example.com/post"
    assert art["source"] == "example.com"
