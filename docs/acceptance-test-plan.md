# 新闻视频自动化工作流 — 全流程全功能测试与验收计划

> 目标：对「采集 → 文案 → 素材 → 校验 → 合成 → 发布」全链路及所有功能点做系统性测试与验收。
> 本计划同时作为**验收清单（checklist）**使用，每条都给出「方法 / 前置条件 / 步骤 / 通过标准 / 优先级」。

---

## 0. 测试策略与分层

| 层级 | 名称 | 范围 | 是否需外部依赖 | 执行方式 |
|------|------|------|----------------|----------|
| L0 | 自动化回归 | 现有 `pytest`（201 用例）+ 前端 `vitest` | 否（全 mock） | `pytest` / `pnpm test` |
| L1 | API 契约 | FastAPI 各路由的入参/出参/状态码/错误码 | 否（TestClient + mock provider） | 自动 + 手动补充 |
| L2 | 端到端业务 | 真实跑通各路线成片，需真实 Key/服务 | 是（AI Key / ComfyUI / FFmpeg / 平台凭证） | 手动验收 |
| L3 | 非功能 | 断点续跑、孤儿回收、错误中文化、日志、归档、并发 | 部分 | 手动 + 故障注入 |

**可执行性分级**（决定哪些能立刻验、哪些需准备环境）：

- 🟢 **无依赖即可验**：模型层、schema、去重、合规、评分、时间轴、prompts、API 契约（mock）
- 🟡 **需本地工具**：FFmpeg（音频合并/合成兜底）、Hyperframes（Node+Puppeteer）、ComfyUI（图片/视频，需 GPU）
- 🔴 **需外部账号/Key**：文本/图片 AI provider、各搜索类采集器 Key、YouTube/B站 发布凭证

**验收准入门槛（Gate）**：L0 全绿 + L1 全通过 → 才进入 L2 端到端验收。

---

## 1. 环境与前置准备

| 项 | 要求 | 验证命令 |
|----|------|----------|
| Python 环境 | `conda env_news_videos_wf` Python 3.12，`pip install -r requirements.txt` | `python -V` |
| 后端可启动 | uvicorn 正常起，`GET /api/health`（或根路由）200 | 由用户自行启动（见备注） |
| 前端可启动 | `pnpm install && pnpm dev` | 浏览器打开 `:5173` |
| FFmpeg | 在 PATH 中可用 | `ffmpeg -version` |
| Redis | 仅 Celery 路线需要（当前主链路走 BackgroundTasks，可不依赖） | `docker compose up -d redis` |
| ComfyUI | 仅 comfyui 图片/视频路线需要，`http://127.0.0.1:8188` | 浏览器访问 |
| 配置 | `backend/config.yaml` 填好对应 provider 的 Key | 设置页或直接编辑 |

> ⚠️ 备注：按项目约定，**测试执行者不代为启动/重启后端**，后端由用户自行管理。本计划中所有「需后端运行」的步骤，默认后端已由用户起好。

---

## 2. L0 自动化回归（🟢 立即可验）

| 编号 | 测试项 | 命令 | 通过标准 | 优先级 |
|------|--------|------|----------|--------|
| L0-1 | 后端全量单测 | `cd backend && pytest` | 201/201 通过，0 失败 0 错误 | P0 |
| L0-2 | 指定模块抽查 | `pytest tests/test_engine.py tests/test_runner_*.py` | 全绿 | P0 |
| L0-3 | Lint | `ruff check .` | 无 error | P1 |
| L0-4 | 格式 | `ruff format --check .` | 无 diff | P2 |
| L0-5 | 前端单测 | `cd frontend && pnpm test` | 全绿 | P1 |
| L0-6 | 前端构建 | `pnpm build` | 构建成功，无类型错误 | P1 |
| L0-7 | 前端 lint | `pnpm lint` | 无 error | P2 |

**验收标准**：L0-1、L0-2、L0-5、L0-6 必须全部通过，方可进入后续。

---

## 3. L1 API 契约测试（🟢 mock 即可验）

针对 4 个路由模块逐一验证。可用 FastAPI `TestClient` + 注入假 provider。

### 3.1 Pipeline 路由（`/api/pipeline`）

