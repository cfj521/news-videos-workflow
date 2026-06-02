# 新闻视频自动化工作流

从新闻采集到视频发布的全链路自动化平台：抓取新闻 → 生成脚本 → 生成图片/视频素材 → 合成配音视频 → 多平台发布。

**技术栈**：Python（FastAPI + Celery）后端 · React（Vite + TypeScript）前端

## 流水线

```
[Collector] → [Processor] → [Generator] → [Composer] → [Publisher]
   抓取新闻      整理/脚本      图片/视频素材    合成视频+配音      多平台发布
   S1            S2/S3          S3/S5           S4/S5             S6
```

每个 stage 是独立的 Celery task，状态存 DB，支持从任意 stage 重试。

## 环境准备

### 后端（conda + requirements.txt）

依赖统一在根目录 `requirements.txt`，`backend/pyproject.toml` 只保留 ruff / pytest 配置。

```bash
conda create -n env_news_videos_wf python=3.12
conda activate env_news_videos_wf
pip install -r requirements.txt        # 含发布可选依赖 biliup / google-*
```

### 前端

```bash
cd frontend
pnpm install
```

### 基础设施 / 外部依赖

- **Redis**（Celery broker）：`docker compose up -d redis`
- **FFmpeg**：需在系统 PATH 中可用（视频合成）
- **ComfyUI**（可选，默认的本地图片/视频生成路线）：本机运行 ComfyUI（默认 `http://127.0.0.1:8188`），模型见 `scripts/download-comfyui-models.ps1`

## 运行

```bash
# 后端 API
cd backend && uvicorn app.main:app --reload          # http://127.0.0.1:8000
# Celery worker（另开终端）
cd backend && celery -A app.tasks worker -l info
# 前端
cd frontend && pnpm dev                              # http://127.0.0.1:5173
```

## 测试

```bash
cd backend && pytest          # 后端
cd frontend && pnpm build     # 前端类型检查 + 构建
```

## 配置

- 运行时配置走设置页（`/settings`）→ 持久化到 YAML，`backend/app/config.py`（pydantic-settings）加载。
- **AI 服务**：文本 / 图片 / 视觉 / 语音 provider（商用 API 或本地 ComfyUI）。
- **ComfyUI**：图片（z_image / qwen）与视频（wan5b / wan14b / lightx2v / ltx）的 workflow 选择与每流 steps/cfg 参数。
- **发布平台**：凭证在「发布管理」页按平台配置（存 DB），不写在配置文件里。

## 发布

支持 YouTube、Bilibili 等。各平台所需账号/Cookie/Token 的申请与填写，见 **[docs/video-publish-guide.md](docs/video-publish-guide.md)**：

- **YouTube**：OAuth（Client ID + Client Secret + Refresh Token），需先在 OAuth Playground 获取 refresh_token，应用须设「外部 + 正式版」。
- **Bilibili**：浏览器 Cookie（SESSDATA + bili_jct 必填，DedeUserID/buvid3/buvid4 建议），基于 biliup 投稿。

## 文档

- [docs/video-publish-guide.md](docs/video-publish-guide.md) — 发布平台账号申请与配置（操作向）
- [docs/video-publish-api-reference.md](docs/video-publish-api-reference.md) — 发布适配器 API 参考
- [CLAUDE.md](CLAUDE.md) — 架构、模块划分、约定（开发者向）
- `comfyui/` — ComfyUI 工作流 JSON 与调用说明
