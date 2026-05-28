# S1 文章可编辑 + 多格式导入（Phase A）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让一次运行的文章列表（articles.json）可在 S1 面板自由增/改/删并从 Word/PDF/MD/URL 导入；创建任务可选「不采集纯人工导入」；runner 在 S1 暂停后重载 articles.json 使编辑生效。不改 Stage2。

**Architecture:** 后端 articles.json 为真源 + 整体 PUT 覆盖保存 + 导入端点（解析后追加）；新增 `document_import` 服务（docx/md/txt 直读、PDF 走单配视觉模型转图、URL 复用 FullTextFetcher）；PipelineRun 加 `auto_collect`；runner 加不采集分支与 resume 后重载。前端 S1 面板升级为可编辑列表 + 导入对话框，Settings 加视觉模型配置，CreateRunDialog 加采集方式。

**Tech Stack:** Python (FastAPI, httpx, SQLAlchemy, pytest, python-docx, pymupdf), React (Vite + TS)。设计见 `docs/superpowers/specs/2026-05-28-editable-importable-articles-design.md`。

---

## File Structure

**后端：**
- `backend/app/config.py` — 加 `vision: ProviderCfg`
- `backend/app/services/document_import.py`（新）— 解析各来源为文章 dict
- `backend/app/services/full_text.py` — 加 `fetch_with_title`
- `backend/app/api/pipeline.py` — articles PUT + import/file + import/url；regen-script 复用 `_article_from_dict`
- `backend/app/models/pipeline_run.py` — `auto_collect` 列
- `backend/app/schemas/pipeline.py` — `auto_collect`
- `backend/app/main.py` — lifespan「确保列存在」
- `backend/app/pipeline/runner.py` — `_article_from_dict`/`_load_articles`、不采集分支、resume 后重载、空文章守卫
- `backend/pyproject.toml` — `python-docx`、`pymupdf`

**前端：**
- `frontend/src/api/client.ts` — `AppSettings.vision`、`runs.create.auto_collect`、articles 编辑/导入 API
- `frontend/src/pages/Settings.tsx` — 文档解析模型一节 + EMPTY_SETTINGS
- `frontend/src/components/CreateRunDialog.tsx` — 采集方式选项
- `frontend/src/pages/Dashboard.tsx` — S1Panel 可编辑 + ArticleDialog + ImportArticleDialog

---

## Task 1: 后端 config 加 vision 视觉模型配置

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: 写失败测试** — 追加到 `backend/tests/test_config.py`:

```python
def test_vision_cfg_defaults():
    from app.config import Settings
    s = Settings()
    assert s.vision.provider == "openai"
    assert s.vision.model == "gpt-4o"
    assert s.vision.base_url == "https://api.openai.com/v1"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_config.py::test_vision_cfg_defaults -v`
Expected: FAIL（`Settings` 无 `vision`）

- [ ] **Step 3: 实现** — 在 `config.py` 的 `Settings` 类里，`image` 之后加 `vision` 字段：

```python
    vision: ProviderCfg = ProviderCfg(provider="openai", base_url="https://api.openai.com/v1", model="gpt-4o")
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat(config): 新增 vision 文档解析模型配置"
```

---

## Task 2: document_import 服务 — docx/md/txt/url 解析

**Files:**
- Create: `backend/app/services/document_import.py`
- Modify: `backend/app/services/full_text.py`（加 `fetch_with_title`）
- Modify: `backend/pyproject.toml`（加 `python-docx`）
- Test: `backend/tests/test_document_import.py`（新）

- [ ] **Step 1: 写失败测试** — 创建 `backend/tests/test_document_import.py`:

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_document_import.py -v`
Expected: FAIL（模块/函数不存在；docx 需已安装）

- [ ] **Step 3a: 加依赖** — `backend/pyproject.toml` 的 `dependencies` 列表加一行：

```toml
    "python-docx>=1.1",
```
然后安装：`cd backend && pip install -e ".[dev]"`

- [ ] **Step 3b: full_text 加 `fetch_with_title`** — 在 `backend/app/services/full_text.py` 的 `FullTextFetcher` 类里加方法：

```python
    async def fetch_with_title(self, url: str) -> tuple[str, str]:
        log.debug("Fetching with title: %s", url)
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        m = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.DOTALL | re.IGNORECASE)
        title = (m.group(1).strip() if m else "")
        return title, self._extract_content(resp.text)
