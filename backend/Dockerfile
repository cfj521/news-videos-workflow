# 后端镜像：FastAPI + 进程内流水线（含 FFmpeg + Node/Hyperframes）
# 构建上下文为「仓库根目录」（见 docker-compose.yml 的 context: .），
# 因此 COPY 路径相对仓库根书写。
FROM python:3.12-slim-bookworm

# Hyperframes 走 Puppeteer 无头 Chromium 截帧；用系统 chromium 并跳过 puppeteer 自带下载
#（避免构建时联网拉 chromium 失败，做法对齐 hyperframes 官方 Dockerfile.test）
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    CONTAINER=true

# 系统依赖：
#   ffmpeg          —— 视频合成 / 兜底渲染（必需）
#   build-essential —— 个别 Python 依赖无 wheel 时的源码编译兜底
#   nodejs (22)     —— hyperframes 渲染需 Node>=22（npx hyperframes）
#   chromium + 运行库 —— hyperframes 经 Puppeteer 驱动无头 Chromium 截帧
#   fonts-noto-cjk  —— 无头 Chromium 渲染中文字幕所需字体（否则显示方块）
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

# 依赖层（与代码分离，最大化缓存）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码 + ComfyUI 工作流模板 + 配置模板
COPY backend/ ./backend/
COPY comfyui/ ./comfyui/
COPY config.yaml.example ./config.yaml.example

# 运行目录为 /app/backend（与本地 `cd backend && uvicorn` 一致）：
#   - config.py 的 CONFIG_PATH = parents[2] → /app/config.yaml（运行时挂载）
#   - database_url/data_dir 的 ../data → /app/data（运行时挂载）
#   - comfyui workflows_dir="comfyui/workflows/api" 相对 cwd 解析，
#     这里软链到仓库根的 comfyui，使其指向 /app/comfyui/workflows/api
RUN ln -sf /app/comfyui /app/backend/comfyui

WORKDIR /app/backend

EXPOSE 8189

# 流水线跑在进程内的后台任务，无需独立 worker/broker
# 端口取自环境变量 BACKEND_PORT（由 .env 经 docker-compose 注入），缺省 8189
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-8189}"]
