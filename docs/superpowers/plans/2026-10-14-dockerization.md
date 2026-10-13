# 实施计划：Docker 化部署

日期：2026-10-14

## 背景与现状

- 当前推荐部署是 systemd 裸机（`deploy/README.md`），Docker 方案曾存在但已归档（`deploy/docker-archive/`）。
- **归档的 Docker 文件已过时，直接恢复会构建失败**：
  1. **硬失败主因**：前端用 `npm ci`，但仓库只有 `pnpm-lock.yaml`（无 `package-lock.json`）——`npm ci` 无 lockfile 必挂。
  2. 前端构建基于 `node:20-alpine`。按 README 口径 Vite 8 需要 Node ≥ 20.19 / 22.12，故 node20 是否满足取决于具体小版本——不是硬失败点，但新方案统一用 `node:22-alpine` 消除歧义、留足余量。
  3. compose 只挂载 `config.yaml` + `data/`，漏掉后来新增的 6 个 YAML store 文件（`model_providers.yaml` / `news_sources.yaml` / `publish_targets.yaml` / `schedule.yaml` / `prompts.yaml` / `covers.yaml`）与 `publish_cookies/`（抖音/快手登录态）。
- 代码侧无需改动：`main.py` 支持 `FRONTEND_DIST` 托管前端；`comfyui/client.py` / `comfyui/wake.py` 已支持 `NV_COMFYUI_URL` 环境变量覆盖 ComfyUI 地址；`tzlocal` 跟随系统时区（容器内即 `TZ` 环境变量）；`config.py` 对 `config.yaml` 是目录时有专门报错兜底。
- **最大坑 A — bind mount 目录陷阱**：bind mount 的宿主路径不存在时，Docker 自动建**空目录**顶替文件。`config.py` 只对 `config.yaml` 有目录兜底报错，6 个 store（`_io.load_yaml`）没有——直接 `open(目录)` 崩溃。因此首启必须先把 7 个 YAML 从 `.example` 模板创建成真实文件（`docker/setup.sh` 解决）。
- **最大坑 B — 原子写 vs 文件 bind mount → EBUSY（review 新发现）**：`_io.save_yaml`（`backend/app/store/_io.py:54-76`）用 `mkstemp + os.replace` 原子写，而 `os.replace` 到**单文件 bind mount 的目标路径**（即挂载点）返回 `EBUSY`（OSError 16）。后果：即便 setup.sh 预创建了 7 个真实文件（躲过坑 A），**任何一次设置保存**（providers/sources/targets/schedules/prompts/cover 任一 store，乃至 `config.py:519-529` 内联调用的 `save_settings`）都会崩溃；只有 `config.yaml`（`config.py:436-439` 原地 `open("w")` 截断写、保 inode）能正常落盘。**修复**：把 `_io.save_yaml` 改原地 `open("w")` 写（对齐 `config.py`），这是单进程单写者场景可接受的一行级改动（`_io.py` 文档串本就写明单进程线程锁模型，无跨进程原子性需求）。**这打破"不改任何业务代码"原则**，需把该原则降级为"不改业务逻辑，仅对齐 `_io.save_yaml` 的写盘方式"。

## 设计原则

1. **单容器一体化**：前端静态产物 + FastAPI 后端 + 进程内流水线 + APScheduler 调度器，一个进程一个端口，与 systemd 部署完全同构，**不改业务逻辑**——唯一的代码改动是坑 B 的 `_io.save_yaml` 写盘方式对齐（原子写 → 原地写），非业务行为变更。
2. **多阶段构建**：`node:22-alpine`（pnpm 构建前端）→ `python:3.12-slim-bookworm`（运行时，含 ffmpeg / chromium / hyperframes）。
3. **密钥与数据不进镜像**：7 个配置 YAML、`data/`（SQLite + `.auth_secret` + 运行产物 + 封面图 + 日志）、`publish_cookies/` 全部 bind mount。
4. **可复现**：pip 按现有 `requirements.txt` 原样安装（冲突链已钉死）；前端 `pnpm install --frozen-lockfile`；BuildKit cache mount 加速。
5. **可选功能 build arg 开关**：抖音/快手浏览器自动化默认不装，`WITH_PUBLISH=1` 开启。
6. **容器内 root 运行**：单租户主机、内网可信环境；挂载目录权限在 Windows Docker Desktop 下做属主很麻烦，文档写明取舍。

## 文件布局（全部在仓库根）

```
Dockerfile                     # 多阶段，构建上下文 = 仓库根
docker-compose.yml             # 单服务 + 挂载 + healthcheck
.dockerignore                  # 更新自归档版（补 6 个含凭证 yaml + publish_cookies/ 的构建上下文卫生）
.env.example                   # APP_PORT / COMFYUI_URL / TZ / WITH_PUBLISH
docker/setup.sh                # 首启准备：从 7 个 .example 模板创建 YAML
docker/README.md               # Docker 部署手册
```