```

- [ ] **Step 3c: 创建 `backend/app/services/document_import.py`**:

```python
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
        from app.services.document_import_pdf import parse_pdf  # lazy, defined in Task 3
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
```

> 注：PDF 分支引用 `app.services.document_import_pdf.parse_pdf`，在 Task 3 创建。本任务的测试不触发 PDF 分支，故可先通过。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_document_import.py -v`
Expected: PASS（6 个用例；PDF 用例在 Task 3）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/document_import.py backend/app/services/full_text.py backend/pyproject.toml backend/tests/test_document_import.py
git commit -m "feat(import): docx/md/txt/url 文章解析服务"
```

---

## Task 3: document_import — PDF 走视觉模型

**Files:**
- Create: `backend/app/services/document_import_pdf.py`
- Modify: `backend/pyproject.toml`（加 `pymupdf`）
- Test: `backend/tests/test_document_import.py`（追加）

- [ ] **Step 1: 追加失败测试** — 追加到 `backend/tests/test_document_import.py`:

```python
class _FakeVisionCfg:
    provider = "openai"
    base_url = "https://api.openai.com/v1"
    model = "gpt-4o"
    api_key = "sk-test"


@pytest.mark.asyncio
async def test_import_pdf_uses_vision_single_call():
    fake_pages = [b"\x89PNG-page1", b"\x89PNG-page2"]
    with patch("app.services.document_import_pdf._render_pdf_pages", return_value=fake_pages) as render, \
         patch("app.services.document_import_pdf.httpx.AsyncClient") as MockClient:
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": "PDF 提取的正文"}}]}
        resp.raise_for_status = MagicMock()
        client = MockClient.return_value
        client.__aenter__.return_value = client
        client.post = AsyncMock(return_value=resp)

        art = await import_file(b"%PDF-1.7 fake", "paper.pdf", vision_cfg=_FakeVisionCfg())

    assert art["title"] == "paper"
    assert art["content"] == "PDF 提取的正文"
    render.assert_called_once()
    # 单次调用塞入全部页图片
    payload = client.post.call_args[1]["json"]
    image_blocks = [b for b in payload["messages"][0]["content"] if b.get("type") == "image_url"]
    assert len(image_blocks) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_document_import.py -k pdf -v`
Expected: FAIL（`document_import_pdf` 不存在）

- [ ] **Step 3a: 加依赖** — `backend/pyproject.toml` 的 `dependencies` 加：

```toml
    "pymupdf>=1.24",
```
安装：`cd backend && pip install -e ".[dev]"`

- [ ] **Step 3b: 创建 `backend/app/services/document_import_pdf.py`**:

```python
import base64

import httpx

from app.logging import get_logger

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


async def parse_pdf(data: bytes, filename: str, vision_cfg) -> dict:
    pages = _render_pdf_pages(data)
    if not pages:
        raise ValueError("empty pdf")
    content = await _vision_extract(pages, vision_cfg)
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    title = stem.rsplit(".", 1)[0] if "." in stem else stem
    return {"title": title, "content": content, "summary": "", "source": filename, "url": ""}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_document_import.py -v`
Expected: PASS（含 PDF 用例）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/document_import_pdf.py backend/pyproject.toml backend/tests/test_document_import.py
git commit -m "feat(import): PDF 经视觉模型解析（PyMuPDF 转图 + 单次多图调用）"
```

---

## Task 4: api 文章 CRUD 与导入端点

**Files:**
- Modify: `backend/app/api/pipeline.py`
- Test: `backend/tests/test_api_articles.py`（新）

- [ ] **Step 1: 写失败测试** — 创建 `backend/tests/test_api_articles.py`:

