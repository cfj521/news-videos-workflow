<p align="right"><b>English</b> | <a href="README.zh-CN.md">简体中文</a></p>

# News-to-Video Automation Workflow

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?logo=react&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)

An end-to-end platform that turns news into published videos: scrape news → generate script → generate image/video assets → compose narrated video → publish to multiple platforms.

**Tech stack**: Python (FastAPI) backend · React (Vite + TypeScript) frontend

## Pipeline

```
[Collector] → [Processor] → [Generator] → [Composer] → [Publisher]
   scrape       script       image/video    compose +       multi-platform
   news         generation    assets         narration       publishing
   S1           S2/S3         S3/S5          S4/S5           S6
```

Each stage runs sequentially inside the backend process (FastAPI background tasks), persists its state to the DB, and can be retried from any stage.

## Setup

### Backend (conda + requirements.txt)

Dependencies live in the root `requirements.txt`; `backend/pyproject.toml` only keeps ruff / pytest config.

```bash
conda create -n env_news_videos_wf python=3.12
conda activate env_news_videos_wf
pip install -r requirements.txt        # includes optional publishing deps: biliup / google-*
```

### Frontend

```bash
cd frontend
pnpm install
```

### Infrastructure / external dependencies

- **FFmpeg**: must be available on the system PATH (video composition).
- **ComfyUI** (optional, the default local image/video generation route): run ComfyUI locally (default `http://127.0.0.1:8188`); models via `scripts/download-comfyui-models.ps1`.

## Run

```bash
# Backend API (the pipeline runs as in-process background tasks — no extra worker/broker needed)
cd backend && uvicorn app.main:app --reload --port 8189   # http://127.0.0.1:8189
# Frontend
cd frontend && pnpm dev                              # http://127.0.0.1:5173
```

First launch seeds a default admin account **admin / admin** — change it under **Settings → Users** after logging in.

## Docker

One-shot deployment (backend + frontend with Nginx reverse proxy). The pipeline runs as in-process background tasks — no worker/broker container needed.

```bash
cp config.yaml.example config.yaml   # fill in your API keys
cp .env.example .env                  # Docker ports + ComfyUI URL (optional; sane defaults)
docker compose up -d --build
# open http://localhost:8190  (default login: admin / admin)
```

- Ports and the ComfyUI URL live in `.env` (`FRONTEND_PORT`, `BACKEND_PORT`, `COMFYUI_URL`). `COMFYUI_URL` is injected into the backend and **overrides** `comfyui.server_url` — no need to edit `config.yaml`.
- `config.yaml` and `data/` are bind-mounted — secrets stay out of the image; the SQLite DB and run artifacts persist on the host.
- ComfyUI is expected on the host (needs GPU + models); the backend reaches it via `host.docker.internal`.

## Test

```bash
cd backend && pytest          # backend
cd frontend && pnpm build     # frontend type-check + build
```

## Configuration

- First-time setup: copy the template in the repo root, `cp config.yaml.example config.yaml`, fill in your API keys, and start (`config.yaml` is gitignored). Afterwards, prefer the Settings page (`/settings`) for a visual editor that writes back to the file on save. Loading is handled by `backend/app/config.py` (pydantic + YAML) — **the project uses the root `config.yaml`, not `.env`**.
- **Models** page: a provider library grouped by purpose (Text / Image / Vision / TTS). For each provider configure base_url / API key / output-token limit and an **editable model-name list**; custom providers are supported. Credentials are shared per provider.
- **Pipeline** page: the single place that selects **which provider + model** each purpose uses (summary / script / image / vision / TTS), plus default resolution, language, video route, and the ComfyUI video model + fps.
- **ComfyUI** page: per-workflow steps/cfg parameters for image (z_image / qwen) and video (wan5b / wan14b / lightx2v / ltx) workflows.
- **Prompts** page: editable Chinese / English prompt sets — the task language decides which set is used.
- **Publishing platforms**: credentials are configured per platform on the "Publishers" page (stored in the DB), not in the config file.

## ComfyUI models (local image/video generation)

The default image/video route runs on a **local ComfyUI** (workflows in `comfyui/workflows/api/*.json`). You must download the models yourself and let ComfyUI find them. Reference config: **24 GB VRAM**; full set ≈ **180 GB** disk — you only need the route(s) you actually use. File names below omit the `.safetensors` suffix; the authoritative list (with download sources) is `scripts/download-comfyui-models.ps1`.

| Route | ComfyUI dir(s) | Model files |
|---|---|---|
| **z_image** — image, default/fast | `diffusion_models` · `text_encoders` · `vae` | `z_image_turbo_bf16` · `qwen_3_4b` · `ae` |
| **Qwen-Image** — image, CN/layout | `diffusion_models` · `text_encoders` · `vae` | `qwen_image_fp8_e4m3fn` · `qwen_2.5_vl_7b_fp8_scaled` · `qwen_image_vae` |
| **Wan 2.2 5B** — video, default/fast | `diffusion_models` · `text_encoders` · `vae` | `wan2.2_ti2v_5B_fp16` · `umt5_xxl_fp8_e4m3fn_scaled` · `wan2.2_vae` |
| **Wan 2.2 14B** — video, quality (i2v & t2v) | `diffusion_models` · `vae` | `wan2.2_{i2v,t2v}_{high,low}_noise_14B_fp8_scaled` · `wan_2.1_vae` |
| **Wan 2.2 Lightning** — video, 4-step LoRA | `loras` | `wan2.2_{i2v,t2v}_lightx2v_4steps_lora_*` |
| **LTX 2.3** — video | `checkpoints` · `text_encoders` · `loras` · `latent_upscale_models` | `ltx-2.3-22b-dev-fp8` · `gemma_3_12B_it_fp4_mixed` · `ltx-2.3-22b-distilled-lora-384-1.1` · `ltx-2.3-{spatial,temporal}-upscaler-x2-1.0` |

All models are on **ModelScope** (`Comfy-Org/*`, `Lightricks/LTX-2.3*`). The helper scripts download everything into one folder:

```powershell
pip install modelscope
powershell -ExecutionPolicy Bypass -File scripts/download-comfyui-models.ps1      # image + Wan 2.2
powershell -ExecutionPolicy Bypass -File scripts/download-ltx23-comfyui-models.ps1 # LTX 2.3 (optional)
```

Then point ComfyUI's `extra_model_paths.yaml` `base_path` at that folder (the scripts default to `D:/models/comfyui/`), restart ComfyUI, and pick the matching model under **Settings → Pipeline** (workflow params live under **Settings → ComfyUI**). **No GPU?** Set the video route to `hyperframes` (falls back to FFmpeg) — ComfyUI is optional.

## Publishing

Supports YouTube, Bilibili, and more. For how to obtain and fill in each platform's account / cookie / token, see **[docs/video-publish-guide.md](docs/video-publish-guide.md)**:

- **YouTube**: OAuth (Client ID + Client Secret + Refresh Token); obtain the refresh_token via the OAuth Playground, with the app set to "External + Production".
- **Bilibili**: browser cookies (SESSDATA + bili_jct required; DedeUserID/buvid3/buvid4 recommended), uploaded via biliup.

## Docs

- [docs/video-publish-guide.md](docs/video-publish-guide.md) — publishing platform account setup & configuration (how-to)
- [docs/video-publish-api-reference.md](docs/video-publish-api-reference.md) — publishing adapter API reference
- [CLAUDE.md](CLAUDE.md) — architecture, module layout, conventions (for developers)
- `comfyui/` — ComfyUI workflow JSON and usage notes