| 编号 | 端点 | 用例 | 通过标准 | 优先级 |
|------|------|------|----------|--------|
| API-P1 | `POST /runs` | 合法 body 创建任务 | 201，返回 run，状态 pending/processing | P0 |
| API-P2 | `GET /runs` | 列表分页 limit/offset | 200，按 created_at 倒序 | P1 |
| API-P3 | `GET /runs/{id}` | 存在/不存在 | 200 / 404 | P0 |
| API-P4 | `GET /runs/{id}` | 孤儿回收：上个进程遗留 processing | 自动转 failed，error_message 含「后端重启」 | P1 |
| API-P5 | `POST /runs/{id}/resume` | review 态任务恢复 | 200 `{status:resumed}` | P0 |
| API-P6 | `DELETE /runs/{id}` | 删除非运行中任务 | 200，DB 记录 + run 目录均删除 | P0 |
| API-P7 | `DELETE /runs/{id}` | 删除 processing 任务 | 409 拒绝 | P0 |
| API-P8 | `GET/PUT /runs/{id}/articles` | 读写文章列表 | PUT 空标题且空正文 → 400 | P0 |
| API-P9 | `POST /articles/import/url` | 合法/非法 URL | 成功追加 / 400 / 502 | P1 |
| API-P10 | `POST /articles/import/file` | PDF/图片/>20MB | 解析成功 / 400(超限) / 502 | P1 |
| API-P11 | `GET /runs/{id}/script` `/timeline` | 不存在 | 404 | P1 |
| API-P12 | `POST /runs/{id}/regen-script` | 无 articles | 400 | P1 |
| API-P13 | `POST /scenes/{sid}/audio` | regen 音频 | 200，script narration 已更新，音频文件落盘 | P1 |
| API-P14 | `POST /scenes/{sid}/image` | regen 图片 | 200，image_prompt 已更新，图片落盘 | P1 |
| API-P15 | `POST /scenes/{sid}/regen-prompt` | AI 重写提示词 | 200，返回新 image_prompt | P2 |
| API-P16 | `POST /scenes` (add) | 指定 group_id 增镜 | 新分镜 id 自增，插到该组末尾 | P1 |
| API-P17 | `DELETE /scenes/{sid}` | 删组内唯一分镜 | 连带删 group 及对应 article，source_index 前移 | P1 |
| API-P18 | `POST /reroll-articles` | daily/weekly/普通 三态 | daily→400；weekly→resummarizing；普通→rerolling | P1 |
| API-P19 | `POST /runs/{id}/render` | 无 timeline / 无 script(audio) | 400 提示先跑对应 stage | P1 |
| API-P20 | `GET /preview` `/preview-html` | 渲染审核页 / Hyperframes 预览 | 200 HTML；无 timeline→404 | P2 |
| API-P21 | `GET /runs/{id}/logs` | tail 日志 | 200，返回 lines 数组 | P2 |
| API-P22 | `GET /runs/{id}/video` | 成品下载 | 200 FileResponse；mp3/mp4 mime 正确；无成品→404 | P1 |
| API-P23 | `GET /assets/{file}` | 素材服务 | png/mp3 mime 正确；越权路径不可读 | P1 |

### 3.2 Sources 路由（`/api/sources`）

| 编号 | 用例 | 通过标准 | 优先级 |
|------|------|----------|--------|
| API-S1 | `GET /` 按 priority 排序 | 200 | P1 |
| API-S2 | `POST /` 创建源 | 201 | P0 |
| API-S3 | `PATCH /{id}` 部分更新（exclude_unset） | 仅改传入字段 | P0 |
| API-S4 | `PATCH` 不存在 | 404 | P1 |
| API-S5 | `POST /batch` 批量 enabled/pinned/priority_map | 批量生效 | P1 |

### 3.3 Publishers 路由（`/api/publishers`）

| 编号 | 用例 | 通过标准 | 优先级 |
|------|------|----------|--------|
| API-PUB1 | CRUD 增删改查 | 201/200/200/200 | P0 |
| API-PUB2 | `PATCH` 改 config_json/enabled | 生效 | P1 |
| API-PUB3 | `DELETE` 不存在 | 404 | P2 |

### 3.4 Settings 路由（`/api/settings`）

| 编号 | 用例 | 通过标准 | 优先级 |
|------|------|----------|--------|
| API-SET1 | `GET /` 脱敏读取 | Key 显示为 `xxxx...xxxx` | P0（安全） |
| API-SET2 | `GET /raw` 原始读取 | 完整值（供前端编辑） | P1 |
| API-SET3 | `PUT /` 保存，未改密钥（含 `...`）跳过 | 不覆盖真实 Key | P0（安全） |
| API-SET4 | `PUT /` infra 组被忽略 | 不可改 DB/Redis 地址 | P1 |
| API-SET5 | `GET /prompts/defaults` | 返回各 prompt 的 label/desc/default | P1 |

**验收标准**：P0 项 100% 通过；P1 ≥ 95%；任何安全相关（脱敏/不覆盖密钥/越权读取）项**零容忍**。

---

## 4. L2 端到端业务验收（按功能域）

### 4.1 Stage 1 — 采集（9 类采集器）

| 编号 | 采集器 | 依赖 | 验收点 | 优先级 |
|------|--------|------|--------|--------|
| C-1 | Hacker News（默认兜底） | 🔴 网络 | 无 DB 源时自动用 HN，能拉到 story | P0 |
| C-2 | RSS（36氪/TechCrunch/MarkTechPost…） | 🔴 网络 | 解析条目，时间范围过滤生效（1d/3d/7d/15d/1m） | P0 |
| C-3 | Google News | 🔴 网络 | 拉取并解析 | P1 |
| C-4 | Tavily | 🔴 Key | 有 Key 正常；无 Key 友好报错 | P1 |
| C-5 | Brave Search | 🔴 Key | 同上 | P1 |
| C-6 | Serper | 🔴 Key | 同上 | P1 |
| C-7 | DuckDuckGo | 🔴 网络 | 无 Key 搜索可用 | P2 |
| C-8 | Scraping（Scrapling） | 🟡 浏览器 | `scrapling install` 后抓动态页 | P2 |
| C-9 | AIHot（aihot.virxact.com） | 🔴 网络 | items/daily/weekly 三模式见 4.2 | P0 |
| C-10 | 时间范围过滤 | 🟢 | 只保留范围内文章 | P0 |
| C-11 | max_articles 截断 | 🟢 | 取 top N（默认 5） | P0 |
| C-12 | DB 源优先 | 🟢 | 有启用源用 DB 源，否则用默认 | P0 |
| C-13 | 源类型解析 | 🟢 | config_json.provider > URL hint > type 字段 | P1 |
| C-14 | 跳过无采集器的源 | 🟢 | 记 warning 并跳过，不崩 | P1 |

