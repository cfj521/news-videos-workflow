#!/usr/bin/env bash
# ============================================================================
# 在 WSL 中原生安装 ComfyUI 并注册为 systemd 服务（GPU 直通，无需 Docker）
#
# 适用：WSL2 + 已装 Windows 侧 NVIDIA 驱动（CUDA 直通到 WSL）+ WSL 内 Linux 版 conda
# 产出：~/comfyui 下的 ComfyUI；conda 环境 comfyui；/etc/systemd/system/comfyui.service
#       开机自启、崩溃自动重启、监听 0.0.0.0:8188
#
# 前置：WSL 内需有 Linux 版 Miniconda（注意 Windows 的 conda 不能用于 WSL 原生进程）：
#   wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
#   bash /tmp/miniconda.sh -b -p $HOME/miniconda3 && $HOME/miniconda3/bin/conda init bash && exec bash
#
# 用法：
#   bash scripts/setup-comfyui-wsl.sh
#
# 可用环境变量覆盖默认值（示例）：
#   COMFYUI_DIR=~/comfyui  MODELS_DIR=/mnt/d/models/comfyui  COMFYUI_PORT=8188 \
#   TORCH_CUDA=cu128  COMFYUI_REF=master  CONDA_ENV=comfyui  PY_VERSION=3.12 \
#   bash scripts/setup-comfyui-wsl.sh
#
# 模型说明：默认读取 Windows 侧 /mnt/d/models/comfyui（经 extra_model_paths.yaml），
#   省去搬运 180GB；代价是模型加载经 9P 较慢（推理本身不受影响）。若追求加载速度，
#   把模型拷进 WSL ext4 目录并把 MODELS_DIR 指过去即可。
# ============================================================================
set -euo pipefail

# ---- 可配置项 ----
COMFYUI_DIR="${COMFYUI_DIR:-$HOME/comfyui}"
MODELS_DIR="${MODELS_DIR:-/mnt/d/models/comfyui}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
TORCH_CUDA="${TORCH_CUDA:-cu128}"          # 对齐 CUDA 12.8
COMFYUI_REF="${COMFYUI_REF:-master}"        # 可钉 tag，如 v0.24.0
CONDA_ENV="${CONDA_ENV:-comfyui}"           # conda 环境名
PY_VERSION="${PY_VERSION:-3.12}"            # conda 环境的 Python 版本
REPO_URL="https://github.com/comfyanonymous/ComfyUI.git"
SERVICE_NAME="comfyui"
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"

