<p align="right"><b>English</b> | <a href="README.zh-CN.md">简体中文</a></p>

# News-to-Video Automation Workflow

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?logo=react&logoColor=black)
![Deploy](https://img.shields.io/badge/deploy-systemd-FCC624?logo=linux&logoColor=black)

An end-to-end platform that turns news into published videos — **scrape → score & select → script → generate image/video assets → compose with narration → publish to multiple platforms** — fully automated, or paused at any step for human review. Managed from a web admin panel.

**Tech stack**: Python (FastAPI) backend · React (Vite + TypeScript) frontend.

## Features

**Collection & selection**
- Multiple collectors: **RSS**, **web scraping** (Scrapling, for sites without a feed), **search APIs** (Tavily / Brave / Serper / DuckDuckGo), and **AI-HOT** direct sources.
- Category tagging (AI models / products / industry / papers / tips) and a configurable time window.
- Cross-run **dedup** over a lookback window, then an AI **scoring** pass ranks items and keeps the top-N (`max_articles`).
- **Manual import**: add an article by URL or by uploading a file, or skip collection entirely and feed your own content.

**Script & assets**
- AI builds a per-item **storyboard** (spoken narration + English image/motion prompts) — single-item, daily-batch, or weekly-digest framing.
- **Bilingual** (Chinese / English): the task language picks the prompt set, with **5 switchable prompt presets** (rename by double-click).
- Image assets via the chosen Image provider; **TTS narration** via the chosen TTS provider.
- **Per-scene manual intervention**: regenerate the script, an image, or an image prompt; reroll the article list.

**Three output routes**
- **ComfyUI** — local GPU diffusion (image: z_image / Qwen-Image · video: Wan 2.2 / LTX 2.3).
- **Hyperframes** — HTML/CSS motion graphics, no GPU needed (Node + `hyperframes`).
- **Audio-only** — pure narration, no visuals.
- Optional **title burn-in** overlay (CJK font), fully styleable.

**Pluggable AI providers**
- **Text / Image / Vision / TTS** are each swappable via config — OpenAI, DashScope, Edge-TTS, ComfyUI, … — no code changes.
- A per-provider credential library; the **Pipeline** page is the single place that picks which provider + model each purpose uses.

**Local ComfyUI + remote wake**
- Run image/video generation on a **local ComfyUI**, with a one-click connection test.
- Deploy the app on a **GPU-less server** while ComfyUI lives on a separate GPU machine — woken on demand via **Wake-on-LAN**. If ComfyUI is unreachable the run fails clearly (no silent fallback).

**Publishing & orchestration**
- **Multi-platform publishing** via an adapter pattern (YouTube, Bilibili, …), credentials per account.
- **Scheduling**: cron-like routines (daily / weekly / monthly) that auto-create runs at the set time.
- **Auto** or **manual (step-by-step review)** execution; every stage is idempotent and **retryable from any stage**.
- Runs execute **one at a time** through a global in-process serial queue — no extra worker/broker.
- Web admin panel: Dashboard (monitor / review / intervene), Sources, Publishers, Schedules, Settings, plus user management.

## Pipeline

```
[Collector] → [Processor] → [Generator] → [Composer] → [Publisher]
   scrape +     script /      image/video    compose +      multi-platform
   score        storyboard    assets         narration      publishing
   S1           S2/S3         S3/S5          S4/S5           S6
```

Each stage runs sequentially inside the backend process; state is persisted to the DB so a run can resume/retry from any stage. Whole runs are serialized through a single in-process worker (others queue as `pending`); a restart drops queued runs and gracefully stops the running one.

## Run options

When you create a run you choose: **time range** (1d / 3d / 7d / 15d / 1m) · **max articles** · **category** · **language** (zh / en) · **video route** (ComfyUI / Hyperframes / Audio-only) · **collection mode** (auto-collect / manual import) · **execution mode** (auto / manual step-by-step review) · **sources** · **publish targets**. The same options back the scheduler (which always runs in auto mode).

## Setup

### Backend (conda + requirements.txt)

Dependencies live in the root `requirements.txt`; `backend/pyproject.toml` only keeps ruff / pytest config.

```bash
conda create -n env_news_videos_wf python=3.12
conda activate env_news_videos_wf
pip install -r requirements.txt        # includes optional publishing deps: biliup / google-*
```

### Frontend

Requires **Node ≥ 22 + pnpm** (see [System dependencies](#system-dependencies) below — Ubuntu's apt Node 18 is too old for Vite 8).

```bash
cd frontend && pnpm install && pnpm build   # backend serves the built frontend/dist
```

### System dependencies

- **FFmpeg** — required for video composition (also the fallback compositor for the Hyperframes route). Ubuntu: `sudo apt install -y ffmpeg fonts-noto-cjk`.
- **CJK font** — for title burn-in on the FFmpeg / ComfyUI routes. Ubuntu: `fonts-noto-cjk` (above); Windows uses the built-in `C:/Windows/Fonts/msyh.ttc`. Missing → burn-in is skipped, output unaffected.
- **Node ≥ 22 + pnpm** — required to build the frontend (Vite 8 needs Node ≥ 20.19 / 22.12; Ubuntu's apt Node 18 is too old). Ubuntu (use NodeSource): `curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs`, then enable pnpm: `corepack enable && corepack prepare pnpm@latest --activate` (or `sudo npm i -g pnpm`).
- **Hyperframes** — only for the `hyperframes` video route: `sudo npm i -g hyperframes` (or let `npx` fetch it on first render). Falls back to FFmpeg if missing. Not a pip dependency.
- **ComfyUI** — optional, only for the default local image/video route; see [ComfyUI models](#comfyui-models-local-imagevideo-generation).

### Config files

All config lives in repo-root YAML files (gitignored), created from their `.example` templates:

```bash
cp config.yaml.example          config.yaml            # required: base settings (port / route / resolution / language…)
cp model_providers.yaml.example model_providers.yaml   # provider base_url / api_key (or fill via the Models page)
```

Only `config.yaml` is required up front. The rest auto-create on first use or are written by their matching Settings page: `prompts.yaml` (prompt presets), `news_sources.yaml` (sources), `publish_targets.yaml` (publish accounts), `schedule.yaml` (scheduled runs). `cp` a template only if you want to pre-seed it.

> On first launch the backend seeds a default admin **admin / admin** — change it under **Settings → Users**.

## Configuration

Everything is editable from the Settings page (`/settings`), which writes back to the YAML files on save. Loading is handled by `backend/app/config.py` (pydantic + YAML) — **the project uses the root `config.yaml`, not `.env`**.

- **Models** — a provider library grouped by purpose (Text / Image / Vision / TTS): base_url / API key / output-token limit + an editable model-name list; custom providers supported, credentials shared per provider.
- **Pipeline** — picks **which provider + model** each purpose uses (summary / script / image / vision / TTS), plus default resolution, language, video route, and ComfyUI video model + fps.
- **ComfyUI** — connection address with a **Test connection** button and optional **Wake-on-LAN** remote wake; per-workflow steps/cfg for image (z_image / qwen) and video (wan5b / wan14b / lightx2v / ltx) workflows.
- **Prompts** — 5 switchable presets (#1–#5, double-click to rename), each with a Chinese / English set; empty fields fall back to built-in defaults.
- **Publishers** — per-account platform credentials.
- **Sources** / **Schedules** — manage news sources and scheduled runs.

## ComfyUI models (local image/video generation)

The default image/video route runs on a **local ComfyUI** (workflows in `comfyui/workflows/api/*.json`). You download the models yourself and let ComfyUI find them. Reference config: **24 GB VRAM**; full set ≈ **160 GB** disk — you only need the route(s) you actually use. File names below omit the `.safetensors` suffix; the authoritative list (with download sources) is `scripts/download-comfyui-models.ps1` / `.sh`.

| Route | ComfyUI dir(s) | Model files |
|---|---|---|
| **z_image** — image, default/fast | `diffusion_models` · `text_encoders` · `vae` | `z_image_turbo_bf16` · `qwen_3_4b` · `ae` |
| **Qwen-Image** — image, CN/layout | `diffusion_models` · `text_encoders` · `vae` | `qwen_image_fp8_e4m3fn` · `qwen_2.5_vl_7b_fp8_scaled` · `qwen_image_vae` |
| **Wan 2.2 5B** — video, default/fast | `diffusion_models` · `text_encoders` · `vae` | `wan2.2_ti2v_5B_fp16` · `umt5_xxl_fp8_e4m3fn_scaled` · `wan2.2_vae` |
| **Wan 2.2 14B** — video, quality (i2v & t2v) | `diffusion_models` · `vae` | `wan2.2_{i2v,t2v}_{high,low}_noise_14B_fp8_scaled` · `wan_2.1_vae` |
| **Wan 2.2 Lightning** — video, 4-step LoRA | `loras` | `wan2.2_{i2v,t2v}_lightx2v_4steps_lora_*` |
| **LTX 2.3** — video | `checkpoints` · `text_encoders` · `loras` | `ltx-2.3-22b-dev-fp8` · `gemma_3_12B_it_fp4_mixed` · `ltx-2.3-22b-distilled-lora-384-1.1` |

All models are on **ModelScope** (`Comfy-Org/*`, `Lightricks/LTX-2.3*`). One script (PowerShell + bash variants) downloads everything (image + Wan 2.2 + LTX 2.3, aligned with the api workflows) into one folder:

```bash
pip install modelscope
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts/download-comfyui-models.ps1
# Linux / WSL (bash)
bash scripts/download-comfyui-models.sh
```

> Override the target dir with `-ModelsDir <path>` (PowerShell) / `--models-dir <path>` (bash); defaults: `D:\models\comfyui` / `~/models/comfyui`.

Then point ComfyUI's `extra_model_paths.yaml` `base_path` at that folder, restart ComfyUI, and pick the matching model under **Settings → Pipeline**. **No GPU on the app host?** Either set the video route to `hyperframes` (no GPU) / `audio` (narration only), or run ComfyUI on a separate GPU machine and let the app wake it via **Wake-on-LAN** (Settings → ComfyUI).

## Publishing

Supports YouTube, Bilibili, and more. For how to obtain and fill in each platform's account / cookie / token, see **[docs/video-publish-guide.md](docs/video-publish-guide.md)**:

- **YouTube**: OAuth (Client ID + Client Secret + Refresh Token); obtain the refresh_token via the OAuth Playground, app set to "External + Production".
- **Bilibili**: browser cookies (SESSDATA + bili_jct required; DedeUserID/buvid3/buvid4 recommended), uploaded via biliup.

## Deployment

Recommended: **systemd on Ubuntu** — see **[deploy/README.md](deploy/README.md)** for the full walk-through (service account, mounts, config files, the unit file). One process serves the frontend (static) and the backend (API + in-process pipeline) on a single port — no worker/broker.

> The previous single-container **Docker** setup is archived (not maintained) under [`deploy/docker-archive/`](deploy/docker-archive/README.md).

## Docs

- [docs/video-publish-guide.md](docs/video-publish-guide.md) — publishing platform account setup & configuration (how-to)
- [docs/video-publish-api-reference.md](docs/video-publish-api-reference.md) — publishing adapter API reference
- [CLAUDE.md](CLAUDE.md) — architecture, module layout, conventions (for developers)
- `comfyui/` — ComfyUI workflow JSON and usage notes