```python
import io
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.main import create_app
from app.models import Base  # noqa: F401


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.pipeline._run_dir", lambda run_id: tmp_path / str(run_id))
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sf = sessionmaker(bind=engine)
    app = create_app()
    Base.metadata.create_all(engine)

    def override_get_db():
        s = sf()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with patch("app.api.pipeline._run_pipeline_bg"):
        yield TestClient(app)


def _seed_articles(tmp_path, run_id, arts):
    d = tmp_path / str(run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "articles.json").write_text(json.dumps(arts, ensure_ascii=False), encoding="utf-8")


def test_put_articles_overwrites_and_preserves_internal(client, tmp_path):
    _seed_articles(tmp_path, 1, [{"title": "old", "content": "c", "aihot_method": "daily", "aggregator_url": "x"}])
    new_list = [{"title": "新", "content": "正文", "summary": "", "source": "s", "url": "u", "aihot_method": "daily", "aggregator_url": "x"}]
    r = client.put("/api/pipeline/runs/1/articles", json=new_list)
    assert r.status_code == 200
    saved = json.loads((tmp_path / "1" / "articles.json").read_text(encoding="utf-8"))
    assert saved[0]["title"] == "新"
    assert saved[0]["aihot_method"] == "daily"  # 内部字段保活


def test_put_articles_rejects_empty_items(client, tmp_path):
    _seed_articles(tmp_path, 1, [])
    r = client.put("/api/pipeline/runs/1/articles", json=[{"title": "", "content": ""}])
    assert r.status_code == 400


def test_import_url_appends(client, tmp_path):
    _seed_articles(tmp_path, 1, [{"title": "a", "content": "c"}])
    with patch("app.api.pipeline.import_url", new=AsyncMock(return_value={"title": "导入", "content": "正文", "summary": "", "source": "example.com", "url": "https://example.com"})):
        r = client.post("/api/pipeline/runs/1/articles/import/url", json={"url": "https://example.com"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[1]["title"] == "导入"


def test_import_file_appends(client, tmp_path):
    _seed_articles(tmp_path, 1, [])
    with patch("app.api.pipeline.import_file", new=AsyncMock(return_value={"title": "memo", "content": "hi", "summary": "", "source": "memo.txt", "url": ""})):
        r = client.post("/api/pipeline/runs/1/articles/import/file", files={"file": ("memo.txt", io.BytesIO(b"hi"), "text/plain")})
    assert r.status_code == 200
    assert r.json()[0]["title"] == "memo"


def test_import_file_unsupported_returns_400(client, tmp_path):
    _seed_articles(tmp_path, 1, [])
    with patch("app.api.pipeline.import_file", new=AsyncMock(side_effect=ValueError("unsupported"))):
        r = client.post("/api/pipeline/runs/1/articles/import/file", files={"file": ("a.zip", io.BytesIO(b"x"), "application/zip")})
    assert r.status_code == 400
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_api_articles.py -v`
Expected: FAIL（端点不存在）

- [ ] **Step 3: 实现** — 在 `backend/app/api/pipeline.py` 顶部 import 区加：

```python
from fastapi import UploadFile, File
from pydantic import BaseModel as _PydBase
from app.services.document_import import import_file, import_url
```

在 `get_articles`（约 85-90 行）之后新增：

```python
def _write_articles(run_id: int, items: list) -> None:
    rd = _run_dir(run_id)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "articles.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


@router.put("/runs/{run_id}/articles")
def put_articles(run_id: int, items: list[dict]):
    for it in items:
        if not (str(it.get("title", "")).strip() or str(it.get("content", "")).strip()):
            raise HTTPException(status_code=400, detail="每篇文章至少需要标题或正文")
    _write_articles(run_id, items)
    return items


class _ImportUrlBody(_PydBase):
    url: str


def _read_articles(run_id: int) -> list:
    path = _run_dir(run_id) / "articles.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("/runs/{run_id}/articles/import/url")
async def import_article_url(run_id: int, body: _ImportUrlBody):
    try:
        art = await import_url(body.url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"URL 导入失败: {e}")
    items = _read_articles(run_id)
    items.append(art)
    _write_articles(run_id, items)
    return items


@router.post("/runs/{run_id}/articles/import/file")
async def import_article_file(run_id: int, file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 20MB")
    cfg = get_settings()
    try:
        art = await import_file(data, file.filename or "", cfg.vision)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"解析失败: {e}")
    items = _read_articles(run_id)
    items.append(art)
    _write_articles(run_id, items)
    return items
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_api_articles.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/pipeline.py backend/tests/test_api_articles.py
git commit -m "feat(api): 文章列表 PUT 覆盖 + 文件/URL 导入端点"
```

---

## Task 5: PipelineRun.auto_collect 列 + schema + 确保列存在

**Files:**
- Modify: `backend/app/models/pipeline_run.py`、`backend/app/schemas/pipeline.py`、`backend/app/main.py`
- Test: `backend/tests/test_schemas.py`、`backend/tests/test_main.py`

