# 后端镜像：FastAPI + 进程内流水线（含 FFmpeg）
# 构建上下文为「仓库根目录」（见 docker-compose.yml 的 context: .），
# 因此 COPY 路径相对仓库根书写。
FROM python:3.12-slim-bookworm

# 系统依赖：
#   ffmpeg        —— 视频合成 / 兜底渲染（必需）
#   build-essential —— 个别依赖无 wheel 时的源码编译兜底
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        build-essential \
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

EXPOSE 8000

# 流水线跑在进程内的后台任务，无需独立 worker/broker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
