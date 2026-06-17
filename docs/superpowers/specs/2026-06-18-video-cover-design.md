# 视频固定封面（片头）设计

## 目标

为生成视频在最前面加一个**固定封面/片头场景**：满屏封面图 + 居中大标题（模板，如「每日AI资讯」/「最近7天AI资讯」）+ 副标题 + 旁白配音。封面参数可在**设置页**全局配置，也可在**预览页针对当前 run 临时覆盖**（不写全局）。

## 形态（已确认）

封面 = 视频最前面的一个**带配音的「场景0」**：封面图作背景 + 标题/副标题文字叠加 + 旁白 TTS 音频，时长 = 旁白音频长度；之后才是正常新闻分镜。它是 timeline 头部一个带 `is_cover` 标记的 entry。

### 路线范围（评审修正）
- **仅 hyperframes 路线出封面**（封面的"满屏图 + 居中大标题 + 副标题"只在 `composition.html.j2`/HTML 路实现）。
- **comfyui 路线跳过封面**（其 `comfyui_composer.py` 对每个 entry 做 img2video + 右上角 drawtext，没有居中大标题概念，且会把封面图错误地做成运动视频；comfyui 封面留作后续独立子任务）。
- **纯音频路线跳过封面**（无画面）。
- 判断：`run.video_route == "hyperframes"` 才加封面（注意 video_route 是运行时字符串值，`audio` 不在 `VideoRoute` 枚举里但运行时存在）。

## 配置：`config.yaml` 新增 `cover` 段（位于 `overlay` 段下方）

对应 `app/config.py` 新增 `CoverCfg(BaseModel)`：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | `false` | 是否加封面 |
| `image` | str | `""` | 全局封面图路径（设置页上传后写入，如 `data/cover/cover.png`），空则纯色/渐变背景 |
| `title_template` | str | `"{period}AI资讯"` | 标题模板，含变量；**不含 "HOT"** |
| `subtitle` | str | `""` | 副标题，可含变量 |
| `narration` | str | `""` | 旁白文本（TTS），可含变量；空则封面无音频→走兜底时长 |
| `font_size` | int | `72` | 标题字号（px，按渲染分辨率计）；副标题自动取 `round(font_size*0.55)` |

`config.yaml.example` 同步加注释样例。常量 `COVER_FALLBACK_MS = 4000`（无旁白时封面时长）。

## 模板变量解析（按 run）

`resolve_cover_text(template: str, run) -> str`：

- `{period}`：
  - run 有 `aihot_config` 且 `method == "daily"` → `每日`；`weekly` → `每周`；`monthly` → `每月`
  - 否则（`aihot_config` 为 None 的普通源 / `items`）→ `最近{X}`，X = 格式化 `time_range`（`7d`→`7天`、`1m`→`1个月`）
- `{days}`：`time_range` 的数字部分（`7d`→`7`）
- `{date}`：run 日期（`YYYY-MM-DD`，取 `created_at` 本地日期）

标题/副标题/旁白都过同一解析器。`aihot_config` 为 None 时只可能命中 `最近{X}` 分支。

## 封面 entry 的组装（核心，统一 helper）

新增 `_build_cover_entry(run, cfg, run_dir) -> dict | None`（放 `runner.py` 或 `stage4_timeline.py`，供所有重跑点复用）。返回：
```
{ "scene_id": 0, "is_cover": true, "start_ms": 0,
  "end_ms": cover_dur_ms, "image_path": <run_dir/assets/cover_image.png 的路径>,
  "audio_path": <run_dir/assets/cover_audio.mp3 或 "">,
  "audio_duration_ms": cover_dur_ms,
  "title": <解析后标题>, "subtitle": <解析后副标题>,
  "cover_font_size": <cfg.cover.font_size>,
  "subtitle_text": "", "subtitle_lines": [] }
```
- `cover_dur_ms`：cover_audio 存在则取其真实时长，否则 `COVER_FALLBACK_MS`。
- 关键：**封面视觉（title/subtitle/font_size）全部内联进 entry**，不经任何 `_render_html` 新增入参（出片路径 `compose()→_render_html(timeline, resolution, run_dir)` 不传额外 kwargs，新增参数到不了成片）。

### 封面图必须落进 run_dir（评审 D）
`_render_html` 对 `image_path` 做 `relative_to(run_dir)`，`data/cover/` 不在 run_dir 内会解析失败。所以：
- 全局封面图：stage3（或封面构建时）**复制**到 `run_dir/assets/cover_image.png`。
- per-run 覆盖图：上传也写 `run_dir/assets/cover_image.png`（覆盖）。
- 渲染统一走相对路径，回显/预览复用现有 `/runs/{id}/assets/{filename}` 路由。

## 渲染链路

### Stage 3（`runner.py`）
`run.video_route == "hyperframes"` 且 `cfg.cover.enabled` 时，在素材生成阶段额外：
- 把全局封面图（或 per-run 图）复制到 `assets/cover_image.png`。
- 旁白非空 → 用解析后文本 TTS（`build_tts_provider`）出 `assets/cover_audio.mp3`；旁白空 → 不出音频。