log() { printf '\033[1;36m[setup]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 0) 前置检查 ----
[ -d /run/systemd/system ] || die "未检测到 systemd。请在 /etc/wsl.conf 写入：
  [boot]
  systemd=true
然后在 Windows 执行 'wsl --shutdown' 重启 WSL，再重跑本脚本。"

command -v git >/dev/null || die "缺少 git，请先：sudo apt-get install -y git"
command -v conda >/dev/null || die "WSL 内未找到 conda（注意：Windows 的 conda 不能用于 WSL 原生进程）。
请先在 WSL 装 Linux 版 Miniconda：
  wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
  bash /tmp/miniconda.sh -b -p \$HOME/miniconda3 && \$HOME/miniconda3/bin/conda init bash && exec bash
然后重跑本脚本。"
CONDA_BASE="$(conda info --base)"
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"   # 让本脚本（非交互）能用 conda activate

if [ ! -e /usr/lib/wsl/lib/libcuda.so.1 ]; then
  log "警告：未发现 /usr/lib/wsl/lib/libcuda.so.1 —— 请确认 Windows 侧已装 NVIDIA 驱动且 WSL 为 GPU 模式。继续安装，但 GPU 可能不可用。"
fi

# ---- 1) 拉取 / 更新 ComfyUI 源码 ----
if [ -d "$COMFYUI_DIR/.git" ]; then
  log "更新已存在的 ComfyUI（$COMFYUI_DIR）..."
  git -C "$COMFYUI_DIR" fetch --depth 1 origin "$COMFYUI_REF"
  git -C "$COMFYUI_DIR" checkout -q FETCH_HEAD
else
  log "克隆 ComfyUI 到 $COMFYUI_DIR（ref=$COMFYUI_REF）..."
  git clone --depth 1 --branch "$COMFYUI_REF" "$REPO_URL" "$COMFYUI_DIR" 2>/dev/null \
    || git clone --depth 1 "$REPO_URL" "$COMFYUI_DIR"  # ref 非分支名时退化为默认分支
fi

# ---- 2) conda 环境 + PyTorch(cu128) + 依赖 ----
if conda env list | awk '{print $1}' | grep -qx "$CONDA_ENV"; then
  log "复用已存在的 conda 环境：$CONDA_ENV"
else
  log "创建 conda 环境 $CONDA_ENV (python=$PY_VERSION)..."
  # 仅用 conda-forge 建环境：绕开 Anaconda 官方源(pkgs/main,pkgs/r)的 ToS 门槛
  # 必须显式带 pip —— conda-forge 的 python 不会自动装 pip
  conda create -y -n "$CONDA_ENV" -c conda-forge --override-channels "python=$PY_VERSION" pip
fi
conda activate "$CONDA_ENV"
# 兜底：已存在但缺 pip 的旧环境（conda-forge python 默认无 pip）补一下
python -m pip --version >/dev/null 2>&1 \
  || conda install -y -n "$CONDA_ENV" -c conda-forge --override-channels pip
ENV_PY="$(command -v python)"   # systemd 将直接用这个绝对路径，无需 activate
log "使用环境：$CONDA_ENV  →  $ENV_PY"

log "升级 pip..."
python -m pip install --upgrade pip wheel >/dev/null

log "安装 PyTorch（$TORCH_CUDA 轮子）..."
python -m pip install torch torchvision torchaudio \
  --index-url "https://download.pytorch.org/whl/$TORCH_CUDA"

log "安装 ComfyUI 依赖..."
python -m pip install -r "$COMFYUI_DIR/requirements.txt" \
  --extra-index-url "https://download.pytorch.org/whl/$TORCH_CUDA"

log "校验 GPU 是否可用..."
python - <<'PY'
import torch
print(f"  torch={torch.__version__}  cuda_available={torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"  device={torch.cuda.get_device_name(0)}")
else:
    print("  ⚠️ CUDA 不可用：检查 Windows 驱动 / WSL GPU 模式 / torch 是否装成了 CPU 版")
PY
conda deactivate

# ---- 3) extra_model_paths.yaml —— 指向已有模型目录 ----
if [ -d "$MODELS_DIR" ]; then
  log "写 extra_model_paths.yaml，指向模型目录：$MODELS_DIR"
  cat > "$COMFYUI_DIR/extra_model_paths.yaml" <<YAML
# 由 setup-comfyui-wsl.sh 生成：复用 Windows 侧已下载的模型，避免搬运
nvw_models:
    base_path: $MODELS_DIR
    checkpoints: checkpoints
    diffusion_models: diffusion_models
    text_encoders: text_encoders
    vae: vae
    loras: loras
    upscale_models: latent_upscale_models
YAML
else
  log "警告：模型目录 $MODELS_DIR 不存在，跳过 extra_model_paths.yaml。"
  log "      模型下好后可手动建立，或重设 MODELS_DIR 重跑本脚本。"
fi

# ---- 4) 安装 systemd 服务 ----
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
log "写入 systemd 单元：$UNIT_PATH（需要 sudo）"
sudo tee "$UNIT_PATH" >/dev/null <<UNIT
[Unit]
Description=ComfyUI (news-videos-workflow)
After=network.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$COMFYUI_DIR
# WSL 的 CUDA 用户态库目录，确保原生进程能找到 libcuda
Environment=LD_LIBRARY_PATH=/usr/lib/wsl/lib
ExecStart=$ENV_PY $COMFYUI_DIR/main.py --listen 0.0.0.0 --port $COMFYUI_PORT --disable-auto-launch
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

log "启用并启动服务..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

# ---- 5) 收尾提示 ----
sleep 2
log "服务状态："
sudo systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,6p' || true

cat <<DONE

安装完成。
  UI:        http://localhost:$COMFYUI_PORT
  查看日志:  journalctl -u $SERVICE_NAME -f
  重启:      sudo systemctl restart $SERVICE_NAME
  停止:      sudo systemctl stop $SERVICE_NAME

后端对接（容器内访问宿主 ComfyUI）：
  .env 里保持 COMFYUI_URL=http://host.docker.internal:$COMFYUI_PORT 即可，
  然后 docker compose up -d backend 让其重连。

验证连通（从 backend 容器内，打印 200 即成功）：
  docker exec nvw-backend python -c "import urllib.request;print(urllib.request.urlopen('http://host.docker.internal:$COMFYUI_PORT/system_stats').status)"
DONE