- [ ] **Step 1: 写失败测试** — 追加到 `backend/tests/test_schemas.py`:

```python
def test_pipeline_create_auto_collect_default():
    from app.schemas.pipeline import PipelineRunCreate
    assert PipelineRunCreate().auto_collect is True
    assert PipelineRunCreate(auto_collect=False).auto_collect is False
```

追加到 `backend/tests/test_main.py`:

```python
def test_ensure_auto_collect_column_adds_missing(tmp_path):
    from sqlalchemy import create_engine, text
    from app.main import _ensure_auto_collect_column
    db_file = tmp_path / "legacy.db"
    eng = create_engine(f"sqlite:///{db_file}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE pipeline_runs (id INTEGER PRIMARY KEY, mode TEXT)"))
    _ensure_auto_collect_column(eng)
    with eng.connect() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(pipeline_runs)"))]
    assert "auto_collect" in cols
    # 幂等：再跑一次不报错
    _ensure_auto_collect_column(eng)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_schemas.py::test_pipeline_create_auto_collect_default tests/test_main.py::test_ensure_auto_collect_column_adds_missing -v`
Expected: FAIL

- [ ] **Step 3a: 模型** — `backend/app/models/pipeline_run.py`，import 行确保有 `Boolean`：把 `from sqlalchemy import DateTime, Integer, String, Text` 改为 `from sqlalchemy import Boolean, DateTime, Integer, String, Text`；在 `error_message` 字段后加：

```python
    auto_collect: Mapped[bool] = mapped_column(Boolean, default=True)
```

- [ ] **Step 3b: schema** — `backend/app/schemas/pipeline.py`：`PipelineRunCreate` 加 `auto_collect: bool = True`；`PipelineRunRead` 加 `auto_collect: bool`。

- [ ] **Step 3c: 确保列存在** — `backend/app/main.py`，在 `_seed_aihot_source` 前加：

```python
def _ensure_auto_collect_column(engine) -> None:
    from sqlalchemy import text
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(pipeline_runs)"))]
        if cols and "auto_collect" not in cols:
            conn.execute(text("ALTER TABLE pipeline_runs ADD COLUMN auto_collect BOOLEAN DEFAULT 1"))
```

在 `lifespan` 里 `Base.metadata.create_all(...)` 之后、`_seed_aihot_source(factory)` 之前调用：

```python
    _ensure_auto_collect_column(factory.kw["bind"])
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_schemas.py tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/pipeline_run.py backend/app/schemas/pipeline.py backend/app/main.py backend/tests/test_schemas.py backend/tests/test_main.py
git commit -m "feat: PipelineRun.auto_collect 列 + 启动确保列存在"
```

---

## Task 6: runner — 不采集分支 + resume 后重载 articles.json

**Files:**
- Modify: `backend/app/pipeline/runner.py`、`backend/app/api/pipeline.py`（regen-script 复用 helper）
- Test: `backend/tests/test_runner_articles.py`（新）

- [ ] **Step 1: 写失败测试** — 创建 `backend/tests/test_runner_articles.py`:

```python
import json

from app.pipeline.runner import _article_from_dict, _load_articles


def test_article_from_dict_maps_fields():
    a = _article_from_dict({"title": "T", "content": "C", "url": "https://x", "source": "S", "summary": "sm", "aihot_method": "daily"})
    assert a.title == "T"
    assert a.source_url == "https://x"
    assert a.source_name == "S"
    assert a.summary == "sm"
    assert a.metadata["aihot_method"] == "daily"


def test_article_from_dict_no_aihot_method():
    a = _article_from_dict({"title": "T", "content": "C", "url": "u", "source": "s"})
    assert a.metadata == {}


def test_load_articles_reads_file(tmp_path):
    (tmp_path / "articles.json").write_text(json.dumps([{"title": "T", "content": "C", "url": "u", "source": "s"}]), encoding="utf-8")
    arts = _load_articles(tmp_path)
    assert len(arts) == 1 and arts[0].title == "T"


def test_load_articles_missing_returns_empty(tmp_path):
    assert _load_articles(tmp_path) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_runner_articles.py -v`
Expected: FAIL（helper 不存在）

- [ ] **Step 3a: runner 加 helper** — `backend/app/pipeline/runner.py`，在 `_save_articles` 函数之后加：