### Stage 4（`stage4_timeline.py`）
`run_stage4(...)` 新增可选入参 `cover: dict | None`（即上面 helper 的产物）。
- 反推/正常构建 entries 后，若 `cover` 非空，**插到 entries 头部**，后续新闻场景 `start_ms/end_ms` 顺延 `cover_dur_ms`，`total_duration_ms` 含封面。
- `generate_srt` 无需特判：封面 `subtitle_lines: []` 自然不产字幕行，新闻场景 SRT 时间因累加天然带封面偏移。

### 合成模板（`composition.html.j2`）
对 `entry.is_cover` 的 entry **特殊渲染**：满屏 `<img>` + 居中大标题（`entry.cover_font_size`）+ 副标题（`*0.55`）；**不走**底部逐行字幕、不走右上角分组标题。
- `<audio>` 仅在 `entry.audio_path` 非空时渲染（避免空 src）。
- 封面在头部，`loop.first` 自然不加转场；封面→首个新闻场景沿用现有 `transition`（`#s0` 作 prev，新闻 id 从 1 起不冲突）。
- 注：`_render_html` **不加** `cover` 参数；模板只靠 `entry.is_cover` 分支。

## 所有"重跑 run_stage4"的入口都要带封面（评审 C，关键）

现有从落盘 timeline **反推 scene_assets 重跑 run_stage4** 的地方，会把 `scene_id=0` 的封面当普通场景（`narration_map.get(0)` 为空）→ 静默破坏封面。修正：

1. 反推 scene_assets 时**过滤掉 `is_cover` 的 entry**。
2. 重跑 run_stage4 时**重新传入 `cover=_build_cover_entry(...)`**。

需改的三处（spec 此前漏了后两处）：
- `pipeline.py:get_preview_html`（改字号/行数/间隔/封面视觉时重跑 stage4）
- `pipeline.py:regen_scene_audio`（改任一新闻旁白都重跑 stage4）
- `pipeline.py:regen_script → _regen_bg`（「重新生成」跑 [2,3,4]，stage3+4 都要带封面）

## 设置页（`Settings.tsx`）
在「画面标题」section 下方新增 **「视频封面」** section：
- 开关（enabled）
- 封面图上传（显示当前图缩略 + 重新上传）
- 标题模板（输入框，提示可用变量 `{period}/{days}/{date}`）
- 副标题、旁白（输入框/多行）
- 标题字号（滑块）

### 上传与回显接口
- `POST /api/settings/cover-image`（multipart `UploadFile`，参照 `pipeline.py:import_article_file`）：存 `data/cover/cover.<ext>`，返回相对路径，前端写回 `cover.image`。
- `GET /api/settings/cover-image`：返回当前全局封面图（`FileResponse`）供设置页缩略回显（`data/cover/` 不在现有静态路由内，需新增）。

## 预览页 per-run 覆盖（`Dashboard.tsx` S4 + `get_preview_html`）
预览设置区新增「封面」子项：标题/副标题/字号/图片可临时改，经 **query 覆盖**实时重渲染封面（复用现有 per-run 覆盖机制，不写全局 config）。
- 视觉字段（标题/副标题/字号）：query 参数 → `get_preview_html` 用覆盖值重建 cover entry。
- 图片 per-run 覆盖：上传到 `runs/<id>/assets/cover_image.png`，preview 用之。
- cover_audio 时长：用已存 `assets/cover_audio.mp3`；不存在（首次/旁白空）→ `COVER_FALLBACK_MS`。
- **旁白覆盖需重跑 stage3**（音频已烤进时长，与字幕折行同取舍）：预览覆盖只改视觉，不实时 re-TTS。

## 前端类型 / 客户端
- `frontend/src/types/index.ts`：timeline entry 类型加 `is_cover?`/`title?`/`subtitle?`/`cover_font_size?`；`AppSettings` 加 `cover` 段。
- `frontend/src/api/client.ts`：新增 cover-image 上传/回显、preview-html 的 cover query 参数。

## 已定细节
- 仅 hyperframes 路出封面；comfyui/纯音频跳过。
- 字号：单个 `font_size` 控标题，副标题自动 `*0.55`。
- 副标题/旁白均支持 `{period}/{days}/{date}`。
- 封面 entry 无字幕轨、`subtitle_lines: []`。
- 旁白为空 → 封面无音频，`COVER_FALLBACK_MS=4000` 兜底。
- 封面图统一落 `run_dir/assets/cover_image.png` 走相对路径。
- 所有重跑 run_stage4 的入口（preview-html / regen_scene_audio / regen-script[2,3,4]）都重新注入封面。

## 不做（YAGNI）
- comfyui 路线封面（留作后续独立子任务：静态封面 clip + 居中 drawtext）。
- 封面图不做 AI 生成（固定上传）。
- 不做多套封面模板预设。
- 预览页旁白覆盖不做实时 re-TTS（需整体重跑 stage3）。
