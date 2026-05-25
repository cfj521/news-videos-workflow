# Plan 5: Pipeline Engine + Stage 6 Publishing — Celery 编排 + YouTube 发布

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Stage 1-5 串联为完整的 Celery pipeline，实现 YouTube 发布，支持全自动和半自动两种运行模式，以及 CLI 触发。

**Architecture:** Celery task chain 串联 6 个 stage。每个 stage 是独立 task，通过 DB 状态追踪进度。半自动模式在审核点暂停，等待 API 调用恢复。Pipeline Engine 管理状态流转和断点恢复。

**Tech Stack:** Celery, Redis, google-api-python-client, Click (CLI)

**前置依赖:** Plan 1-4 已完成

---

### Task 1: YouTube Publisher Adapter

**Files:**
- Create: `backend/app/providers/publisher/youtube.py`
- Test: `backend/tests/test_publisher_youtube.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_publisher_youtube.py
import pytest
from unittest.mock import patch, MagicMock
from app.providers.publisher.youtube import YouTubePublisher


def test_youtube_build_metadata():
    publisher = YouTubePublisher(client_id="test", client_secret="test")
    body = publisher._build_request_body(
        title="AI 新突破",
        description="今天的科技新闻速报",
        tags=["AI", "科技", "新闻"],
    )
    assert body["snippet"]["title"] == "AI 新突破"
    assert body["snippet"]["description"] == "今天的科技新闻速报"
    assert body["snippet"]["tags"] == ["AI", "科技", "新闻"]
    assert body["snippet"]["categoryId"] == "28"  # Science & Technology
    assert body["status"]["privacyStatus"] == "public"


def test_youtube_title_truncation():
    publisher = YouTubePublisher(client_id="t", client_secret="t")
    long_title = "A" * 200
    body = publisher._build_request_body(title=long_title, description="", tags=[])
    assert len(body["snippet"]["title"]) <= 100
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_publisher_youtube.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 YouTube Publisher**

```python
# backend/app/providers/publisher/youtube.py
from pathlib import Path

from app.providers.base import PublisherAdapter, PublishResult


class YouTubePublisher(PublisherAdapter):
    def __init__(self, client_id: str = "", client_secret: str = ""):
        self._client_id = client_id
        self._client_secret = client_secret

    async def publish(
        self,
        video_path: str,
        thumbnail_path: str | None,
        title: str,
        description: str,
        tags: list[str],
    ) -> PublishResult:
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from google.oauth2.credentials import Credentials

            service = self._get_service()
            body = self._build_request_body(title, description, tags)

            media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
            request = service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )
            response = request.execute()

            video_id = response["id"]
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            if thumbnail_path and Path(thumbnail_path).exists():
                service.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_path),
                ).execute()

            return PublishResult(
                platform="youtube",
                status="success",
                url=video_url,
            )

        except Exception as e:
            return PublishResult(
                platform="youtube",
                status="failed",
                error_message=str(e),
            )

    def _build_request_body(
        self, title: str, description: str, tags: list[str],
    ) -> dict:
        return {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:30],
                "categoryId": "28",
                "defaultLanguage": "zh",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

    def _get_service(self):
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_info({
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        })
        return build("youtube", "v3", credentials=creds)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_publisher_youtube.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/publisher/youtube.py backend/tests/test_publisher_youtube.py
git commit -m "feat: add YouTube publisher adapter"
```

---

### Task 2: Pipeline Engine — 状态管理

**Files:**
- Create: `backend/app/pipeline/engine.py`
- Test: `backend/tests/test_engine.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_engine.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.base import Base
from app.models.pipeline_run import PipelineRun
from app.pipeline.engine import PipelineEngine


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_run(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="auto", video_route="hyperframes", time_range="7d")
    assert run.id is not None
    assert run.status == "pending"


def test_advance_stage(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="auto", video_route="hyperframes", time_range="7d")

    engine.start_stage(run.id, stage=1)
    updated = db_session.get(PipelineRun, run.id)
    assert updated.status == "processing"
    assert updated.current_stage == 1


def test_complete_stage(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="auto", video_route="hyperframes", time_range="7d")
    engine.start_stage(run.id, stage=1)
    engine.complete_stage(run.id, stage=1)
    updated = db_session.get(PipelineRun, run.id)
    assert updated.status == "processing"


def test_pause_for_review(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="manual", video_route="hyperframes", time_range="7d")
    engine.start_stage(run.id, stage=1)
    engine.pause_for_review(run.id, stage=1)
    updated = db_session.get(PipelineRun, run.id)
    assert updated.status == "review"


def test_fail_run(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="auto", video_route="hyperframes", time_range="7d")
    engine.fail_run(run.id, "Something went wrong")
    updated = db_session.get(PipelineRun, run.id)
    assert updated.status == "failed"
    assert updated.error_message == "Something went wrong"


def test_finish_run(db_session):
    engine = PipelineEngine(db_session)
    run = engine.create_run(mode="auto", video_route="hyperframes", time_range="7d")
    engine.finish_run(run.id)
    updated = db_session.get(PipelineRun, run.id)
    assert updated.status == "done"
    assert updated.finished_at is not None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_engine.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 Pipeline Engine**

