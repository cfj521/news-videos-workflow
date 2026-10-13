# Docker 部署（单容器一体化）

一个容器同时托管 **FastAPI 后端 + 进程内流水线 + 前端静态产物**（单端口）。流水线跑在进程内的全局串行 worker，无需独立 worker/broker。本方案与 systemd 部署（`deploy/README.md`）完全同构，**不改业务逻辑**——唯一的代码改动是 `_io.save_yaml` 的写盘方式对齐（原子写 → 原地写，消除 bind mount 的 EBUSY，见下「两个必须知道的坑」）。

> 旧的 Docker 文件归档在 [`deploy/docker-archive/`](../deploy/docker-archive/README.md)（已过时，不要直接使用）。本目录是当前推荐容器方案。

## 文件布局

| 文件 | 作用 |
|---|---|
| [`Dockerfile`](../Dockerfile) | 多阶段：node:22 构建前端 → python:3.12 运行时（ffmpeg / chromium / hyperframes） |
| [`docker-compose.yml`](../docker-compose.yml) | 单服务 + 7 YAML + data/ + publish_cookies/ 挂载 + healthcheck |
| [`.env.example`](../.env.example) | APP_PORT / COMFYUI_URL / TZ / WITH_PUBLISH |
| [`docker/setup.sh`](setup.sh) | 首启：从 `.example` 模板创建 7 个 YAML（防 bind mount 目录陷阱） |

## 两个必须知道的坑

1. **bind mount 目录陷阱**：bind mount 的宿主路径不存在时，Docker 自动建**空目录**顶替文件。`config.py` 只对 `config.yaml` 有目录兜底报错，6 个 store（`_io.load_yaml`）没有，会 `open(目录)` 崩溃。所以**必须先跑 `docker/setup.sh` 创建 7 个真实 YAML**，再 `docker compose up`。
2. **原子写 vs 文件 bind mount → EBUSY**：`_io.save_yaml` 原为「同目录临时文件 + `os.replace`」原子写，而 `os.replace` 到单文件 bind mount 的挂载点返回 `EBUSY`（OSError 16），任何一次设置保存都会崩溃。已改为原地 `open("w")` 截断写（对齐 `config._save_yaml`）。单进程单写者场景，原子性损失可接受。**改动前的旧镜像/代码不要用于 Docker 部署**。

## 前置

- Docker（带 BuildKit，compose v2）。
- **生产建议 Linux 宿主**：Windows 宿主（Docker Desktop 的 gRPC-FUSE）上，SQLite WAL 的 `-shm` 共享内存文件与 POSIX 锁在 fuse 上不可靠，并发下有 "database is locked" 乃至库损坏风险。**Windows 宿主仅作开发机使用**。
- ComfyUI（可选，默认图片/视频路线）留在宿主机或另一台 GPU 机，容器经 `host.docker.internal` 访问。

## 首启（全新部署）

```bash
bash docker/setup.sh            # 创建 7 个 YAML（从 .example 模板）
cp .env.example .env            # 按需改端口 / ComfyUI 地址 / 时区
docker compose up -d --build    # 构建 + 启动
```

浏览器打开 `http://localhost:8189`（或 `.env` 的 `APP_PORT`），默认登录 `admin / admin`（请尽快改密，设置 → 用户管理）。

首次保存任意设置页会回写对应 YAML（已挂载，持久化）。

## 从 systemd 迁移

已有一套 systemd 裸机部署（`data/` + 7 个 YAML + `publish_cookies/` 已积累数据）时：

1. 把这 3 样原样拷进 Docker 宿主的仓库根（`data/`、7 个 YAML、`publish_cookies/`）。
2. `bash docker/setup.sh`——已存在的文件会自动跳过，不覆盖。
3. `cp .env.example .env`，按需改。
4. `docker compose up -d --build`。

Dashboard 应能看到历史 run、脚本、封面、发布账号。

## 各路线支持