## Dockerfile 设计（要点）

### Stage 1 — 前端构建

- 基础镜像 `node:22-alpine`。
- `npm i -g pnpm@10`（钉大版本，防未来 pnpm 大版本变更 lockfile 格式打挂 `--frozen-lockfile`）→ `pnpm install --frozen-lockfile` → `pnpm build`。
- 产出 `dist/`，供 Stage 2 COPY。

### Stage 2 — 运行时（python:3.12-slim-bookworm）

- **系统依赖（apt）**：
  - `ffmpeg`：视频合成 / 兜底渲染 / 音频合并（必需）。
  - `fonts-noto-cjk` + `fonts-liberation`：hyperframes 无头 Chromium 渲染中文字幕、FFmpeg 路标题烧录（代码可自动探测 Linux CJK 字体）。
  - `chromium` + 全套 X 运行库（libgbm1 / libnss3 / libnspr4 / libatk* / libcups2 / libxkbcommon0 / libxcomposite1 / libxdamage1 / libxrandr2 / libxfixes3 / libxext6 / libxi6 / libpango / libcairo2 / libasound2 / libatspi2.0-0）：hyperframes 走 Puppeteer 驱动无头 Chromium 截帧。
  - `build-essential`：个别 Python 依赖无 wheel 时的源码编译兜底。
  - Node 22（NodeSource）+ `npm i -g hyperframes`：避免首渲染时 npx 联网拉包。
  - 环境变量 `PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true`、`PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium`、`CONTAINER=true`（对齐 hyperframes 官方 Dockerfile.test 做法，避免构建时联网拉 chromium）。
- **Python 依赖（pip，两段）**：依赖层与代码层分离，最大化缓存。用 BuildKit `--mount=type=cache` 缓存 pip 下载（**不用 `--no-cache-dir`**——它会让 pip 不读写缓存目录，cache mount 即失效；原归档版 `--no-cache-dir` 表述废止）。
  1. `pip install -r requirements.txt`（主依赖）。
  2. `WITH_PUBLISH=1` 时：再 `pip install -r requirements-publish.txt`（social-auto-upload 钉死依赖树，必须后装——`requirements-publish.txt` 注释写明与主文件一起解析会回溯爆炸）。
- **SAU 浏览器（与 pip 层同一开关 `WITH_PUBLISH`）**：不装浏览器的 SAU 毫无用处，故 pip 层与浏览器层**同生同死**，由单一 `ARG WITH_PUBLISH` 控制（不再有独立的 `WITH_SAU` ARG——review 指出双开关会导致 compose 只接前者、浏览器层永远为 0、验收测试 5 必挂）。`WITH_PUBLISH=1` 时：
  - `patchright install chromium`（下载浏览器内核到 root 的 `~/.cache/ms-playwright`）。
  - 软链 `~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome` → `/opt/google/chrome/chrome`（抖音 uploader 写死 `channel="chrome"` 的已知限制；快手 uploader 支持 `LOCAL_CHROME_PATH`，无需软链）。
- **应用代码**：
  - `COPY backend/ comfyui/` + 7 个 `*.yaml.example` 模板（镜像内调试用）。
  - `COPY --from=frontend /fe/dist /app/frontend/dist`，`ENV FRONTEND_DIST=/app/frontend/dist`。
  - 软链 `/app/backend/comfyui → /app/comfyui`（工作流 JSON 路径 `comfyui/workflows/api` 按 cwd `/app/backend` 相对解析）。
  - `WORKDIR /app/backend`（与本地 `cd backend && uvicorn` 一致：`config.py` 的 `CONFIG_PATH = parents[2]/config.yaml` → `/app/config.yaml`；`infra.data_dir = ../data` → `/app/data`）。
- **启动**：`CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8190}"]`（端口由 CMD 读环境变量，与 systemd 单元同款做法）。
- **预估体积**：~2.5–3 GB（chromium + ffmpeg + python 依赖；SAU 变体另加 ~1 GB）。

## docker-compose.yml 设计

```yaml
services:
  app:
    build:
      context: .
      args:
        WITH_PUBLISH: ${WITH_PUBLISH:-0}
    image: nvw-app
    container_name: nvw-app
    restart: unless-stopped
    ports:
      - "${APP_PORT:-8190}:${APP_PORT:-8190}"
    environment:
      - APP_PORT=${APP_PORT:-8190}
      # 覆盖 config.yaml 的 comfyui.server_url（容器内不能用 127.0.0.1 连宿主 ComfyUI）
      - NV_COMFYUI_URL=${COMFYUI_URL:-http://host.docker.internal:8188}
      # 计划任务时区（tzlocal 跟随）
      - TZ=${TZ:-Asia/Shanghai}
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./model_providers.yaml:/app/model_providers.yaml
      - ./news_sources.yaml:/app/news_sources.yaml
      - ./publish_targets.yaml:/app/publish_targets.yaml
      - ./schedule.yaml:/app/schedule.yaml
      - ./prompts.yaml:/app/prompts.yaml
      - ./covers.yaml:/app/covers.yaml
      - ./data:/app/data
      - ./publish_cookies:/app/publish_cookies
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request,os,sys; p=os.getenv('APP_PORT','8190'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health').status==200 else 1)\""]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
```

