# 一体化镜像：单容器同时托管前端 + 后端（单端口）。
# 构建上下文为「仓库根目录」（见 docker-compose.yml 的 context: .），COPY 路径相对仓库根。

# ---- Stage 1: 构建前端静态产物（→ /fe/dist）----
FROM node:22-alpine AS frontend
WORKDIR /fe
# 钉 pnpm 大版本，防未来 pnpm 大版本变更 lockfile 格式打挂 --frozen-lockfile
RUN npm i -g pnpm@10
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# ---- Stage 2: 后端 + 托管前端（FastAPI + 进程内流水线 + FFmpeg + Node/Hyperframes）----
FROM python:3.12-slim-bookworm

# Hyperframes 走 Puppeteer 无头 Chromium 截帧；用系统 chromium 并跳过 puppeteer 自带下载
#（避免构建时联网拉 chromium 失败，做法对齐 hyperframes 官方 Dockerfile.test）
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    CONTAINER=true

# 系统依赖：
#   ffmpeg          —— 视频合成 / 兜底渲染 / 音频合并（必需）
#   build-essential —— 个别 Python 依赖无 wheel 时的源码编译兜底
#   nodejs (22)     —— hyperframes 渲染需 Node>=22（npx hyperframes）
#   chromium + 运行库 —— hyperframes 经 Puppeteer 驱动无头 Chromium 截帧
#   fonts-noto-cjk  —— 无头 Chromium 渲染中文字幕 + FFmpeg 标题烧录所需 CJK 字体
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        build-essential \
        curl ca-certificates gnupg \
        chromium \
        fonts-noto-cjk fonts-liberation \
        libgbm1 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libxfixes3 libxext6 libxi6 \
        libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g hyperframes \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Python 依赖（两段，同一 RUN，用 BuildKit cache mount 缓存 pip 下载）----
# 注意：不用 --no-cache-dir（它会让 pip 不读写缓存目录，cache mount 即失效）。
# 依赖层与代码层分离，最大化缓存。
ARG WITH_PUBLISH=0
COPY requirements.txt requirements-publish.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt \
    && if [ "$WITH_PUBLISH" = "1" ]; then \
         # 抖音/快手：pip 层与浏览器层同一开关（不装浏览器的 SAU 毫无用处）。
         # requirements-publish.txt 必须在主依赖装完后再装（钉死依赖树，一起解析会回溯爆炸）。
         pip install -r requirements-publish.txt \
         && patchright install chromium \
         && CHROME=$(ls -d /root/.cache/ms-playwright/chromium-*/chrome-linux*/chrome | head -n1) \
         && mkdir -p /opt/google/chrome \
         && ln -sf "$CHROME" /opt/google/chrome/chrome; \
       else \
         echo "WITH_PUBLISH=0，跳过抖音/快手发布依赖"; \
       fi

# 应用代码 + ComfyUI 工作流模板 + 配置模板
COPY backend/ ./backend/
COPY comfyui/ ./comfyui/
COPY config.yaml.example ./config.yaml.example
COPY covers.yaml.example ./covers.yaml.example
COPY model_providers.yaml.example ./model_providers.yaml.example
COPY news_sources.yaml.example ./news_sources.yaml.example
COPY prompts.yaml.example ./prompts.yaml.example
COPY publish_targets.yaml.example ./publish_targets.yaml.example
COPY schedule.yaml.example ./schedule.yaml.example

# 前端构建产物：后端单端口托管（main.py 读 FRONTEND_DIST）
COPY --from=frontend /fe/dist /app/frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist

# 运行目录为 /app/backend（与本地 `cd backend && uvicorn` 一致）：
#   - config.py 的 CONFIG_PATH = parents[2] → /app/config.yaml（运行时挂载）
#   - database_url/data_dir 的 ../data → /app/data（运行时挂载）
#   - comfyui workflows_dir="comfyui/workflows/api" 相对 cwd 解析，
#     这里软链到仓库根的 comfyui，使其指向 /app/comfyui/workflows/api
RUN ln -sf /app/comfyui /app/backend/comfyui

WORKDIR /app/backend

EXPOSE 8189

# 流水线跑在进程内的后台任务，无需独立 worker/broker
# 端口取自环境变量 APP_PORT（由 .env 经 docker-compose 注入），缺省 8189
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8189}"]
