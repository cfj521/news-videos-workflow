<p align="right"><a href="README.md">English</a> | <b>简体中文</b></p>

# 新闻视频自动化工作流

从新闻采集到视频发布的全链路自动化平台：抓取新闻 → 生成脚本 → 生成图片/视频素材 → 合成配音视频 → 多平台发布。

**技术栈**：Python（FastAPI）后端 · React（Vite + TypeScript）前端

## 流水线

```
[Collector] → [Processor] → [Generator] → [Composer] → [Publisher]
   抓取新闻      整理/脚本      图片/视频素材    合成视频+配音      多平台发布
   S1            S2/S3          S3/S5           S4/S5             S6
```

每个 stage 在后端进程内顺序执行（FastAPI 后台任务），状态存 DB，支持从任意 stage 重试。

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

- **FFmpeg**：需在系统 PATH 中可用（视频合成）
- **ComfyUI**（可选，默认的本地图片/视频生成路线）：本机运行 ComfyUI（默认 `http://127.0.0.1:8188`），模型见 `scripts/download-comfyui-models.ps1`

## 运行

```bash
# 后端 API（流水线跑在进程内的后台任务里，无需额外的 worker/broker）
cd backend && uvicorn app.main:app --reload          # http://127.0.0.1:8000
# 前端
cd frontend && pnpm dev                              # http://127.0.0.1:5173
```

首次启动会播种默认管理员账号 **admin / admin**，登录后请在「设置 → 用户」修改密码。

## Docker 一键部署

后端 + 前端（Nginx 反代）一键起；流水线跑在后端进程内的后台任务，无需 worker/broker 容器。

```bash
cp config.yaml.example config.yaml   # 填入密钥
cp .env.example .env                  # Docker 端口 + ComfyUI 地址（可选，已有合理默认）
docker compose up -d --build
# 浏览器打开 http://localhost:8190 （默认登录 admin / admin）
```

- 端口与 ComfyUI 地址在 `.env` 配置（`FRONTEND_PORT`、`BACKEND_PORT`、`COMFYUI_URL`）。`COMFYUI_URL` 会注入后端并**覆盖** `comfyui.server_url`——无需手改 `config.yaml`。
- `config.yaml` 与 `data/` 以挂载方式注入——密钥不进镜像；SQLite 库与运行产物持久化在宿主机。
- ComfyUI 建议留在宿主机（需 GPU + 模型），后端经 `host.docker.internal` 访问。

## 测试

```bash
cd backend && pytest          # 后端
cd frontend && pnpm build     # 前端类型检查 + 构建
```

## 配置

- 首次配置：在仓库根目录复制模板 `cp config.yaml.example config.yaml`，填入 API Key 即可启动（`config.yaml` 已 gitignore，不入库）；之后推荐用设置页（`/settings`）可视化修改，保存时写回该文件。加载由 `backend/app/config.py`（pydantic + YAML）负责——**项目用根目录的 `config.yaml`，不是 `.env`**。
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
