# 部署（Ubuntu + systemd）

裸机 / VM 上用 systemd 跑本项目。一个进程同时托管 **FastAPI 后端 + 进程内流水线 + 前端静态产物**（单端口）。流水线跑在进程内的全局串行 worker，无需独立 worker/broker。

> Docker 一体化方案已归档（暂不维护），见 [`docker-archive/`](docker-archive/README.md)；本目录是当前推荐的非容器（systemd）方案。

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
conda create -n env_news_videos_wf python=3.12 -y
conda run -n env_news_videos_wf pip install -r /opt/news-videos-workflow/requirements.txt
```

前端构建（产物 `frontend/dist` 由后端托管）：

```bash
cd /opt/news-videos-workflow/frontend && pnpm install && pnpm build
```

配置：

```bash
cd /opt/news-videos-workflow && cp config.yaml.example config.yaml   # 填入各 provider 密钥
```

## 2. 安装服务

编辑 `deploy/news-videos-workflow.service`，按本机改 4 处（已用「改这里①~④」标注）：
- **①** `User`/`Group`：运行用户（非 root，需对仓库目录 + `data/` 可读写）
- **②** `WorkingDirectory`：仓库根下的 `backend`
- **③** `Environment=PATH`：conda 环境 bin 路径（含 `uvicorn`/`python`）
- **④** `ExecStart`：conda 环境里 `uvicorn` 的绝对路径

> conda 环境 bin 路径查法：`conda run -n env_news_videos_wf which uvicorn`

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
conda run -n env_news_videos_wf pip install -r requirements.txt   # 依赖有变时
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