### 4.2 AIHot 日报/周报 digest（专项）

| 编号 | 场景 | 通过标准 | 优先级 |
|------|------|----------|--------|
| AH-1 | items 动态模式 | 拉取动态条目 | P0 |
| AH-2 | daily 日报 | 生成当日汇总文章；当日无数据→明确提示「今日 AI 日报尚未生成」 | P0 |
| AH-3 | weekly 周报 | weekly_items 跨天提炼为 daily_sections 写回 metadata | P0 |
| AH-4 | weekly 数据不足 | 提示「上周 AI 日报数据不足…」，不静默清空 | P1 |
| AH-5 | AIHot 与普通源互斥 | 两者同时 enabled 时只保留 AIHot 组（记 warning） | P0 |
| AH-6 | daily reroll 拒绝 | `POST /reroll-articles` 对 daily 返回 400 | P1 |
| AH-7 | weekly reroll | 触发「重新总结」而非重新采集 | P1 |

> 参考用例：`test_collector_aihot.py`、`test_runner_weekly.py`、`test_runner_mutual_exclusion.py`、`test_runner_articles.py`

### 4.3 内容处理 — 去重 / 合规 / 评分 / 摘要

| 编号 | 功能 | 依赖 | 通过标准 | 优先级 |
|------|------|------|----------|--------|
| PR-1 | 去重（标题相似度 + 正文指纹） | 🟢 | 重复文章被剔除；`test_dedup.py` 绿 | P0 |
| PR-2 | 历史期对比去重 | 🟢 | 与 history 概括对比，回溯窗口生效 | P1 |
| PR-3 | 合规审查 | 🟢/🔴 | 敏感内容标记/排除；`test_compliance.py` 绿 | P1 |
| PR-4 | 评分排序 | 🟢 | 来源权重×时效×相关度，排序正确；`test_scoring.py` 绿 | P1 |
| PR-5 | 摘要生成 | 🔴 AI | 非 aihot 源逐篇生成摘要，长度 ≤ max_length | P1 |
| PR-6 | 全文抽取 | 🟢 | `test_full_text.py` 绿 | P2 |

### 4.4 文章管理（手动导入 / 编辑 / 增删）

| 编号 | 功能 | 依赖 | 通过标准 | 优先级 |
|------|------|------|----------|--------|
| AM-1 | 关闭 auto_collect 手动模式 | 🟢 | S1 进入 review，等待人工导入；空列表不放行 | P0 |
| AM-2 | URL 导入 | 🔴 网络 | 抓取正文追加到 articles.json | P1 |
| AM-3 | 文件导入 - PDF | 🟢 | 解析文本；`test_document_import.py` 绿 | P1 |
| AM-4 | 文件导入 - 图片（vision OCR） | 🔴 vision | 调 vision 模型识别 | P2 |
| AM-5 | 文件超 20MB | 🟢 | 400 拒绝 | P1 |
| AM-6 | 编辑文章 | 🟢 | PUT 保存，空标题且空正文→400 | P0 |
| AM-7 | 删除分镜联动删文章 | 🟢 | 见 API-P17，source_index 前移正确 | P1 |

### 4.5 Stage 2 — 文案分镜（多文章分组）

| 编号 | 功能 | 依赖 | 通过标准 | 优先级 |
|------|------|------|----------|--------|
| S2-1 | 多文章分组脚本 | 🔴 AI | 生成 title/description/tags/groups/scenes；`test_stage2_multi.py` 绿 | P0 |
| S2-2 | 每分镜字段完整 | 🟢 | narration/image_prompt/motion_prompt/duration_hint 齐全 | P0 |
| S2-3 | scene 与 group 关联 | 🟢 | 每 scene 带 group_id/group_title/source_index | P0 |
| S2-4 | 语言可配置 | 🟢 | default_language=zh/en 生效 | P1 |
| S2-5 | regen-script 重生成 | 🔴 AI | 重跑 stage2 覆盖 script.json | P1 |
| S2-6 | weekly distill | 🔴 AI | weekly→distill_weekly_sections | P1 |

### 4.6 Stage 3 — 素材生成（图片 / TTS / 纯音频）

| 编号 | 功能 | 依赖 | 通过标准 | 优先级 |
|------|------|------|----------|--------|
| S3-1 | OpenAI 图片 | 🔴 Key | 每分镜出图，尺寸符合 resolution；`test_image_openai.py` 绿 | P0 |
| S3-2 | ComfyUI 图片 | 🟡 GPU | z_image/qwen workflow，steps/cfg 可调；`test_comfyui_image.py` 绿 | P1 |
| S3-3 | EdgeTTS 配音 | 🔴 网络 | 每分镜出音频 + 实际时长；`test_tts_edge.py` 绿 | P0 |
| S3-4 | 音色/语速可配 | 🟢 | voice/speed 生效 | P1 |
| S3-5 | 纯音频路线（audio） | 🟢 | 只生成音频，跳过图片；`test_stage3_audio_only.py` 绿 | P1 |
| S3-6 | 进度回写 | 🟢 | progress_detail 实时更新「S3 生成图片 x/N」 | P1 |
| S3-7 | 单分镜失败容错 | 🟢 | 标 error 跳过，最终 partial 不整体崩 | P1 |
| S3-8 | 图片质量重生成 | 🔴 | regen image 换提示词重出 | P2 |

### 4.7 Stage 4 — 校验与时间轴

