# 视频固定封面（片头）设计

## 目标

为每条生成视频在最前面加一个**固定封面/片头场景**：满屏封面图 + 居中大标题（如「每日AI资讯」/「最近7天AI资讯」）+ 副标题 + 旁白配音。封面参数可在**设置页**全局配置，也可在**预览页针对当前 run 临时覆盖**（不写全局）。

## 形态（已确认）

封面 = 视频最前面的一个**带配音的「场景0」**：封面图作背景 + 标题/副标题文字叠加 + 旁白 TTS 音频，时长 = 旁白音频长度；之后才是正常新闻分镜。复用现有 hyperframes timeline + 合成模型（封面是带 `is_cover` 标记的第一个 timeline entry）。

纯音频路线（`video_route == "audio"`）跳过封面（无画面）；comfyui / hyperframes 都加。

## 配置：`config.yaml` 新增 `cover` 段（位于 `overlay` 段下方）

对应 `app/config.py` 新增 `CoverCfg(BaseModel)`：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | `false` | 是否加封面 |
| `image` | str | `""` | 封面图路径（设置页上传后写入，如 `data/cover/cover.png`），空则纯色/渐变背景 |
| `title_template` | str | `"{period}AI资讯"` | 标题模板，含变量；**不含 "HOT"** |
| `subtitle` | str | `""` | 副标题，可含变量 |
| `narration` | str | `""` | 旁白文本（TTS），可含变量；空则不出封面音频→封面用固定时长兜底（见下） |
| `font_size` | int | `72` | 标题字号（px，按渲染分辨率计）；副标题自动取 `round(font_size*0.55)` |

`config.yaml.example` 同步加注释样例。

## 模板变量解析（按 run）

`resolve_cover_text(template, run)`：

- `{period}`：
  - AI HOT `aihot_config.method == "daily"` → `每日`；`weekly` → `每周`；`monthly` → `每月`
  - 否则（普通源 / items）→ `最近{X}`，X = 格式化 `time_range`（`7d`→`7天`、`1m`→`1个月`）
- `{days}`：`time_range` 的数字部分（`7d`→`7`）
- `{date}`：run 的日期（`YYYY-MM-DD`，取 `created_at` 本地日期）

标题/副标题/旁白都过同一解析器。

## 渲染链路

### Stage 3（素材生成，`runner.py`）
封面启用且 `video_route != "audio"` 时：
- 用解析后的 `narration` 文本 TTS → `assets/cover_audio.mp3`（复用 `build_tts_provider`）。
- 旁白为空 → 不出音频，封面走固定兜底时长（`COVER_FALLBACK_MS = 4000`）。
- 封面图不生成：用 `cover.image` 配置路径（或 per-run 覆盖路径）。

### Stage 4（时间轴，`stage4_timeline.py`）
`run_stage4(...)` 新增可选入参 `cover: dict | None`。封面启用时在 `entries` **头部插入封面 entry**：
```
{ "scene_id": 0, "is_cover": true, "start_ms": 0,
  "end_ms": cover_dur, "image_path": <封面图>, "audio_path": <cover_audio 或 "">,
  "audio_duration_ms": cover_dur, "title": <解析后标题>, "subtitle": <解析后副标题>,
  "subtitle_text": "", "subtitle_lines": [] }
```
后续新闻场景 `start_ms/end_ms` 顺延 `cover_dur`；`total_duration_ms` 含封面。`generate_srt` 跳过 `is_cover` entry（封面无字幕轨），新闻场景 SRT 时间自动带封面偏移。

### 合成模板（`composition.html.j2`）
对 `is_cover` 的 entry **特殊渲染**：满屏 `<img>` + 居中大标题（`cover_font_size`）+ 副标题（`*0.55`）；**不走**底部逐行字幕、不走右上角分组标题。其音频按现有 `audioEntries` 机制（start=0）播放。封面→首个新闻场景按现有 `transition` 转场。

`_render_html(...)` 新增入参：`cover`（封面 entry 数据 + 字号），透传模板。

## 设置页（`Settings.tsx`）
在「画面标题」section 下方新增 **「视频封面」** section：
- 开关（enabled）
- 封面图上传（显示当前图缩略 + 重新上传）
- 标题模板（输入框，提示可用变量）
- 副标题（输入框）
- 旁白（多行）
- 标题字号（滑块）

### 上传接口
后端新增 `POST /api/settings/cover-image`（multipart）：存到 `data/cover/cover.<ext>`，返回相对路径；前端写回 `cover.image`。（参照现有素材/导入的文件处理。）

## 预览页 per-run 覆盖（`Dashboard.tsx` S4 + `get_preview_html`）
在预览设置区新增「封面」子项：标题/副标题/字号/图片可临时改，经 **query 覆盖**实时重渲染封面（复用现有 per-run 覆盖机制，不写全局 config）。
- 图片 per-run 覆盖：上传到 run 目录（如 `runs/<id>/cover.png`），preview 用该路径。
- **旁白覆盖需重跑 stage3**（音频已烤进 timeline，与字幕折行同取舍）：预览覆盖只改视觉，旁白音频用已存 `cover_audio.mp3` 的时长。
- `get_preview_html` 重建 timeline 时，按 query 覆盖的视觉字段 + 已存 cover_audio 时长重建封面 entry。

## 已定细节
- 字号：单个 `font_size` 控标题，副标题自动 `*0.55`。
- 副标题/旁白：均支持 `{period}/{days}/{date}` 变量。
- 纯音频路线跳过封面。
- 封面 entry 无字幕轨。
- 旁白为空 → 封面无音频，用 `COVER_FALLBACK_MS=4000` 兜底时长。

## 不做（YAGNI）
- 封面图不做 AI 生成（固定上传）。
- 不做多套封面模板预设。
- 预览页旁白覆盖不做实时 re-TTS（需整体重跑 stage3）。