| 路线 | 状态 | 说明 |
|---|---|---|
| hyperframes（当前默认） | ✅ 完整 | node22 + chromium + Noto CJK 全在镜像内 |
| 纯音频 | ✅ 完整 | FFmpeg concat |
| comfyui | ✅ 完整（WoL 除外） | `NV_COMFYUI_URL` 走 `host.docker.internal`；FFmpeg 兜底在镜像内可用；**WoL 唤醒从容器内广播不可靠 → docker 下建议 `wake.enabled: false`** |
| RSS / 搜索 API 采集 | ✅ 完整 | 纯 httpx |
| 网页抓取（Scrapling） | ⚠️ 基本可用 | `Fetcher`（curl_cffi TLS 伪装）无需浏览器；需要浏览器内核的源要 `scrapling install` |
| B站 / YouTube 发布 | ✅ 完整 | 纯 API / cookie |
| 抖音 / 快手发布 | ⚠️ 需 `WITH_PUBLISH=1` | pip SAU + patchright chromium + Chrome 软链；扫码二维码从 API 回传，手机扫码无碍；cookie 靠 `publish_cookies/` 挂载持久 |
| 计划任务 | ✅ 完整 | 注入 `TZ` 后按本地时区触发 |

## 运维

```bash
docker compose logs -f                       # 实时日志
docker compose restart                       # 重启（排队中任务会丢，正在跑的优雅停止）
docker compose down                          # 停止并删容器（数据/配置在挂载，不丢）
```

**更新代码**：
```bash
git pull
docker compose build && docker compose up -d   # 配置/数据都是挂载，不受影响
```

**备份**：`data/` + 7 个 YAML + `publish_cookies/`。

## 常见坑

- **ComfyUI「测试连接」不走 `NV_COMFYUI_URL`**：设置页的测试连接按钮用前端输入框的值（留空则用 `config.yaml` 的 `comfyui.server_url`），**不套用 `NV_COMFYUI_URL` 环境变量**。docker 下 `config.yaml` 默认 `http://127.0.0.1:8188`，点「测试连接」会探测容器自己的 127.0.0.1 报"离线"，而真实流水线走 `NV_COMFYUI_URL=host.docker.internal:8188` 是通的——两个入口结论会互相矛盾。**测试连接框里要手填 `http://host.docker.internal:8188`**。
- **ComfyUI WoL**：docker 下广播包不出网桥，WoL 不可靠 → 关 wake 或整容器 `--network host`。
- **反代**：SSE 进度推送需 `proxy_buffering off`（见 `deploy/README.md` 的 Nginx 片段）。
- **端口统一**：`.env` 的 `APP_PORT` 是唯一端口（前后端同一端口）。
- **行尾**：7 个 YAML 由容器以 LF 写入；宿主 Windows 用户若用自动转 CRLF 的编辑器改 YAML，建议用保留 LF 的编辑器。

## 验收（实施期用）

0. **EBUSY 实证**：`docker run --rm -v "$PWD:/h" python:3.12-slim bash -c 'touch /h/a.txt /h/b.txt && python -c "import os; os.replace(\"/h/b.txt\",\"/h/a.txt")"'` 预期抛 `OSError(16, 'Device or resource busy')`——证实 rename 到 bind mount 文件必 EBUSY。
1. **干净首启**：`setup.sh` + `up -d --build` → `/api/health` 200、可登录。
2. **零密钥端到端冒烟**：RSS（HN）+ edge-tts + hyperframes 路线跑一条完整 run → 出 mp4。
3. **迁移回归**：`data/` + 7 YAML 拷入 → Dashboard 看到历史。
4. **计划任务**：`TZ=Asia/Shanghai` 一次性 schedule 按本地时间触发。
5. **（可选）抖音**：`WITH_PUBLISH=1` → 扫码登录 → cookie 落 `publish_cookies/`。
6. **ComfyUI 跨机**：容器经 `host.docker.internal` 连接测试通过。
7. **7 个 YAML 逐一保存回归**（直击坑 2 EBUSY）。
8. **「测试连接」用 host.docker.internal 验证**。