| 编号 | 功能 | 依赖 | 通过标准 | 优先级 |
|------|------|------|----------|--------|
| S4-1 | 时间轴生成 | 🟢 | entries 含 start/end_ms，total_duration_ms 正确；`test_stage4.py` 绿 | P0 |
| S4-2 | 音画对齐 | 🟢 | 图片展示时长 = 旁白音频时长（+scene_gap） | P0 |
| S4-3 | 分镜审核页 | 🟢 | preview.html 生成，图/音/文案可见 | P1 |
| S4-4 | Hyperframes 预览 | 🟡 | hyperframes 路线生成 index.html | P1 |
| S4-5 | audio 路线跳过 S4 | 🟢 | video_route=audio 不进 S4 | P1 |

### 4.8 Stage 5 — 合成（三套 + 兜底）

| 编号 | 路线 | 依赖 | 通过标准 | 优先级 |
|------|------|------|----------|--------|
| S5-1 | Hyperframes HTML→MP4 | 🟡 Node+FFmpeg | 出 output.mp4，分辨率正确；`test_stage5.py` 绿 | P0 |
| S5-2 | Hyperframes 失败兜底 FFmpeg | 🟡 | 异常时自动 `_ffmpeg_compose` | P0 |
| S5-3 | ComfyUI 视频生成 | 🟡 GPU | wan5b/wan14b/ltx workflow；`test_comfyui_video.py`/`test_comfyui_composer.py` 绿 | P1 |
| S5-4 | ComfyUI 失败兜底 FFmpeg | 🟡 | 异常时自动 FFmpeg 拼接 | P0 |
| S5-5 | 纯音频合并 | 🟡 FFmpeg | 按分镜顺序合并 MP3；`test_audio_merge.py` 绿 | P1 |
| S5-6 | 手动触发 render | 🟢 | `POST /render` 重新合成，刷新 started_at | P1 |
| S5-7 | 成品归档导出 | 🟢 | 配 output_dir 时复制为 `run_{id}_{标题}.ext`；`test_output_media_meta.py` 绿 | P2 |
| S5-8 | 成品不存在处理 | 🟢 | 失败置 failed + 明确错误 | P1 |

### 4.9 Stage 6 — 发布

| 编号 | 平台 | 实现状态 | 依赖 | 通过标准 | 优先级 |
|------|------|----------|------|----------|--------|
| S6-1 | YouTube | ✅ 真实 | 🔴 凭证 | Data API v3 上传成功返回链接；`test_publisher_youtube.py` 绿 | P0 |
| S6-2 | Bilibili | ✅ 真实 | 🔴 Cookie | biliup 投稿成功（现代 UA 绕 412）；`test_publisher_bilibili.py` 绿 | P0 |
| S6-3 | Douyin | ⚠️ 有实现未接线 | 🔴 | `_build_one` 未注册→Stage6 报 "No publisher"（已知） | P2 |
| S6-4 | Kuaishou/Instagram | ⚠️ 有实现未接线 | 🔴 | 同上 | P2 |
| S6-5 | 音频平台（小宇宙/喜马/网易云/Apple） | ❌ 占位 | — | 返回「暂未实现」失败结果，不崩；`test_audio_publishers.py` 绿 | P2 |
| S6-6 | 多平台并发发布 | 🟢 | 单平台失败不阻塞其他 | P1 |
| S6-7 | 发布结果落盘 | 🟢 | publish_results.json 记录成功/失败 | P1 |
| S6-8 | 仅发布启用 target | 🟢 | 只发 enabled 且在 platforms 内的 target | P1 |

> 已知差距（建议在验收报告中标注）：`build_publishers._build_one` 仅注册了 bilibili / youtube，douyin/kuaishou/instagram 虽有 adapter 但未接线。

### 4.10 Pipeline 引擎与运行模式

| 编号 | 功能 | 依赖 | 通过标准 | 优先级 |
|------|------|------|----------|--------|
| PE-1 | 全自动模式 | 🔴 | auto 一路跑完 1→6 不停顿 | P0 |
| PE-2 | 半自动模式审核断点 | 🟢 | 每 stage 后转 review，等 resume；`test_engine.py` 绿 | P0 |
| PE-3 | 阶段选择 selected_stages | 🟢 | 仅跑选中 stage（如只 1-4） | P0 |
| PE-4 | 断点续跑 | 🟢 | resume 后从 review 处继续，已完成素材不重生 | P0 |
| PE-5 | 孤儿任务回收 | 🟢 | 进程重启后旧 processing 任务判 failed | P1 |
| PE-6 | review 超时 | 🟢 | 1 小时未 resume → TimeoutError | P2 |
| PE-7 | 无文章中止 | 🟢 | 0 篇时 failed + `_no_article_message` | P1 |
| PE-8 | 错误中文化 | 🟢 | 超时/401/429/403/404 等转中文「源头+原因」 | P1 |
| PE-9 | 任务级分辨率/比例 | 🟢 | run.resolution 覆盖全局 video 配置 | P1 |
| PE-10 | 单条 vs 合集 | 🔴 | 单条→单视频；多条→合集（转场） | P1 |

### 4.11 场景级编辑（半自动核心交互）

| 编号 | 功能 | 通过标准 | 优先级 |
|------|------|----------|--------|
| SE-1 | regen 音频 | 改 narration 重生成音频，预览即时刷新 | P1 |
| SE-2 | regen 图片 | 改 image_prompt 重出图 | P1 |
| SE-3 | AI 重写提示词 | 据 narration 生成新 image_prompt | P2 |
| SE-4 | 增加分镜 | 按 group 补镜，AI 生成内容 | P1 |
| SE-5 | 删除分镜 | 删镜；删组内最后一镜连带删组+文章 | P1 |
| SE-6 | reroll 文章 | 重新采集/重新总结（按模式分流） | P1 |

