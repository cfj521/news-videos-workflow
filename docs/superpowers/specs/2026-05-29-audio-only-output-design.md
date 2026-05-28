# 纯语音成品模式 — 设计文档

## 背景与目标

当前流水线只产出视频成品（Hyperframes/LTX → MP4）。本期新增**纯语音成品模式**：选择后不生成图片、不合成视频，最终产物是一个合并的 MP3（全部分镜旁白按序拼接）。同时把发布平台按媒体类型（视频/音频）分类，新增几个语音平台，使纯语音成品也能发布到合适的平台。

本功能叠加在当前分支 `feat/aihot-default-exclusion`（PR #3）之上，与之同属一个 PR。

## 非目标 (YAGNI)

- 不为新增语音平台做完整可用的发布对接：仅做目录 + 媒体分类 + 配置字段 + 占位/尽力适配器（与现有视频适配器一致：缺依赖/凭证时优雅报错，不阻断）。
- 不改视频模式的既有行为（除阶段全局改名 `成片渲染→合成渲染`）。
- 纯语音模式不生成图片、不建视频时间轴、不合成视频。
- 不输出独立文稿/字幕文件（产物就是单个 MP3）。

## 模式表示

- **复用 `PipelineRun.video_route`**，新增取值 `"audio"`（无需新增 DB 列）。`video_route == "audio"` 即纯语音模式。
- 前端 `PipelineRun.video_route` 类型：`"hyperframes" | "ltx" | "audio"`。
- 创建对话框的路线选择器：**标签 "视频路线" → "音视频路线"**，选项 `Hyperframes / LTX / 纯语音`。

## 阶段结构与命名

| 后端 stage | 视频模式 | 纯语音模式 |
|---|---|---|
| S1 | 搜索整理 | 搜索整理（不变）|
| S2 + S3 | **脚本/图片生成** | **脚本/语音生成**（S3 跳过图片，仅逐条 TTS）|
| S4 | 预览 | 隐藏 / 跳过 |
| S5 | **成片渲染 → 合成渲染** | **合成渲染**：合并逐条音频 → MP3 + 试听 + 下载 |
| S6 | 发布 | 发布（仅显示音频可用平台）|

命名规则：
- `成片渲染 → 合成渲染`：**全局改名**（两种模式都用，名字更通用）。
- `脚本/图片生成 → 脚本/语音生成`：**仅纯语音模式**（标签随 `video_route` 变）。

可视阶段 → 后端阶段映射（`BACKEND_STAGE_MAP`）不变：可视 2→[2,3]、4→[4]、5→[5]、6→[6]。纯语音模式下创建对话框**不展示"预览"(可视 4)**，故 selected_stages 不含 4。

## 后端流水线改动

### `stage3_collect`/`run_stage3`（素材生成）
- 新增参数 `audio_only: bool = False`。为真时**跳过图片生成**，只产逐条 TTS 音频；返回的 `scene_assets` 每条含 `audio_path`，不含 `image_path`（或置空）。

### `runner.py`（`_run_inner`）
- S3 块：`audio_only = (run.video_route == "audio")`，调用 `run_stage3(..., audio_only=audio_only)`；图片相关进度文案在音频模式下省略。
- S4 块：`video_route == "audio"` 时整块跳过（即便 4 在 selected 也不执行；正常情况下音频模式 selected 不含 4）。
- S5 块：
  - `video_route == "audio"`：调用新 helper `_ffmpeg_merge_audio(scene_assets, script, run_dir) -> mp3_path`，按 `script["scenes"]` 顺序取每条 `audio_path`，用 ffmpeg concat 合并为 `run_dir/output.mp3`；`output_path = output.mp3`。**不依赖 timeline**。
  - 其他路线：维持现有视频合成逻辑（仍要求 timeline）。
- 进度/日志在音频模式用"合成音频/合并语音"等文案，避免"渲染视频"。

### 新 helper `_ffmpeg_merge_audio`
- 输入：`scene_assets`（含逐条 audio_path）、`script`（定顺序）、`run_dir`。
- 实现：按分镜 id 顺序收集存在的 audio 文件，写 ffmpeg concat 列表，`ffmpeg -f concat -safe 0 -i list.txt -c:a libmp3lame output.mp3`（或对已是 mp3 的用 `-c copy`，不一致时重编码）。返回输出路径。
- 边界：无任何音频 → 抛错，runner 置 failed。

## 产物与下载

- 产物：单个合并 MP3，`output_path = run_dir/output.mp3`。
- 复用现有产物端点（serve `output_path`，按扩展名返回正确 content-type）。
- 前端：纯语音模式"下载 MP4"→"**下载 MP3**"（按 `video_route` 切换文案与文件名）；"重新渲染"→"**重新合成**"。

## 前端改动

### 创建对话框 `CreateRunDialog.tsx`
- 路线选择器标签改"音视频路线"，加"纯语音"选项。
- `video_route === "audio"` 时：
  - 执行阶段列表**去掉"预览"(S4)**；阶段依赖相应调整（S5 依赖 [1,2]，不依赖 4）。
  - 阶段标签：S2 显示"脚本/语音生成"，S5 显示"合成渲染"。
  - S6 发布平台多选**仅列 audio/both 平台**。