```python
# backend/app/pipeline/engine.py
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.pipeline_run import PipelineRun


class PipelineEngine:
    def __init__(self, db: Session):
        self.db = db

    def create_run(
        self,
        mode: str = "auto",
        video_route: str = "hyperframes",
        time_range: str = "7d",
        max_articles: int = 5,
    ) -> PipelineRun:
        run = PipelineRun(
            mode=mode,
            video_route=video_route,
            time_range=time_range,
            max_articles=max_articles,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def start_stage(self, run_id: int, stage: int) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.status = "processing"
        run.current_stage = stage
        if stage == 1 and not run.started_at:
            run.started_at = datetime.now(timezone.utc)
        self.db.commit()

    def complete_stage(self, run_id: int, stage: int) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.current_stage = stage
        self.db.commit()

    def pause_for_review(self, run_id: int, stage: int) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.status = "review"
        run.current_stage = stage
        self.db.commit()

    def resume_run(self, run_id: int) -> PipelineRun:
        run = self.db.get(PipelineRun, run_id)
        run.status = "processing"
        self.db.commit()
        return run

    def fail_run(self, run_id: int, error_message: str) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.status = "failed"
        run.error_message = error_message
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()

    def finish_run(self, run_id: int) -> None:
        run = self.db.get(PipelineRun, run_id)
        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()

    def should_pause(self, run_id: int, stage: int) -> bool:
        run = self.db.get(PipelineRun, run_id)
        return run.mode == "manual"
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_engine.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/engine.py backend/tests/test_engine.py
git commit -m "feat: add pipeline engine with state management"
```

---

### Task 3: Celery Tasks 定义

**Files:**
- Create: `backend/app/tasks.py`
- Create: `backend/app/pipeline/stage6_publish.py`

- [ ] **Step 1: 实现 Stage 6**

```python
# backend/app/pipeline/stage6_publish.py
from app.providers.base import PublisherAdapter, PublishResult


async def run_stage6(
    video_path: str,
    thumbnail_path: str | None,
    title: str,
    description: str,
    tags: list[str],
    publishers: dict[str, PublisherAdapter],
    platforms: list[str] | None = None,
) -> list[PublishResult]:
    platforms = platforms or list(publishers.keys())
    results: list[PublishResult] = []

    for platform in platforms:
        publisher = publishers.get(platform)
        if not publisher:
            results.append(PublishResult(
                platform=platform, status="failed",
                error_message=f"No publisher for {platform}",
            ))
            continue

        result = await publisher.publish(
            video_path=video_path,
            thumbnail_path=thumbnail_path,
            title=title,
            description=description,
            tags=tags,
        )
        results.append(result)

    return results
```

- [ ] **Step 2: 实现 Celery tasks**

```python
# backend/app/tasks.py
import asyncio
import json
from pathlib import Path

from celery import Celery

from app.config import get_settings

settings = get_settings()
celery_app = Celery("news_videos", broker=settings.REDIS_URL)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=3)
def task_stage1(self, run_id: int):
    from app.database import create_engine_from_url, create_session_factory
    from app.pipeline.engine import PipelineEngine
    from app.pipeline.stage1_collect import run_stage1
    from app.providers.collector import create_collector_registry
    from app.models.raw_article import RawArticle

    engine_db = create_engine_from_url(settings.DATABASE_URL)
    Session = create_session_factory(engine_db)

    with Session() as db:
        pe = PipelineEngine(db)
        pe.start_stage(run_id, 1)

        try:
            run = db.get(pe.__class__.__mro__[0], run_id)
            # 简化：从 DB 读取 sources 配置
            from app.models.news_source import NewsSource
            sources_db = db.query(NewsSource).filter(NewsSource.enabled == True).all()
            sources = [
                {"name": s.name, "type": s.type, "url": s.url,
                 **(json.loads(s.config_json) if s.config_json else {})}
                for s in sources_db
            ]

            collectors = create_collector_registry(
                tavily_key=settings.TAVILY_API_KEY,
                brave_key=settings.BRAVE_SEARCH_API_KEY,
            )

            from app.models.pipeline_run import PipelineRun
            run = db.get(PipelineRun, run_id)
            articles_data = _run_async(run_stage1(
                sources=sources,
                collectors=collectors,
                time_range=run.time_range,
                max_articles=run.max_articles,
            ))

            run_dir = Path(settings.DATA_DIR) / "runs" / str(run_id) / "articles"
            run_dir.mkdir(parents=True, exist_ok=True)

            for a in articles_data:
                article = RawArticle(
                    run_id=run_id,
                    title=a.title,
                    content=a.content,
                    source_url=a.source_url,
                    source_name=a.source_name,
                    category=a.category,
                    language=a.language,
                    selected=True,
                )
                db.add(article)

            pe.complete_stage(run_id, 1)
            db.commit()

            if pe.should_pause(run_id, 1):
                pe.pause_for_review(run_id, 1)
                return {"status": "review", "run_id": run_id}

            return {"status": "done", "run_id": run_id, "article_count": len(articles_data)}

        except Exception as e:
            pe.fail_run(run_id, str(e))
            raise self.retry(exc=e, countdown=60)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/tasks.py backend/app/pipeline/stage6_publish.py
git commit -m "feat: add Celery tasks and Stage 6 publishing pipeline"
```