### 4.12 配置管理与提示词

| 编号 | 功能 | 通过标准 | 优先级 |
|------|------|----------|--------|
| CFG-1 | 设置分标签页 | text/image/vision/tts/collectors/youtube/comfyui/prompts 各组可存读 | P1 |
| CFG-2 | 密钥脱敏显示 | 见 API-SET1/3，前端不泄露完整 Key | P0 |
| CFG-3 | 可编辑提示词 | 7 类 prompt（roundup/daily_batch/summary_meta/weekly_digest/image_regen/article_summary/news_scoring）可改可复位默认；`test_api_settings_prompts.py`/`test_prompts.py` 绿 | P1 |
| CFG-4 | 提示词跨进程生效 | reload_settings 后 worker 拿到新值 | P1 |
| CFG-5 | ComfyUI 参数可调 | image/video workflow + steps/cfg + fps；锁死项（lightx2v 4步）不可改 | P1 |
| CFG-6 | 存储目录 | work_dir / output_dir 配置生效 | P2 |

### 4.13 前端 4 页面

| 编号 | 页面 | 验收点 | 优先级 |
|------|------|--------|--------|
| FE-1 | 工作台 Dashboard | 任务列表/卡片、新建任务对话框、阶段指示、进度、日志、成片预览、resume/render/delete 操作 | P0 |
| FE-2 | 信息源 Sources | 列表、增/改/删、批量启用/置顶/排序、AIHot 模式切换 | P0 |
| FE-3 | 发布管理 Publishers | target 增删改、凭证录入、平台启用 | P1 |
| FE-4 | 设置 Settings | 各标签页编辑保存、密钥脱敏、提示词编辑/复位 | P1 |
| FE-5 | Toast/错误提示 | 失败有中文提示，不白屏 | P1 |
| FE-6 | 审核交互 | review 态可编辑分镜并 resume | P0 |

---

## 5. L3 非功能与健壮性

| 编号 | 项 | 方法 | 通过标准 | 优先级 |
|------|----|------|----------|--------|
| NF-1 | 可恢复性 | 跑到 S3 杀进程，重启后 resume | 已完成素材不重生，从断点续 | P0 |
| NF-2 | 幂等性 | 同一 stage 重跑 | 不产生重复/脏数据 | P1 |
| NF-3 | 错误可观测 | 注入 401/超时 | pipeline.log 有完整堆栈，前端有中文摘要 | P1 |
| NF-4 | 日志分任务 | 每 run 独立 pipeline.log | tail 接口可读 | P2 |
| NF-5 | 安全：Key 不落库 | 检查 DB | Key 仅在 config.yaml，DB 不存明文 | P0 |
| NF-6 | 文件清理 | 删除任务 | run 目录被 rmtree | P1 |
| NF-7 | 大文件/长任务 | 多分镜（20+）长视频 | 不 OOM、不超时崩 | P2 |
| NF-8 | 并发任务 | 同时起 2-3 个 run | 互不串数据/目录 | P1 |
| NF-9 | 外部服务不可用降级 | 关掉 ComfyUI | 自动兜底 FFmpeg，不致命 | P0 |

---

## 6. 端到端验收主场景（冒烟 + 全链路）

按优先级排成「可演示」的验收剧本：

| 剧本 | 路线 | 步骤 | 通过标准 | 优先级 |
|------|------|------|----------|--------|
| E2E-A 冒烟 | hyperframes / 半自动 | 新建任务(1-5) → S1 采集(HN) → S2 脚本 → S3 素材 → S4 预览审核 → S5 出片 | 得到可播放 output.mp4 | P0 |
| E2E-B 纯音频 | audio | 1-3+5 → 合并 MP3 | 得到 output.mp3 | P1 |
| E2E-C 手动导入 | hyperframes | 关 auto_collect → URL/PDF 导入 → 编辑分镜 → 出片 | 全程人工可干预 | P1 |
| E2E-D AIHot 日报 | hyperframes | daily 源 → 生成日报合集视频 | 合集带转场 | P1 |
| E2E-E ComfyUI 视频 | comfyui | 图片→视频→合成 | 出动态视频；失败兜底 FFmpeg | P2 |
| E2E-F 发布 | — | 出片 → 发 YouTube/B站 | 返回真实链接，记录落盘 | P1 |
| E2E-G 全自动 | hyperframes | auto 1→6 一键到底 | 无人工干预完成并发布 | P1 |

---

## 7. 验收结论判定标准

| 等级 | 标准 |
|------|------|
| ✅ 通过 | L0 全绿；L1 的 P0 100% + 安全项零缺陷；L2 的 P0 全部通过；E2E-A 冒烟成功 |
| ⚠️ 有条件通过 | P0 通过但存在 P1/P2 已知问题（如 douyin 未接线、音频平台占位），列入「已知差距」清单 |
| ❌ 不通过 | 任一 P0 失败，或安全项（密钥泄露/越权）缺陷，或冒烟 E2E-A 失败 |

**缺陷分级**：P0=阻断（必修）｜P1=主要（验收前修）｜P2=次要（可挂账）。

---

## 8. 测试数据与缺陷记录模板

**缺陷记录**：`[编号] 标题 | 复现步骤 | 期望 | 实际 | 严重级(P0/1/2) | 截图/日志 | 状态`