## .env.example

```
APP_PORT=8190        # 容器对外端口 = 浏览器入口 = API 入口（单端口）
COMFYUI_URL=http://host.docker.internal:8188   # 宿主机 ComfyUI 地址
TZ=Asia/Shanghai     # 计划任务时区
WITH_PUBLISH=0       # 1 = 装抖音/快手发布依赖（SAU + patchright chromium + Chrome 软链）
```

## docker/setup.sh（首启准备）

- 幂等：每个 YAML 目标文件不存在才从对应 `.example` 模板 `cp` 创建；已存在则跳过（带提示）。
- 覆盖 7 个文件：`config.yaml` / `model_providers.yaml` / `news_sources.yaml` / `publish_targets.yaml` / `schedule.yaml` / `prompts.yaml` / `covers.yaml`。
- `data/` 与 `publish_cookies/` 目录不存在则 `mkdir -p`。
- 用途：避开「bind mount 自动建空目录」陷阱；从 systemd 迁移的旧部署若已有这些文件，直接跳过即可。
- 用法：`bash docker/setup.sh`（在仓库根执行）。

## 首启流程

1. `cp .env.example .env`，按需改端口 / ComfyUI 地址 / 时区。
2. `bash docker/setup.sh` 创建 7 个 YAML。
3. `docker compose up -d --build`。
4. 浏览器打开 `http://localhost:8190`（或 `.env` 的 `APP_PORT`），默认登录 `admin / admin`。
5. 首次保存任意设置页会回写对应 YAML（已挂载，持久化）——**前提是先完成坑 B 的 `_io.save_yaml` 原地写修复**，否则任何一次保存都会 EBUSY 崩溃。

## 各功能路线支持矩阵

| 路线 | 状态 | 说明 |
|---|---|---|
| hyperframes（当前默认） | ✅ 完整 | node22 + chromium + Noto CJK 全在镜像内 |
| 纯音频 | ✅ 完整 | FFmpeg concat |
| comfyui | ✅ 完整（WoL 除外） | `NV_COMFYUI_URL` 走 `host.docker.internal`；FFmpeg 兜底在镜像内可用；**WoL 唤醒从容器内广播不可靠 → docker 下建议 `wake.enabled: false`** |
| RSS / 搜索 API 采集 | ✅ 完整 | 纯 httpx |
| 网页抓取（Scrapling） | ⚠️ 基本可用 | `Fetcher`（curl_cffi TLS 伪装）无需浏览器；需要浏览器内核的源要 `scrapling install`（镜像可选层） |
| B站 / YouTube 发布 | ✅ 完整 | 纯 API / cookie |
| 抖音 / 快手发布 | ⚠️ 需 `WITH_PUBLISH=1` | pip SAU + patchright chromium + Chrome 软链；扫码二维码从 API 回传，手机扫码无碍；cookie 靠 `publish_cookies/` 挂载持久 |
| 计划任务 | ✅ 完整 | 注入 `TZ` 后按本地时区触发 |

## 运维要点（写进 docker/README.md）

- **更新**：`git pull` → `docker compose build && up -d`（配置 / 数据都是挂载，不受影响）；依赖有变时重建缓存层。
- **备份**：`data/` + 7 个 YAML + `publish_cookies/`。
- **日志**：容器 stdout + `data/logs/pipeline.log`（任务日志写盘，随挂载持久）。
- **重启语义**（与 systemd 一致）：排队中任务丢失；正在跑的任务被优雅停止并由僵尸回收判失败。
- **反代**：SSE 进度推送需 `proxy_buffering off`（复用 systemd 文档的 Nginx 片段）。
- **端口统一**：`.env` 的 `APP_PORT` 是唯一端口；建议把 CLAUDE.md 的 8190 与部署文档的 8190 一次对齐（docker 默认 8190，systemd 单元可改）。
- **ComfyUI WoL**：docker 下广播包不出网桥，WoL 不可靠 → 关 wake 或整容器 `--network host`。
- **ComfyUI「测试连接」不走 `NV_COMFYUI_URL`**：`api/settings.py:67-71` 的测试端点用前端输入框的值（留空则用 `config.yaml` 的 `comfyui.server_url`），**不套用 `NV_COMFYUI_URL` 环境变量**。后果：docker 下 `config.yaml` 默认 `http://127.0.0.1:8188`，点「测试连接」会探测容器自己的 127.0.0.1 报"离线"，而真实流水线走 `NV_COMFYUI_URL=host.docker.internal:8188` 是通的——两个入口结论互相矛盾。**docker/README 必须写明：测试连接框里要手填 `http://host.docker.internal:8188`**。
- **SQLite WAL 在 Windows 宿主 FUSE 挂载上的可靠性**：`database.py:14` 强制 `PRAGMA journal_mode=WAL`。Linux 宿主 bind mount 无碍；**Windows 宿主**（Docker Desktop 的 gRPC-FUSE）上 `-shm` 共享内存文件与 POSIX 锁在 fuse 上不可靠，并发下有 "database is locked" 乃至库损坏风险。**生产建议 Linux 宿主；Windows 宿主仅作开发机使用**。

