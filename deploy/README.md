# 部署（Ubuntu + systemd）

裸机 / VM 上用 systemd 跑本项目。一个进程同时托管 **FastAPI 后端 + 进程内流水线 + 前端静态产物**（单端口）。流水线跑在进程内的全局串行 worker，无需独立 worker/broker。

> Docker 一体化方案已归档（暂不维护），见 [`docker-archive/`](docker-archive/README.md)；本目录是当前推荐的非容器（systemd）方案。

## 0. 运行用户与目录

服务以非 root 的**服务账号** `app_nvw`（主组 `sharing`，对应单元里的 `User`/`Group`）运行：

```bash
getent group sharing || sudo groupadd sharing
# 系统账号、不可交互登录、独立 home（首跑时 scrapling/缓存需可写）
sudo useradd --system --create-home --home-dir /home/app_nvw \
     --gid sharing --shell /usr/sbin/nologin app_nvw

# 仓库 + 数据目录归属（/data/news-videos-workflow 为部署路径）
sudo chown -R app_nvw:sharing /data/news-videos-workflow
sudo find /data/news-videos-workflow -type d -exec chmod 2775 {} \;   # setgid：新文件继承 sharing 组
```

- **conda 环境可达**：若 conda 装在别的用户 home 下（如 `/home/colex/miniconda3`），`app_nvw` 默认进不去 → 启动失败。放行 `sudo chmod o+x /home/colex /home/colex/miniconda3`，或更干净地把 miniconda 装到公共路径（如 `/opt/miniconda3`，归 `root:sharing` 组可读执行）。
- 以该用户跑安装命令（`nologin` 不影响 `sudo -u`）：`sudo -u app_nvw bash -lc '...'`。
- `/data` 若是独立挂载，确认 `app_nvw` 能穿透访问；单元已加 `RequiresMountsFor=/data`，挂载就绪后才启动。

## 1. 前置依赖

```bash
# 系统依赖：ffmpeg（视频合成 + 读音频时长 ffprobe）、中文字体（字幕）
sudo apt update && sudo apt install -y ffmpeg fonts-noto-cjk

# 可选——Hyperframes 视频路线需要 Node>=22 + hyperframes：
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
sudo apt install -y nodejs && sudo npm i -g hyperframes

# ComfyUI（默认视频/图片路线）需另行在本机或别处运行，见仓库根 CLAUDE.md
```

Python 环境（conda，Python 3.12）：

```bash
conda create -n env_nvw python=3.12 -y
conda run -n env_nvw pip install -r /data/news-videos-workflow/requirements.txt
```

前端构建（产物 `frontend/dist` 由后端托管）：

```bash
cd /data/news-videos-workflow/frontend && pnpm install && pnpm build
```

配置文件（均在仓库根、均已 gitignore，从同名 `.example` 模板创建）：

```bash
cd /data/news-videos-workflow
cp config.yaml.example          config.yaml            # 必需：基础配置（端口/路线/分辨率/语言…）
cp model_providers.yaml.example model_providers.yaml   # provider 的 base_url/api_key（也可后续在「设置→模型配置」页填，保存时自动生成）
# 以下按需，不建也行——后端会自动生成 / 由对应页面写入：
#   prompts.yaml          首次启动自动生成（模板 prompts.yaml.example）
#   news_sources.yaml     「新闻源」页管理
#   publish_targets.yaml  「发布管理」页按账号写入（模板 publish_targets.yaml.example）
#   schedule.yaml         「计划任务」页写入（模板 schedule.yaml.example）
```

> 若 `cp` 用了 `sudo`/其它用户，记得把新建的 yaml 再 `chown app_nvw:sharing`（或直接 `sudo -u app_nvw cp ...`），保证运行用户可读写。

## 2. 安装服务

编辑 `deploy/news-videos-workflow.service`，按本机改 4 处（已用「改这里①~④」标注）：
- **①** `User`/`Group`：运行用户（非 root，需对仓库目录 + `data/` 可读写）
- **②** `WorkingDirectory`：仓库根下的 `backend`
- **③** `Environment=PATH`：conda 环境 bin 路径（含 `uvicorn`/`python`）
- **④** `ExecStart`：conda 环境里 `uvicorn` 的绝对路径

> conda 环境 bin 路径查法：`conda run -n env_nvw which uvicorn`

```bash
sudo cp deploy/news-videos-workflow.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now news-videos-workflow
```

浏览器打开 `http://<host>:8190`（端口见单元里 `APP_PORT`），默认登录 `admin / admin`（请尽快改密）。

## 3. 运维

```bash
systemctl status news-videos-workflow        # 状态
journalctl -u news-videos-workflow -f        # 实时日志
sudo systemctl restart news-videos-workflow  # 重启（排队中的任务会丢，正在跑的会优雅停止）
sudo systemctl stop news-videos-workflow     # 停止
```

更新代码后：

```bash
git pull
conda run -n env_nvw pip install -r requirements.txt   # 依赖有变时
cd frontend && pnpm install && pnpm build                          # 前端有变时
sudo systemctl restart news-videos-workflow
```

## 4. 反向代理（可选）

如需 HTTPS / 域名，前面挂 Nginx 反代到 `127.0.0.1:8190`（并把单元里 `--host` 改为 `127.0.0.1` 只监听本地）。SSE（任务进度）需关闭代理缓冲：

```nginx
location / {
    proxy_pass http://127.0.0.1:8190;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;      # SSE 进度推送需要
    proxy_read_timeout 1h;    # 长任务
}
```

## 说明
- 任务**全局串行**执行：同一时刻最多一个任务在跑，其余排队（显示 `pending`）。
- 进程内队列：重启会丢失「排队中」的任务（正在跑的会被优雅停止并由僵尸回收判失败）。
- 数据（SQLite + 运行产物）在仓库根 `data/`，备份该目录即可。