**已知差距清单（验收时同步给业务方）**：
1. Stage6 实际仅接线 YouTube / Bilibili，douyin/kuaishou/instagram 有 adapter 但 `_build_one` 未注册。
2. 音频发布平台（小宇宙/喜马拉雅/网易云/Apple Podcasts）为占位，返回「暂未实现」。
3. RPD 中的 LTX 路线已由 ComfyUI 路线取代（video_route: hyperframes | comfyui | audio）。

---

## 9. 执行顺序建议

```
L0 自动化(🟢) ──▶ L1 API契约(🟢) ──▶ 4.x 各域单点(🟢优先) ──▶ E2E-A 冒烟 ──▶ L2 全域(🟡🔴) ──▶ L3 非功能 ──▶ E2E-F/G 发布与全自动 ──▶ 出验收报告
```

1. **第 1 天**：L0 + L1 + 全部 🟢 用例（无需外部依赖，可立刻 100% 跑完）。
2. **第 2 天**：备好 FFmpeg/Hyperframes/ComfyUI → 4.6~4.8 + E2E-A/B/E。
3. **第 3 天**：备好各 AI Key 与平台凭证 → 4.1/4.5/4.9 + E2E-C/D/F/G + L3。
4. 汇总缺陷 → 修 P0/P1 → 回归 → 出验收结论。

---

## 10. 执行记录

### 第一轮：L0 + L1（零依赖层）— 2026-06-03

| 层 | 项 | 结果 | 备注 |
|----|----|------|------|
| L0-1 | 后端 pytest | ✅ 211 passed | 初次 200/1，修复 1 个陈旧测试后全绿 |
| L0-3 | ruff check | ⚠️ P2 债 | app/ 282 + tests/ 87，**纯风格**（262 E501 长行、未用 import、import 排序、2 处故意的 ORM `==True`）；无 F811/F821/F841 等逻辑隐患 |
| L0-4 | ruff format | ⚠️ P2 债 | 79 文件未格式化，非功能问题 |
| L0-5 | 前端单测 | N/A | 项目无前端单测（仅 dev/build/lint/preview） |
| L0-6 | 前端 build | ✅ 通过 | tsc 类型检查 + vite build 均成功 |
| L0-7 | 前端 lint | ⚠️ P2 债 | 8 error，全是 React 最佳实践（7 `set-state-in-effect` + 1 `react-refresh`），无功能缺陷 |
| L1 | API 契约（新增 `test_l1_contract.py` 10 条） | ✅ 10/10 | 含密钥脱敏、回传脱敏值不覆盖密钥、infra 忽略、删运行中→409、删任务清目录、video 404、publishers CRUD、源批量 |

**本轮发现的缺陷：**

| ID | 严重级 | 标题 | 状态 |
|----|--------|------|------|
| BUG-1 | P2（测试债） | `test_collector_rss` 用硬编码 pubDate(`26 May 2026`)，被 7d 时间过滤判 0 条 → 陈旧失败 | ✅ 已修：改为相对 `now` 的动态日期 |
| **BUG-2** | **P0（安全）** | **`GET /runs/{id}/assets/{path}` 路径穿越/任意文件读取（LFI）**：`..%2fsecret.txt` 返回 200+内容，可逃出 `assets/` 读取宿主任意可读文件（含含密钥的 `config.yaml`） | ✅ 已修：解析后用 `is_relative_to(assets_root)` 锁定目录 + 回归测试 |

**改动文件（待 review/commit）：**
- `backend/tests/test_collector_rss.py`（BUG-1 修复）
- `backend/app/api/pipeline.py` → `get_asset`（BUG-2 安全修复）
- `backend/tests/test_l1_contract.py`（新增 L1 契约测试）

**门槛判定**：L0 功能项全绿 + L1 P0/安全项全过 + BUG-2 已修复 → **准予进入 L2 端到端验收**。ruff/format/前端 lint 三项 P2 债不阻断，建议另开清理任务。

### 第二轮：L2 离线可跑组件 — 2026-06-03

**环境探测**：ffmpeg 8.1 ✅ ｜ node v22 + npx ✅ ｜ ComfyUI ❌（127.0.0.1:8188 未运行）

新增 `tests/test_ffmpeg_integration.py`（真跑 ffmpeg，skipif 守卫无 ffmpeg 环境）：

| ID | 项 | 结果 | 校验 |
|----|----|------|------|
| S5-5 | 纯音频合并 `_ffmpeg_merge_audio` | ✅ 真跑 | 真实 mp3，ffprobe 时长 ≈ 4.5s |
| S5-2/4 | FFmpeg 合成兜底 `_ffmpeg_compose` | ✅ 真跑 | 真实 mp4，分辨率 320×240、时长 ≈ 2.5s；**验证 `shell=True+list` 在 Windows 可用** |
| S5-2/4 | 无有效场景抛错 | ✅ | 不产空文件 |
| S5-7 | 归档导出 `export_final` | ✅ | 复制 + 文件名非法字符清洗 |

> 关键价值：此前 `test_audio_merge`/`test_stage5` **全程 mock subprocess/composer**，从未真实产出过成片。本轮首次用真实 ffmpeg 端到端验证了「成片合成」核心能力在本机可用。

全量回归：**215 passed**。

### 第三轮：L2 网络类免 Key 真跑 — 2026-06-03

直接调内部 provider 真实拉取/合成（不经后端服务、不需 API Key）：

