# Docker 部署（已归档，暂不维护）

当前推荐用 **systemd**（见 `deploy/README.md`）部署。Docker 一体化方案暂停使用，相关文件归档于此：

| 文件 | 原位置 |
|---|---|
| `docker-compose.yml` | 仓库根 |
| `Dockerfile` | `backend/Dockerfile` |
| `.dockerignore` | 仓库根 |
| `.env.example` | 仓库根 |

## 恢复使用 Docker

把文件移回原位（路径很重要：compose 的构建上下文为仓库根、`dockerfile: backend/Dockerfile`，Dockerfile 内 `COPY` 也相对仓库根）：

```bash
cd <仓库根>
git mv deploy/docker-archive/docker-compose.yml ./docker-compose.yml
git mv deploy/docker-archive/Dockerfile ./backend/Dockerfile
git mv deploy/docker-archive/.dockerignore ./.dockerignore
git mv deploy/docker-archive/.env.example ./.env.example
```

然后照旧：

```bash
cp config.yaml.example config.yaml   # 填密钥
cp .env.example .env                 # APP_PORT / COMFYUI_URL（可选）
docker compose up -d --build
# 浏览器打开 http://localhost:8190 （默认 admin / admin）
```

> 归档期间这些文件不随代码改动更新；恢复后请核对 `requirements.txt`、`backend/` 结构是否与 Dockerfile 的 `COPY` 一致。
