# Docker 部署（已归档，勿直接使用）

> **Docker 已于 2026-10 恢复为当前推荐的容器方案**：新的构建文件放在**仓库根**——`Dockerfile` / `docker-compose.yml` / `.dockerignore` / `.env.example` / `docker/setup.sh` / `docker/README.md`。**不要使用本目录的归档文件**（见下「为何过时」），用法见 [`docker/README.md`](../docker/README.md)。
>
> 非容器的推荐方案仍是 **systemd**（见 `deploy/README.md`）。

## 为何归档方案过时（勿恢复）

下面这些文件是早期版本，已与当前代码不一致：

| 文件 | 原位置 | 过时原因 |
|---|---|---|
| `docker-compose.yml` | 仓库根 | 只挂 `config.yaml` + `data/`，漏掉后来新增的 6 个 YAML store 与 `publish_cookies/` |
| `Dockerfile` | `backend/Dockerfile` | 前端用 `npm ci`（仓库无 `package-lock.json`，实际是 `pnpm-lock.yaml`）必挂；`node:20-alpine` 构建不了 Vite 8 |
| `.dockerignore` | 仓库根 | 漏排除 6 个含凭证 yaml 与 `publish_cookies/` |
| `.env.example` | 仓库根 | 缺 `TZ` / `WITH_PUBLISH` |

这些文件仅保留作对照，**不要移回原位**——直接恢复会构建失败。