| ID | 项 | 结果 | 证据 |
|----|----|------|------|
| C-1 | Hacker News 采集 | ✅ 真跑 | 拉到 3 篇真实 story |
| C-2 | RSS 采集（TechCrunch） | ✅ 真跑 | 解析到 3 篇真实文章 |
| C-3 | Google News 采集 | ✅ 真跑 | 采集成功（探测脚本控制台 gbk 编码报错，非采集器问题） |
| C-7 | DuckDuckGo 采集 | ⚠️ 依赖缺失 | 返回 0 + 提示 `duckduckgo-search not installed`，**优雅降级未崩** |
| S3-3 | EdgeTTS 配音 | ✅ 真跑 | 真实 mp3 15840 字节、时长 2750ms |

**本轮发现：**

| ID | 严重级 | 标题 | 状态 |
|----|--------|------|------|
| BUG-3 | P2（依赖/文档） | DuckDuckGo 采集器需 `duckduckgo-search`，但 `requirements.txt` 未列入；启用该源会静默返回 0 篇 | 待办：补依赖或在文档标注「DDG 为可选源，需额外装包」 |
| BUG-4 | P1（环境依赖） | Hyperframes 包（`hyperframes@0.6.69`）未安装（全局/前端/后端均无），MVP 主渲染路线 S5-1 当前无法真跑；首次渲染会触发 npx 联网拉取，否则直接走 FFmpeg 兜底 | 待办：预装 `hyperframes` 或文档明确「首次需联网安装」；兜底链已验可用 |

### 待执行：仍被阻塞的 L2 / L3

| 项 | 依赖 | 状态 |
|----|------|------|
| Tavily / Brave / Serper 采集 | 搜索 API Key | 阻塞 |
| AI 文本/图片（Claude/OpenAI） | API Key | 阻塞 |
| ComfyUI 图片/视频路线 | 启动 ComfyUI 服务（127.0.0.1:8188 当前未起） | 阻塞 |
| Hyperframes 渲染 | npm `hyperframes` 包 | ⚠️ 包未安装（见 BUG-4）；`_render_html` 已单测覆盖，缺包时走 FFmpeg 兜底 |
| 发布 YouTube / B站 | 平台凭证 | 阻塞 |
| 全链路 E2E（auto/manual/resume） | 后端运行 + 上述 | 阻塞 |

> 结论：**所有「免 Key + 免后端服务 + 免 ComfyUI」可独立验证的链路均已真跑通过**。剩余项均需用户提供 API Key / 启动 ComfyUI / 提供发布凭证 / 启动后端后方可继续。

### 第四轮：真实全链路 E2E（后端运行）— 2026-06-03

环境就绪：后端 :8000(0.0.0.0) ✅ ｜ 前端 :5173(**::1 仅 IPv6，须用 `localhost`**) ✅ ｜ ComfyUI :8188 ✅ ｜ hyperframes 0.6.69 ✅ ｜ text=openai/gpt-5.5、image=openai/gpt-image-2 key 已配 ✅ ｜ 发布目标 youtube+bilibili 凭证在库 ✅

**E2E-A 主路线成片（run #4，hyperframes，手动导入→1-5）：**

| 阶段 | 结果 | 证据 |
|------|------|------|
| S1 手动导入 (AM-1/6) | ✅ | auto_collect=false → review → 导入 1 篇 → resume |
| S2 文案 gpt-5.5 (S2-1/2) | ✅ | 《Claude Opus 4.8…》3 分镜，旁白+图片提示+本土化约束 |
| S3 素材 (S3-1/3) | ✅ | gpt-image-2 出 3 图（每张~100s）+ EdgeTTS 配音 |
| S4 时间轴/预览 (S4-1/3) | ✅ | timeline + storyboard |
| S5 **Hyperframes 渲染 (S5-1)** | ✅ | **output.mp4 32.2MB / 46.5s / 1080×1920 / H.264 30fps / AAC**，总耗时 565s |
| FE-1 前端工作台 | ✅ | devtool 验：任务列表/阶段指示/进度/运行中删除按钮禁用 |

> S5-1（Hyperframes 主渲染路线）**首次真实出片成功**——此前因包未装一直无法验证。

**E2E-F 发布（复用 run #4 成片，真实对外）：**

| 平台 | 结果 |
|------|------|
| YouTube (S6-1) | ✅ **发布成功** `youtube.com/watch?v=DswWxNoIo3I`（按用户选择 public） |
| Bilibili (S6-2) | ⚠️ 代码已修通，上传到 100%，submit 被 B站风控 `21564 投稿过于频繁` 限流，24h 后可重试 |

**本轮发现：**

| ID | 严重级 | 标题 | 状态 |
|----|--------|------|------|
| **BUG-5** | **P1** | **B站发布在异步 pipeline 中必崩**：`BilibiliPublisher.publish` 是 async，但体内同步调 biliup，而 biliup 内部用 `asyncio.run()`——在运行中的事件循环里调用直接抛 `asyncio.run() cannot be called from a running event loop`。整个 pipeline 跑在 asyncio loop 里，故正常 Stage6 的 B站投稿必然失败。单测因 mock biliup 未暴露 | ✅ 已修：抽 `_blocking_publish` 经 `asyncio.to_thread` 在独立线程跑；真跑验证上传管道打通（传到 100%） |

**其它观察：** 现有 API 无「对已完成 run 单独触发发布」端点，Stage6 只能在完整 pipeline 内执行（本轮用内部组件直调绕过）。建议补一个 `POST /runs/{id}/publish` 端点便于重试发布。