## 验收测试清单

0. **EBUSY 实证（本机无 docker server 时在真实宿主先跑）**：`docker run --rm -v "$PWD:/h" python:3.12-slim bash -c 'touch /h/a.txt /h/b.txt && python -c "import os; os.replace(\"/h/b.txt\",\"/h/a.txt")"'` 预期抛 `OSError(16, 'Device or resource busy')`——证实 rename 到 bind mount 文件必 EBUSY，即坑 B 成立。
1. **干净首启**：全新克隆 + `docker/setup.sh` + `up -d --build` → `/api/health` 200、前端可登录（admin/admin）。
2. **零密钥端到端冒烟**：RSS 源（HN）+ edge-tts + hyperframes 路线跑一条完整 run → 出 mp4（不依赖任何 API key）。
3. **迁移回归**：把现有部署的 `data/` + 7 个 YAML 拷进新宿主挂载 → Dashboard 能看到历史 run、脚本、封面、发布账号。
4. **计划任务**：`TZ=Asia/Shanghai` 下一次一次性 schedule，确认按本地时间触发。
5. **（可选）抖音**：`WITH_PUBLISH=1` 构建 → 创建抖音账号 → 扫码登录成功 → cookie 落 `publish_cookies/`。
6. **ComfyUI 跨机**：宿主跑 ComfyUI，容器经 `host.docker.internal` 连接测试按钮通过。
7. **7 个 YAML 逐一保存回归（直击坑 B EBUSY）**：在设置页分别保存 providers / sources / targets / schedules / prompts / cover / 流水线配置各一次，确认全部落盘成功、容器不崩、内容正确。
8. **「测试连接」用 host.docker.internal 验证**：ComfyUI 测试连接框手填 `http://host.docker.internal:8188`，确认按钮探测的是该地址（而非 `NV_COMFYUI_URL` 或 127.0.0.1）。

## 文档与收尾

- `docker/README.md`：完整手册（前置、首启、迁移、运维、排错）。
- `README.md` / `README.zh-CN.md`：Setup 节加 Docker 入口，与 systemd 并列两条路。
- `deploy/docker-archive/README.md`：更新指向新方案（归档文件保留作对照）。
- `CLAUDE.md`：补 Docker 特有说明（TZ / WoL / 端口 / bind mount 目录陷阱）。
- 端口对齐：统一 8190（CLAUDE.md 口径），systemd 单元的 8190 可改。

## 独立发现（不属于 docker 本身，但文档要改）

CLAUDE.md 写「ComfyUI 视频路失败不兜底 FFmpeg」，但 `runner.py` Stage5 实际是**失败即回退 FFmpeg 兜底合成**（不兜底的只有 Stage3 图片路：`ensure_comfyui_ready` 不可达即抛错）。docker 文档按**代码实际行为**写；建议后续把 CLAUDE.md 这句话修正，或把代码改成硬失败——二选一，由维护者定。

## 实施顺序

0. **代码修复（blocking 前置）**：把 `_io.save_yaml`（`backend/app/store/_io.py:54-76`）的 `mkstemp + os.replace` 原子写改为原地 `open("w")` 截断写（对齐 `config.py:436-439`），消除坑 B 的 EBUSY。单进程单写者场景，原子性损失可接受。加单测覆盖保存不抛错。
1. 写 6 个新文件：`Dockerfile` / `docker-compose.yml` / `.dockerignore` / `.env.example` / `docker/setup.sh` / `docker/README.md`。
2. 干净首启 + 冒烟 e2e（验收测试 0、1、2）。
3. 迁移回归 + 7-YAML 保存回归 + 测试连接验证（验收测试 3、4、7、8）。
4. 可选：`WITH_PUBLISH` 变体验证 + ComfyUI 跨机（验收测试 5、6）。
5. 文档对齐 + 归档说明更新。