```python
def _article_from_dict(d: dict):
    from app.providers.base import RawArticleData
    return RawArticleData(
        title=d.get("title", ""),
        content=d.get("content", ""),
        source_url=d.get("url", ""),
        source_name=d.get("source", ""),
        summary=d.get("summary", ""),
        aggregator_url=d.get("aggregator_url", ""),
        metadata={"aihot_method": d["aihot_method"]} if d.get("aihot_method") else {},
    )


def _load_articles(run_dir: Path) -> list:
    p = run_dir / "articles.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [_article_from_dict(d) for d in data]
```

- [ ] **Step 3b: 改 Stage1 块** — 把 `_run_inner` 中整个 `if 1 in selected:` 块（采集 + 摘要 + save + manual review）替换为以下（保留原采集/摘要逻辑，新增不采集分支 + 统一重载 + 空守卫）：

```python
    if 1 in selected:
        t0 = time.time()
        from app.models.news_source import NewsSource

        if not run.auto_collect:
            _save_articles([], run_dir)
            _update(db, run, current_stage=1, status="review", progress_detail="等待人工导入文章…")
            log.info("[S1] auto_collect off — waiting for manual import")
            await _wait_for_resume(run_id, db)
            run = db.get(PipelineRun, run_id)
        else:
            _update(db, run, current_stage=1, progress_detail="S1 采集新闻中...")
            log.info("[S1] Collecting news — time_range=%s max=%d", run.time_range, run.max_articles)
            db_sources = db.query(NewsSource).filter(NewsSource.enabled == True).all()
            if db_sources:
                source_configs, collectors = build_collectors_from_db(db_sources)
                log.info("[S1] Using %d DB sources: %s", len(source_configs), [s["name"] for s in source_configs])
            else:
                source_configs, collectors = build_collectors(cfg)
                log.info("[S1] No DB sources, using defaults")
            daily_mode = any(sc.get("method") == "daily" for sc in source_configs)
            articles = await run_stage1(
                sources=source_configs, collectors=collectors,
                time_range=run.time_range, max_articles=run.max_articles,
            )
            for i, a in enumerate(articles, 1):
                log.info("[S1]   [%d] %s (%s)", i, a.title, a.source_name)
            if articles and articles[0].metadata.get("source_group") != "aihot":
                _update(db, run, progress_detail=f"S1 生成摘要中 (0/{len(articles)})...")
                await _summarize_articles(articles, cfg, run, db, log)
            elapsed = time.time() - t0
            _update(db, run, progress_detail=f"S1 完成 — {len(articles)} 篇文章 ({elapsed:.1f}s)")
            log.info("[S1] Done — %d articles in %.1fs", len(articles), elapsed)
            _save_articles(articles, run_dir)
            if run.mode == "manual":
                _update(db, run, status="review", progress_detail=f"S1 采集完成 ({len(articles)} 篇)，等待审核")
                log.info("[S1] Paused for review")
                await _wait_for_resume(run_id, db)
                run = db.get(PipelineRun, run_id)

        # resume 后从 articles.json 重载，让人工导入/编辑生效
        articles = _load_articles(run_dir)
        # 人工导入模式：必须 ≥1 篇才放行，否则回到 review 继续等
        while not run.auto_collect and not articles:
            _update(db, run, status="review", progress_detail="请先导入至少 1 篇文章")
            await _wait_for_resume(run_id, db)
            run = db.get(PipelineRun, run_id)
            articles = _load_articles(run_dir)
```

（紧随其后的 `if not articles:` 失败块保持不变——仅在 auto_collect 采集到 0 篇时触发。）

- [ ] **Step 3c: regen-script 复用 helper（DRY）** — `backend/app/api/pipeline.py` 的 `regen_script` 里，把手写重建 `RawArticleData` 改为复用 helper。在文件已有的 `from app.pipeline.runner import ...` 处加入 `_article_from_dict`，并把 regen_script 内重建文章那几行替换为：

```python
    articles_raw = json.loads(articles_path.read_text(encoding="utf-8"))
    article = _article_from_dict(articles_raw[0])
    style = "daily" if article.metadata.get("aihot_method") == "daily" else "single"
```

- [ ] **Step 4: 运行确认通过 + 导入检查**