全量回归：**215 passed**。

### 第五轮：ComfyUI 路线 — 2026-06-03

ComfyUI 0.22.0 / PyTorch 2.11+cu130 / 12 个 workflow JSON 齐全（z_image·qwen 图片；wan22_5b/14b·ltx23 视频）。直接构造 provider 真跑：

| ID | 项 | 结果 | 证据 |
|----|----|------|------|
| S3-2 | ComfyUI 图片（z_image t2i） | ✅ 真跑 | 9 步 / 38s / 1024×1024 PNG 1.1MB |
| S5-3 | ComfyUI 视频（wan5b i2v） | ✅ 真跑 | 30 步 / 39s / 512×512 H.264 24fps 61帧 2.54s |

> ComfyUI 图片与图生视频两条路线均在本机 GPU 上真实产出，参数（workflow/steps/cfg/fps）经 `build_image_provider`/`build_video_provider` 正确传递。

**前端 4 页面（devtool 验证，localhost:5173）：**

| ID | 页面 | 结果 |
|----|------|------|
| FE-1 | 工作台 | ✅ 任务列表/阶段指示/进度/运行中禁删 |
| FE-2 | 信息源 | ✅ 26 源 + AI HOT 聚合(动态/日报/周报) + 互斥说明(AH-5) |
| FE-3 | 发布管理 | ✅ 5 平台；**敏感凭证脱敏**(SESSDATA/bili_jct/Secret/RefreshToken `••••`)，UID/ClientID 明文(公开标识) |
| FE-4 | 设置 | ✅ 4 标签；**API Key 全脱敏** `•••••`+显示按钮；保存 dirty 态正确 |

> 安全小结：前端发布管理页与设置页均正确脱敏真正的密钥，仅明文展示非敏感的公开标识，符合 CFG-2 要求。

### 第六轮：补齐 t2v（文生视频）provider — 2026-06-03

**背景**：`comfyui-workflows-design` 落盘了全集 t2v+i2v 工作流（t2v 4 个：wan22_5b/14b/14b_lightx2v_t2v、ltx23_t2v），但 `comfyui-video-generation-design` 按 YAGNI「仅 i2v」只接了 i2v 代码——t2v 工作流文件在、无 provider。本轮按需补齐。

**改动**：`ComfyUIVideoProvider` 加 `mode`（i2v/t2v）+ `_T2V_WORKFLOW_MAP`；t2v 跳过 `upload_image`、不填 `INPUT_IMAGE`（t2v 占位符仅 WIDTH/HEIGHT/LENGTH/SEED/POS/NEG）；`build_video_provider(cfg, mode=...)` 透传；`is_ltx` 判断含 `ltx23_t2v`。

**测试**：新增 4 条单测（workflow 映射、4 个 t2v 文件填充无残留占位符、t2v 跳过上传、build mode 透传）。全量 **219 passed**。

| ID | 项 | 结果 |
|----|----|------|
| S5-3t | t2v provider 单测 | ✅ 11/11（含 4 t2v workflow 真实填充） |
| S5-3t | t2v wan5b 真实冒烟 | ✅ 18.5s / 512×512 H.264 61帧 2.54s mp4 |

**本轮发现：**

| ID | 严重级 | 标题 | 状态 |
|----|--------|------|------|
| **BUG-6** | **P1** | **3 个 wan t2v 工作流输出 `SaveAnimatedWEBP`（动图 webp），ffmpeg 8.1 解不了**（`invalid TIFF header / image data not found`），转码失败。i2v 当初按设计 N4 已改 `CreateVideo+SaveVideo`(mp4)，但 t2v 未接代码遗留 webp 输出 | ✅ 已修：3 个 wan t2v(`5b/14b/14b_lightx2v`)的输出节点改为 `CreateVideo+SaveVideo`(mp4/h264)，与 i2v 一致；真跑出有效 mp4 |

> ltx23_t2v 本就用 `CreateVideo+SaveVideo`，不受影响。全量回归 **219 passed**。t2v provider 现可用于后续「各模型 i2v+t2v」批量生成。

### 第七轮：4 模型 ×(i2v+t2v)× 60s 批量生成 — 2026-06-03

统一 qwen 种子图（768×768，43s）+ 6 段统一文稿，每段 10s 拼 60s，输出 `data/batch_video/`。

| 模型 | i2v | t2v |
|------|-----|-----|
| wan5b | ✅ 60.2s 512² h264 | ✅ 60.2s |
| ltx | ✅ 59.8s | ✅ 59.8s |
| wan14b | ⚠️→重跑中 | ⚠️→重跑中 |
| wan14b_lightx2v | ⚠️→重跑中 | ⚠️→重跑中 |

**本轮发现：**

| ID | 严重级 | 标题 | 状态 |
|----|--------|------|------|
| **BUG-7** | **P1** | wan14b 4 组合首轮全部 `timeout 600s`，但查 ComfyUI history 实为 `status=success`——**ComfyUI 生成成功的结果因客户端 600s 超时被丢弃浪费**。根因：`ComfyUIVideoProvider` 用了 `ComfyUIClient` 默认 600s，而 14B 模型（≈14GB 权重/24GB 显存频繁交换）单段 >600s | ✅ 已修：视频 provider 超时 600→1800s（+测试）；wan14b 用新超时重跑中 |

> 成功的 4 个成片（wan5b/ltx 各 i2v+t2v）均为有效 60s 视频，可横向对比模型。全量回归 **220 passed**。
