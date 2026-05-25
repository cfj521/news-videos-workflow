# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

新闻视频自动化工作流系统：从新闻采集到视频发布的全链路自动化平台。

**Tech Stack**: Python (FastAPI + Celery) backend, React (Vite + TypeScript) frontend

## Architecture

### Pipeline Stages

```
[Collector] → [Processor] → [Generator] → [Composer] → [Publisher]
   抓取新闻      整理/生成脚本    生成图片素材     合成视频+配音      多平台发布
```

每个 stage 是独立的 Celery task，通过 Redis 传递状态，pipeline 支持从任意 stage 重试。

### Core Modules

- **`backend/app/pipeline/`** — 核心流水线，每个 stage 一个子包
  - `collector/` — 基于 Scrapling 的新闻抓取，支持 RSS、网页、API 多种数据源
  - `processor/` — 内容去重、摘要、视频脚本生成（通过 AI provider 接口）
  - `generator/` — 图片/视频素材生成（通过 AI provider 接口）
  - `composer/` — FFmpeg/MoviePy 视频合成、TTS 配音、唇形同步校正
  - `publisher/` — 多平台发布适配器（抖音、YouTube、B站等）

- **`backend/app/providers/`** — AI 服务的 Provider 抽象层
  - 统一接口：`TextProvider`, `ImageProvider`, `TTSProvider`, `LipSyncProvider`
  - 具体实现按需接入（Claude、OpenAI、Stable Diffusion、Edge-TTS、CosyVoice 等）
  - 通过配置文件切换 provider，不改业务代码

- **`backend/app/api/`** — FastAPI 路由层
- **`backend/app/models/`** — SQLAlchemy 数据模型
- **`frontend/`** — React 管理面板（任务监控、内容审核、手动干预）

### Data Flow

一条新闻从采集到发布的完整数据流：

```
NewsSource → RawArticle → ProcessedScript → [ImageAsset[], AudioAsset] → Video → PublishResult
```

每条数据在 DB 中有状态追踪（pending → processing → done / failed），支持断点续跑。

### Key Design Patterns

- **Provider Pattern**: 所有 AI 服务通过抽象接口调用，`backend/app/providers/base.py` 定义接口，具体实现在子模块中注册
- **Adapter Pattern**: 每个发布平台是一个 Publisher Adapter，统一 `publish(video, metadata)` 接口
- **Pipeline as State Machine**: 每个 task 有明确的状态流转，失败可单独重试

## Commands

### Backend

```bash
cd backend
pip install -e ".[dev]"          # 安装后端依赖（含开发工具）
uvicorn app.main:app --reload    # 启动 API 服务 (默认 :8000)
celery -A app.tasks worker -l info  # 启动 Celery worker
pytest                           # 运行全部测试
pytest tests/test_collector.py -k "test_rss"  # 运行单个测试
ruff check .                     # lint
ruff format .                    # format
```

### Frontend

```bash
cd frontend
pnpm install                     # 安装前端依赖
pnpm dev                         # 启动开发服务器 (默认 :5173)
pnpm build                       # 生产构建
pnpm lint                        # ESLint
pnpm test                        # Vitest
```

### Infrastructure

```bash
docker compose up -d redis       # 启动 Redis（Celery broker）
docker compose up -d             # 启动全部服务
```

## Dependencies

- **Scrapling**: 新闻抓取框架，需 Python 3.10+，安装时用 `pip install "scrapling[all]"`，首次运行 `scrapling install` 下载浏览器
- **FFmpeg**: 视频合成必须在系统 PATH 中可用
- **Redis**: Celery 消息队列

## Configuration

环境变量通过 `.env` 文件管理，`backend/app/config.py` 使用 pydantic-settings 加载。关键配置：

- `AI_TEXT_PROVIDER` / `AI_IMAGE_PROVIDER` / `AI_TTS_PROVIDER` — 选择 AI 服务 provider
- `PUBLISH_PLATFORMS` — 启用的发布平台列表
- 各 provider 的 API key 配置

## Conventions

- 中文注释和文档，代码标识符用英文
- Provider 接口用 `async def`，所有 AI 调用走异步
- Pipeline stage 之间通过 Celery task chain 串联，每个 stage 是幂等的
- 新增 AI provider 需实现 `base.py` 中对应的抽象类并在 `__init__.py` 注册
- 新增发布平台需实现 `PublisherAdapter` 接口并加到 adapter registry