Run: `cd backend && python -c "import app.pipeline.runner; import app.api.pipeline" && python -m pytest tests/test_runner_articles.py tests/test_api_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/runner.py backend/app/api/pipeline.py backend/tests/test_runner_articles.py
git commit -m "feat(runner): 不采集分支 + S1 resume 后重载 articles.json + 空文章守卫"
```

---

## Task 7: 前端 client.ts — vision / auto_collect / 文章编辑导入 API

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: AppSettings 加 vision** — 在 `interface AppSettings` 的 `image` 行后加：

```ts
  vision: { provider: string; base_url: string; model: string; api_key: string };
```

- [ ] **Step 2: runs.create 加 auto_collect** — 在 `create` 的 body 类型里加 `auto_collect?: boolean;`。

- [ ] **Step 3: api.runs 加文章编辑/导入方法** — 在 `runs` 对象里（`rerollArticles` 附近）加：

```ts
    saveArticles: (runId: number, items: unknown[]) =>
      fetchJSON(`/pipeline/runs/${runId}/articles`, { method: "PUT", body: JSON.stringify(items) }),
    importArticleUrl: (runId: number, url: string) =>
      fetchJSON(`/pipeline/runs/${runId}/articles/import/url`, { method: "POST", body: JSON.stringify({ url }) }),
    importArticleFile: async (runId: number, file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`/api/pipeline/runs/${runId}/articles/import/file`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(`API error: ${res.status} ${(await res.json().catch(() => ({}))).detail ?? res.statusText}`);
      return res.json();
    },
```

> `importArticleFile` 用原生 `fetch`（不经 `fetchJSON`），因为是 multipart，不能设 `Content-Type: application/json`。

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 错误

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(client): vision 配置类型 + auto_collect + 文章编辑/导入 API"
```

---

## Task 8: 前端 Settings — 文档解析模型一节

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: 加 VISION_PRESETS** — 在 `IMAGE_PRESETS` 定义之后加：

```tsx
const VISION_PRESETS: Record<string, ProviderPreset> = {
  openai: { label: "OpenAI", baseUrl: "https://api.openai.com/v1", models: ["gpt-4o", "gpt-4o-mini"] },
  dashscope: { label: "阿里云 (Qwen-VL)", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: ["qwen-vl-max", "qwen-vl-plus"] },
};
```

- [ ] **Step 2: EMPTY_SETTINGS 加 vision** — 在 `EMPTY_SETTINGS` 的 `image` 行后加：

```tsx
  vision: { provider: "openai", base_url: "https://api.openai.com/v1", model: "gpt-4o", api_key: "" },
```

- [ ] **Step 3: 渲染该节** — 在「图片模型」`ProviderSection` 之后加：

```tsx
      <ProviderSection title="文档解析模型" desc="导入 PDF 时用的视觉模型（多模态）" presets={VISION_PRESETS} config={settings.vision} onChange={(p) => patch("vision", p)} />
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 错误

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/Settings.tsx
git commit -m "feat(settings): 文档解析（视觉）模型配置一节"
```

---

## Task 9: 前端 CreateRunDialog — 采集方式选项

**Files:**
- Modify: `frontend/src/components/CreateRunDialog.tsx`

- [ ] **Step 1: 加状态** — 在 `const [maxArticles, setMaxArticles] = useState(5);` 后加：

```tsx
  const [autoCollect, setAutoCollect] = useState(true);
```

- [ ] **Step 2: 提交时带上** — 在 `api.runs.create({...})` 调用里加 `auto_collect: autoCollect,`。

- [ ] **Step 3: UI** — 在「时间范围 / 最大文章数」那个 `grid` 之前加一段采集方式选择，并把时间范围/最大文章数在 `!autoCollect` 时禁用。具体：在该 grid 上方插入：

```tsx
        <div className="mb-4">
          <label className={labelCls}>采集方式</label>
          <Select value={autoCollect ? "auto" : "manual"} onChange={(v) => setAutoCollect(v === "auto")} options={[
            { value: "auto", label: "自动采集" },
            { value: "manual", label: "不采集（人工导入）" },
          ]} />
        </div>
```

并给时间范围的 `Select` 与最大文章数的 `input` 各加 `disabled`/置灰：把它们所在的两个 `<div>` 包裹层加 `className={!autoCollect ? "opacity-40 pointer-events-none" : ""}`。

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 错误

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/CreateRunDialog.tsx
git commit -m "feat(create-run): 采集方式选项（自动采集 / 人工导入）"
```