### 任务详情 `Dashboard.tsx`
- 标签栏：`成片渲染→合成渲染`（全局）；纯语音模式**隐藏"预览"标签**，S2 标签显示"脚本/语音生成"。
- S2 面板（纯语音）：每个分镜**隐藏 图片提示词 / 重新生成图片 / 重生成提示词**，仅留 旁白 + 音频播放 + 重新配音。
- "合成渲染"标签（纯语音）：展示合并音频的**试听播放器 + 下载 MP3**（取代视频预览/下载 MP4）。
- 下载/重渲按钮文案随 `video_route` 切换。

### 类型 `types.ts`
- `video_route` 加 `"audio"`。
- `STAGE_LABELS[5]` 改 "合成渲染"。S2(可视2) 标签在音频模式动态显示"脚本/语音生成"（在组件内按模式取，不改静态表，或静态表保留"脚本/图片生成"由组件覆盖）。

## 发布平台媒体分类 + 新增语音平台

### 媒体分类
- 新增**静态映射** `PLATFORM_MEDIA: Record<platform, "video" | "audio" | "both">`，**只放前端 `types.ts`**，用于 UI 过滤与徽标。后端不需要该分类（发布按所选平台执行即可）。无 DB 改动。
- 现有分类：`youtube / instagram / douyin / kuaishou = video`，**`bilibili = both`**（有音频区）。
- Publishers 页：平台卡片加**媒体类型徽标**。
- 纯语音模式发布选择：只列 `audio`/`both` 平台。

### 新增语音平台（目录 + 分类 + 配置字段 + 占位适配器）
四个，媒体类型均 `audio`：
- **喜马拉雅** `ximalaya`
- **小宇宙** `xiaoyuzhou`
- **网易云音乐** `netease_music`
- **Apple Podcasts** `apple_podcasts`

每个平台需要：
- `PLATFORM_LABELS` 中文名；`PLATFORM_MEDIA = "audio"`；`PLATFORM_CHIP` 颜色；`PLATFORM_FIELDS` 配置字段（如 token/cookie/RSS 等，按各平台常见接入方式给合理字段）。
- 后端 adapter：实现 `PublisherAdapter.publish(audio, metadata)` 接口骨架，缺依赖/凭证时返回 `PublishResult(status="failed", error_message=...)`（与现有 douyin/bilibili 占位风格一致），并注册进 adapter registry。

## 数据流

```
视频 run:   [articles] → S2 脚本 → S3 图片+语音 → S4 时间轴/预览 → S5 合成视频(MP4) → S6 发布(视频平台)
纯语音 run: [articles] → S2 脚本 → S3 仅语音(逐条 mp3) → S5 合并音频(output.mp3) → S6 发布(音频平台)
                                         （跳过 S4）
```

## 边界与错误处理

- 纯语音模式无任何成功音频 → S5 合并报错 → run 置 failed，提示"无可合并的语音"。
- 旧的视频 run 不受影响（`video_route` 仍是 hyperframes/ltx，走原路径）。
- 合并后逐条音频文件保留在磁盘（与现状一致，无需清理）。
- 发布到未实现/未配置的语音平台 → adapter 优雅返回失败，不阻断流水线。

## 测试计划

后端（pytest）：
- `run_stage3(audio_only=True)`：mock image/tts provider，断言不调用图片生成、`scene_assets` 仅含 audio。
- `_ffmpeg_merge_audio`：给若干假音频路径，断言生成 output.mp3 且按分镜顺序（可用 ffmpeg 探测时长或 mock ffmpeg 调用，校验 concat 列表顺序）。
- runner 音频路线：`video_route=="audio"` 时 S4 跳过、S5 走合并、`output_path` 为 mp3（用 monkeypatch 替掉真实 provider/ffmpeg）。
- 平台分类过滤为前端逻辑：纯语音模式发布选项只列 audio/both（前端验证，无后端测试）。

前端：
- `pnpm build` 通过。
- 浏览器实测：创建纯语音任务 → 音视频路线"纯语音"；执行阶段无预览；详情页 S2 隐藏图片元素、标签"脚本/语音生成"；"合成渲染"试听 + 下载 MP3；发布平台仅列音频平台；Publishers 页显示媒体徽标。
- 回归：视频模式流程标签"合成渲染"、其余不变。

## 影响文件

后端：
- `app/models/pipeline_run.py`（无需改列，仅 video_route 取值约定）
- `app/pipeline/stage3_*`（`run_stage3` 加 `audio_only`）
- `app/pipeline/runner.py`（S3 audio_only、跳过 S4、S5 音频合并、`_ffmpeg_merge_audio`）
- `app/providers/publisher/`（新增 ximalaya/xiaoyuzhou/netease_music/apple_podcasts 占位适配器 + 注册）
- 平台媒体分类（后端如需过滤）
- `tests/`（stage3 audio_only、音频合并、runner 音频路线、平台分类）

前端：
- `src/types/index.ts`（video_route 加 audio、STAGE_LABELS[5]、PLATFORM_LABELS/新平台、PLATFORM_MEDIA）
- `src/components/CreateRunDialog.tsx`（音视频路线、纯语音联动、发布平台过滤）
- `src/pages/Dashboard.tsx`（标签改名/隐藏预览、S2 隐藏图片元素、合成渲染试听+下载 MP3、按模式文案）
- `src/pages/Publishers.tsx`（媒体徽标、新平台配置字段）