---

### Task 4: API 路由 — Pipeline 管理

**Files:**
- Create: `backend/app/api/pipeline.py`
- Create: `backend/app/api/sources.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_pipeline.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_api_pipeline.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import create_app
from app.models.base import Base


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    app = create_app()

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    from app.api.dependencies import get_db
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_create_pipeline_run(client):
    response = client.post("/api/pipeline/runs", json={
        "mode": "auto",
        "video_route": "hyperframes",
        "time_range": "7d",
        "max_articles": 5,
    })
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"
    assert data["id"] is not None


def test_list_pipeline_runs(client):
    client.post("/api/pipeline/runs", json={"time_range": "7d"})
    response = client.get("/api/pipeline/runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


def test_get_pipeline_run(client):
    create_resp = client.post("/api/pipeline/runs", json={"time_range": "7d"})
    run_id = create_resp.json()["id"]
    response = client.get(f"/api/pipeline/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["id"] == run_id
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_api_pipeline.py -v`
Expected: FAIL

- [ ] **Step 3: 创建 dependencies.py**

```python
# backend/app/api/dependencies.py
from typing import Generator
from sqlalchemy.orm import Session
from app.database import create_engine_from_url, create_session_factory
from app.config import get_settings


def get_db() -> Generator[Session, None, None]:
    settings = get_settings()
    engine = create_engine_from_url(settings.DATABASE_URL)
    SessionLocal = create_session_factory(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 4: 实现 API 路由**

```python
# backend/app/api/pipeline.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.models.pipeline_run import PipelineRun
from app.schemas.pipeline import PipelineRunCreate, PipelineRunRead
from app.pipeline.engine import PipelineEngine

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.post("/runs", response_model=PipelineRunRead, status_code=201)
def create_run(body: PipelineRunCreate, db: Session = Depends(get_db)):
    engine = PipelineEngine(db)
    run = engine.create_run(
        mode=body.mode,
        video_route=body.video_route,
        time_range=body.time_range,
        max_articles=body.max_articles,
    )
    return run


@router.get("/runs", response_model=list[PipelineRunRead])
def list_runs(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    runs = db.query(PipelineRun).order_by(
        PipelineRun.created_at.desc()
    ).offset(offset).limit(limit).all()
    return runs


@router.get("/runs/{run_id}", response_model=PipelineRunRead)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: int, db: Session = Depends(get_db)):
    engine = PipelineEngine(db)
    run = engine.resume_run(run_id)
    return {"status": "resumed", "run_id": run.id}
```

```python
# backend/app/api/sources.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.models.news_source import NewsSource
from app.schemas.source import NewsSourceCreate, NewsSourceRead, NewsSourceUpdate

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/", response_model=list[NewsSourceRead])
def list_sources(db: Session = Depends(get_db)):
    return db.query(NewsSource).order_by(NewsSource.priority).all()


@router.post("/", response_model=NewsSourceRead, status_code=201)
def create_source(body: NewsSourceCreate, db: Session = Depends(get_db)):
    source = NewsSource(**body.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.patch("/{source_id}", response_model=NewsSourceRead)
def update_source(
    source_id: int,
    body: NewsSourceUpdate,
    db: Session = Depends(get_db),
):
    source = db.get(NewsSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(source, key, value)
    db.commit()
    db.refresh(source)
    return source
```

```python
# backend/app/api/router.py
from fastapi import APIRouter
from app.api.pipeline import router as pipeline_router
from app.api.sources import router as sources_router

api_router = APIRouter()
api_router.include_router(pipeline_router)
api_router.include_router(sources_router)
```

- [ ] **Step 5: 更新 main.py 注册路由**

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="News Videos Workflow", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/")
    async def root():
        return {"message": "News Videos Workflow API"}

    return app


app = create_app()
```

- [ ] **Step 6: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_api_pipeline.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/ backend/app/main.py backend/tests/test_api_pipeline.py
git commit -m "feat: add API routes for pipeline and source management"
```

---

### Task 5: 全部测试 + Lint

- [ ] **Step 1: 运行完整测试**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: 全部 PASS

- [ ] **Step 2: Lint**

Run: `cd backend && ruff check . && ruff format --check .`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: finalize Plan 5 - pipeline engine, publishing, API routes"
```

---

## Plan 5 完成检查

- ✅ YouTube Publisher Adapter
- ✅ Pipeline Engine（状态管理：create/start/complete/pause/resume/fail/finish）
- ✅ Stage 6 pipeline（多平台发布）
- ✅ Celery task（Stage 1 示例，其他 stage 同理）
- ✅ API 路由：Pipeline runs CRUD + Sources CRUD
- ✅ 半自动模式支持（pause_for_review / resume）