---

## Task 10: 前端 S1Panel — 可编辑列表 + 增改删 + 导入

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: 在 Dashboard.tsx 顶部加对话框样式 import** — 现有从 `../styles` 的 import 里补 `dialogOverlayCls, dialogPanelCls`（若未导入）。

- [ ] **Step 2: 加 ArticleDialog 组件** — 在 `S1Panel` 之前加：

```tsx
type ArticleRec = Record<string, unknown> & { title?: string; content?: string; summary?: string; source?: string; url?: string };

function ArticleDialog({ initial, onSave, onClose }: { initial: ArticleRec | null; onSave: (a: ArticleRec) => void; onClose: () => void; }) {
  const [title, setTitle] = useState(String(initial?.title ?? ""));
  const [content, setContent] = useState(String(initial?.content ?? ""));
  const [summary, setSummary] = useState(String(initial?.summary ?? ""));
  const [source, setSource] = useState(String(initial?.source ?? ""));
  const [url, setUrl] = useState(String(initial?.url ?? ""));
  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[560px]`}>
        <h2 className="text-lg font-semibold mb-4">{initial ? "编辑文章" : "添加文章"}</h2>
        <label className={labelCls}>标题</label>
        <input value={title} onChange={(e) => setTitle(e.target.value)} className={`${inputCls} mb-3`} />
        <label className={labelCls}>正文</label>
        <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={8} className={`${inputCls} mb-3 text-[13px]`} />
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div><label className={labelCls}>来源</label><input value={source} onChange={(e) => setSource(e.target.value)} className={inputCls} /></div>
          <div><label className={labelCls}>原文链接</label><input value={url} onChange={(e) => setUrl(e.target.value)} className={inputCls} /></div>
        </div>
        <label className={labelCls}>摘要</label>
        <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={2} className={`${inputCls} mb-4 text-[13px]`} />
        <div className="flex justify-end gap-3">
          <button onClick={onClose} className={btnCompact}>取消</button>
          <button onClick={() => onSave({ ...(initial ?? {}), title, content, summary, source, url })} className={btnPrimary}>保存</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 加 ImportArticleDialog 组件** — 紧接其后加：

