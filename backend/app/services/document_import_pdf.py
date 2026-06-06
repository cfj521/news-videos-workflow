import base64

import httpx

from app.logging import get_logger
from app.oauth.openai_oauth import build_codex_client, subscription_creds

log = get_logger("service.document_import.pdf")

MAX_PAGES = 20
DPI = 150


def _render_pdf_pages(data: bytes, max_pages: int = MAX_PAGES, dpi: int = DPI) -> list[bytes]:
    import fitz  # lazy import (pymupdf)

    doc = fitz.open(stream=data, filetype="pdf")
    pages: list[bytes] = []
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                log.warning("PDF has >%d pages, truncated", max_pages)
                break
            pix = page.get_pixmap(dpi=dpi)
            pages.append(pix.tobytes("png"))
    finally:
        doc.close()
    return pages


async def _vision_extract(images_png: list[bytes], cfg) -> str:
    if getattr(cfg, "auth_mode", "api_key") == "subscription":
        return await _vision_extract_subscription(images_png, cfg)
    # api_key 模式：裸 httpx POST 到 /chat/completions（保持原有行为不变）
    content = [{"type": "text", "text": "提取这份文档的正文为纯文本，只输出正文内容，不要任何解释或标注。"}]
    for png in images_png:
        b64 = base64.b64encode(png).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    payload = {"model": cfg.model, "messages": [{"role": "user", "content": content}], "max_tokens": 4096}
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f"{cfg.base_url.rstrip('/')}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


async def _vision_extract_subscription(images_png: list[bytes], cfg) -> str:
    """订阅模式：通过 Codex responses 端点流式解析文档图片（image_url 须为字符串 data URL）。"""
    _, token, account_id = subscription_creds()
    client = build_codex_client(token, account_id)
    content: list[dict] = [
        {"type": "input_text", "text": "提取这份文档的正文为纯文本，只输出正文内容，不要任何解释或标注。"}
    ]
    for png in images_png:
        b64 = base64.b64encode(png).decode()
        content.append({"type": "input_image", "image_url": f"data:image/png;base64,{b64}"})
    parts: list[str] = []
    async with client.responses.stream(
        model=cfg.model,
        instructions="You extract the plain text body from document images.",
        input=[{"role": "user", "content": content}],
        store=False,
    ) as stream:
        async for event in stream:
            if event.type == "response.output_text.delta":
                parts.append(event.delta or "")
    return "".join(parts)


async def parse_pdf(data: bytes, filename: str, vision_cfg) -> dict:
    pages = _render_pdf_pages(data)
    if not pages:
        raise ValueError("empty pdf")
    content = await _vision_extract(pages, vision_cfg)
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    title = stem.rsplit(".", 1)[0] if "." in stem else stem
    return {"title": title, "content": content, "summary": "", "source": filename, "url": ""}
