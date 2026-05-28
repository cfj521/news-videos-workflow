from urllib.parse import urlparse

from app.logging import get_logger
from app.services.full_text import FullTextFetcher

log = get_logger("service.document_import")

SUPPORTED_EXTS = {".docx", ".pdf", ".md", ".txt"}


def _stem(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def _ext(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


def _parse_docx(data: bytes, filename: str) -> dict:
    import io

    from docx import Document  # lazy import

    doc = Document(io.BytesIO(data))
    paras = [p.text for p in doc.paragraphs if p.text.strip()]
    content = "\n".join(paras)
    title = (paras[0][:200] if paras else _stem(filename))
    return {"title": title, "content": content, "summary": "", "source": filename, "url": ""}


def _parse_text(data: bytes, filename: str, ext: str) -> dict:
    text = data.decode("utf-8", errors="replace")
    title = _stem(filename)
    if ext == ".md":
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
    return {"title": title, "content": text, "summary": "", "source": filename, "url": ""}


async def import_file(data: bytes, filename: str, vision_cfg) -> dict:
    ext = _ext(filename)
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"unsupported file type: {ext or '(none)'}")
    if ext == ".docx":
        art = _parse_docx(data, filename)
    elif ext == ".pdf":
        from app.services.document_import_pdf import parse_pdf  # lazy, defined in a later task
        art = await parse_pdf(data, filename, vision_cfg)
    else:
        art = _parse_text(data, filename, ext)
    if not art["content"].strip():
        raise ValueError("empty content")
    return art


async def import_url(url: str) -> dict:
    fetcher = FullTextFetcher()
    title, content = await fetcher.fetch_with_title(url)
    if not content.strip():
        raise ValueError("empty content")
    host = urlparse(url).hostname or url
    return {"title": title or host, "content": content, "summary": "", "source": host, "url": url}