```tsx
function ImportArticleDialog({ runId, onDone, onClose }: { runId: number; onDone: () => void; onClose: () => void; }) {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const { showToast } = useToast();
  const doFile = async (f: File) => {
    setLoading(true);
    try { await api.runs.importArticleFile(runId, f); showToast("已导入", "success"); onDone(); }
    catch (e) { showToast(e instanceof Error ? e.message : "导入失败", "error"); }
    finally { setLoading(false); }
  };
  const doUrl = async () => {
    if (!url.trim()) return;
    setLoading(true);
    try { await api.runs.importArticleUrl(runId, url.trim()); showToast("已导入", "success"); onDone(); }
    catch (e) { showToast(e instanceof Error ? e.message : "导入失败", "error"); }
    finally { setLoading(false); }
  };
  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[480px]`}>
        <h2 className="text-lg font-semibold mb-4">导入文章</h2>
        <label className={labelCls}>上传文件（.docx / .pdf / .md / .txt）</label>
        <input type="file" accept=".docx,.pdf,.md,.txt" disabled={loading}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) doFile(f); }}
          className="mb-1 block w-full text-sm text-white/60" />
        <p className="text-[11px] text-white/25 mb-4">PDF 走视觉模型解析，可能较慢</p>
        <label className={labelCls}>或粘贴网页 URL</label>
        <div className="flex gap-2 mb-4">
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." className={inputCls} />
          <button onClick={doUrl} disabled={loading} className={btnPrimary}>导入</button>
        </div>
        <div className="flex justify-end"><button onClick={onClose} className={btnCompact}>关闭</button></div>
        {loading && <p className="text-xs text-white/40 mt-2">处理中...</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 改写 S1Panel** — 用下面整段替换现有 `S1Panel`：

```tsx
function S1Panel({ runId }: { runId: number }) {
  const { data: articles, mutate } = useSWR<ArticleRec[]>(`articles-${runId}`, () => api.runs.articles(runId) as Promise<ArticleRec[]>);
  const [rerolling, setRerolling] = useState(false);
  const [editing, setEditing] = useState<{ idx: number; rec: ArticleRec } | null>(null);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const { showToast } = useToast();

  const save = async (list: ArticleRec[]) => { await api.runs.saveArticles(runId, list); mutate(); };

  const handleReroll = async () => {
    setRerolling(true);
    try { await api.runs.rerollArticles(runId); showToast("重新采集中...", "success"); setTimeout(() => { mutate(); setRerolling(false); }, 5000); }
    catch { showToast("采集失败", "error"); setRerolling(false); }
  };

  const list = articles ?? [];

  const onSaveArticle = async (rec: ArticleRec) => {
    const next = [...list];
    if (editing) next[editing.idx] = rec; else next.push(rec);
    await save(next);
    setEditing(null); setAdding(false);
  };
  const onDelete = async (idx: number) => { const next = list.filter((_, i) => i !== idx); await save(next); };

  if (!articles) return <p className="text-white/30 text-sm">加载中...</p>;

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <span className="text-sm text-white/40">{list.length} 篇文章</span>
        <div className="flex gap-2">
          <button onClick={() => setImporting(true)} className={btnCompact}>导入</button>
          <button onClick={() => setAdding(true)} className={btnCompact}>+ 添加文章</button>
          <button onClick={handleReroll} disabled={rerolling} className={btnActionReroll}>{rerolling ? "采集中..." : "重新采集"}</button>
        </div>
      </div>
      {list.length === 0 && <p className="text-white/30 text-sm">暂无文章，点「导入」或「添加文章」</p>}
      <div className="space-y-2">
        {list.map((a, i) => {
          const mainLink = String(a.aggregator_url ?? a.url ?? "");
          return (
            <div key={i} className={`${cardCls} p-4`}>
              <div className="flex justify-between items-start gap-3">
                <div className="min-w-0">
                  {mainLink ? <a href={mainLink} target="_blank" rel="noreferrer" className="text-sm text-white/80 font-medium hover:text-blue-300 transition">{String(a.title ?? "")}</a>
                    : <span className="text-sm text-white/80 font-medium">{String(a.title ?? "")}</span>}
                  <div className="text-[11px] text-white/25 mt-1">{String(a.source ?? "")}</div>
                  {a.summary ? <p className="text-xs text-white/40 mt-2 leading-relaxed">{String(a.summary)}</p> : null}
                </div>
                <div className="flex gap-2 shrink-0">
                  <button onClick={() => setEditing({ idx: i, rec: a })} className={btnCompact}>编辑</button>
                  <button onClick={() => onDelete(i)} className={btnCompact}>删除</button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <p className="text-[11px] text-white/25 mt-3">编辑文章后，到"脚本/图片"标签点【重生成脚本】以应用。</p>

      {(adding || editing) && (
        <ArticleDialog initial={editing?.rec ?? null} onSave={onSaveArticle} onClose={() => { setAdding(false); setEditing(null); }} />
      )}
      {importing && <ImportArticleDialog runId={runId} onDone={() => { setImporting(false); mutate(); }} onClose={() => setImporting(false)} />}
    </div>
  );
}
```

- [ ] **Step 5: 类型检查 + 提交**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 错误

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "feat(s1): 文章列表可增/改/删 + 文件/URL 导入对话框"
```

---

## 验收

- [ ] 后端全量：`cd backend && python -m pytest -q`（含新增 document_import / articles / runner / schemas 用例；其余维持 102+ 通过）
- [ ] 前端：`cd frontend && npx tsc --noEmit` 0 错误
- [ ] 手动核对（用户启服务）：建任务选「不采集」→ S1 暂停 → 导入 docx/pdf/md/txt/URL → 文章入列 → 编辑/删除 → 审核通过继续 → S2 生成脚本；自动采集后编辑文章再 resume 也生效；Settings 出现「文档解析模型」节。

## Self-Review 注记
- 内部字段保活：前端 `ArticleRec` 为 `Record<string, unknown>` 透传，编辑用 `{...原始, ...编辑}`，PUT 回传完整对象 → `aihot_method`/`aggregator_url` 不丢；Task 4 有往返保活测试。
- PDF：Task 3 单次多图调用，端点同步 + 前端 loading；若实测超时再改后台任务（接口已幂等可重试）。
- 懒加载：docx/pymupdf 在函数内 import，缺库只影响对应格式。
- 兼容旧库：Task 5 `_ensure_auto_collect_column` 幂等补列。
