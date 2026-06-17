# 视频固定封面（片头）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给生成视频最前面加一个带配音的固定封面（满屏图+居中标题/副标题+旁白TTS），全局可配、预览页可 per-run 覆盖；hyperframes 路内联渲染，comfyui 路拼接封面片段到开头。

**Architecture:** 封面是 timeline 头部一个带 `is_cover` 标记的 entry（视觉字段全内联进 entry）。新增纯函数模块 `app/pipeline/cover.py` 负责文案解析与 entry 组装。stage3 出 `cover_audio.mp3`+拷封面图进 run_dir/assets；stage4 在 timeline 头部插封面；`composition.html.j2` 按 `is_cover` 分支渲染；comfyui 路在 stage5 跳过封面 entry、单独渲封面片段后 FFmpeg 拼接。所有"反推 timeline 重跑 run_stage4"的入口统一过滤 `is_cover` 并重新注入封面。

**Tech Stack:** Python/FastAPI、pydantic、Jinja2、FFmpeg、edge-tts；React/TS/Tailwind。spec：`docs/superpowers/specs/2026-06-18-video-cover-design.md`。

**测试约定：** 纯逻辑（文案解析、entry 组装、timeline 插入、SRT 偏移、模板渲染）走 pytest TDD；渲染/FFmpeg/TTS/浏览器/UI 这些环境内跑不动的，给明确**手动冒烟步骤**（用户自跑后端）。后端测试：`cd backend && pytest`。

---

## Phase 1 — 配置与封面纯逻辑

### Task 1: `CoverCfg` 配置项

**Files:**
- Modify: `backend/app/config.py`（在 `OverlayCfg` 定义后、`Settings` 类里）
- Modify: `config.yaml.example`（`overlay` 段后）

- [ ] **Step 1: 加 `CoverCfg` 类**

在 `backend/app/config.py` 中 `OverlayCfg` 类**之后**加：

```python
class CoverCfg(BaseModel):
    """视频固定封面（片头）。统一用 hyperframes 渲染；comfyui 路线拼接到成片开头。"""
    enabled: bool = False
    image: str = ""                       # 全局封面图相对路径（设置页上传后写入，如 data/cover/cover.png）
    title_template: str = "{period}AI资讯"  # 标题模板，支持 {period}/{days}/{date}
    subtitle: str = ""                    # 副标题，可含变量
    narration: str = ""                   # 旁白文本（TTS），可含变量；空则封面无音频
    font_size: int = 72                   # 标题字号（px，按渲染分辨率）；副标题自动 *0.55
```

- [ ] **Step 2: 把 `cover` 挂到 `Settings`**

在 `Settings` 类里（与 `overlay: OverlayCfg = OverlayCfg()` 同级）加一行：

```python
    cover: CoverCfg = CoverCfg()
```

- [ ] **Step 3: `config.yaml.example` 加样例**

在 `overlay:` 段之后加：

```yaml
cover:
  enabled: false
  image: ""                       # 设置页上传封面图后写入（如 data/cover/cover.png）
  title_template: "{period}AI资讯"  # 变量：{period}(每日/每周/每月/最近X天) {days} {date}
  subtitle: ""
  narration: ""                   # 旁白文本；空则封面无配音，走 4s 兜底时长
  font_size: 72                   # 标题字号（px，按渲染分辨率）；副标题自动 0.55×
```

- [ ] **Step 4: 验证加载**

Run: `cd backend && python -c "from app.config import get_settings; print(get_settings().cover.title_template)"`
Expected: 打印 `{period}AI资讯`（无异常）

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py config.yaml.example
git commit -m "feat(cover): 新增 CoverCfg 配置项"
```

---

### Task 2: 封面文案解析 `resolve_cover_text`（TDD）

**Files:**
- Create: `backend/app/pipeline/cover.py`
- Test: `backend/tests/test_cover.py`

封面模块集中放封面纯逻辑。`resolve_cover_text` 把模板变量按 run 填充。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_cover.py`：

```python
from types import SimpleNamespace
from app.pipeline.cover import resolve_cover_text


def _run(**kw):
    base = dict(aihot_config=None, time_range="7d", created_at="2026-06-18T01:00:00+00:00")
    base.update(kw)
    return SimpleNamespace(**base)


def test_period_normal_source_days():
    assert resolve_cover_text("{period}AI资讯", _run(time_range="7d")) == "最近7天AI资讯"

def test_period_normal_source_month():
    assert resolve_cover_text("{period}AI资讯", _run(time_range="1m")) == "最近1个月AI资讯"

def test_period_aihot_daily():
    r = _run(aihot_config='{"method": "daily"}')
    assert resolve_cover_text("{period}AI资讯", r) == "每日AI资讯"

def test_period_aihot_weekly():
    r = _run(aihot_config='{"method": "weekly"}')
    assert resolve_cover_text("{period}AI资讯", r) == "每周AI资讯"

def test_days_and_date():
    r = _run(time_range="7d")
    assert resolve_cover_text("{days}天·{date}", r) == "7天·2026-06-18"

def test_empty_template():
    assert resolve_cover_text("", _run()) == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_cover.py -v`
Expected: FAIL（`No module named 'app.pipeline.cover'`）

- [ ] **Step 3: 实现 `resolve_cover_text`**

`backend/app/pipeline/cover.py`：

```python
"""视频固定封面（片头）纯逻辑：文案解析 + 封面 timeline entry 组装。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

COVER_FALLBACK_MS = 4000  # 旁白为空时封面兜底时长


def _fmt_time_range(tr: str) -> str:
    """'7d'->'7天'、'1m'->'1个月'，无法解析则原样。"""
    m = re.fullmatch(r"\s*(\d+)\s*([dwmy])\s*", tr or "")
    if not m:
        return tr or ""
    unit = {"d": "天", "w": "周", "m": "个月", "y": "年"}.get(m.group(2), "")
    return f"{m.group(1)}{unit}"


def _aihot_method(run) -> str:
    raw = getattr(run, "aihot_config", None)
    if not raw:
        return ""
    try:
        return (json.loads(raw) or {}).get("method", "") or ""
    except Exception:
        return ""


def resolve_cover_text(template: str, run) -> str:
    """把封面模板里的 {period}/{days}/{date} 按 run 填充。"""
    if not template:
        return ""
    tr = getattr(run, "time_range", "") or ""
    method = _aihot_method(run)
    period = {"daily": "每日", "weekly": "每周", "monthly": "每月"}.get(method) or f"最近{_fmt_time_range(tr)}"
    days_m = re.match(r"\s*(\d+)", tr)
    days = days_m.group(1) if days_m else ""
    # 日期：取 created_at 的本地日；缺失则今天
    date_str = ""
    created = getattr(run, "created_at", None)
    try:
        if isinstance(created, str) and created:
            date_str = datetime.fromisoformat(created).astimezone().strftime("%Y-%m-%d")
        elif isinstance(created, datetime):
            date_str = created.astimezone().strftime("%Y-%m-%d")
    except Exception:
        date_str = ""
    if not date_str:
        date_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    return (template
            .replace("{period}", period)
            .replace("{days}", days)
            .replace("{date}", date_str))
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_cover.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/cover.py backend/tests/test_cover.py
git commit -m "feat(cover): resolve_cover_text 模板变量解析"
```

---

### Task 3: 封面 entry 组装 `build_cover_entry`（TDD）

**Files:**
- Modify: `backend/app/pipeline/cover.py`
- Modify: `backend/tests/test_cover.py`

`build_cover_entry` 产出 timeline 头部的封面 entry。音频/图片路径由调用方（runner）准备好后传入，本函数只负责组装 + 文案解析 + 时长取值，保持纯函数可测。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_cover.py` 追加：

```python
from app.pipeline.cover import build_cover_entry, COVER_FALLBACK_MS
from app.config import CoverCfg


def test_build_cover_entry_with_audio():
    cfg = CoverCfg(enabled=True, title_template="{period}AI资讯", subtitle="每天3分钟", font_size=80)
    e = build_cover_entry(cfg, _run(time_range="7d"),
                          image_rel="assets/cover_image.png",
                          audio_rel="assets/cover_audio.mp3", audio_ms=5200)
    assert e["is_cover"] is True
    assert e["scene_id"] == 0
    assert e["start_ms"] == 0 and e["end_ms"] == 5200 and e["audio_duration_ms"] == 5200
    assert e["title"] == "最近7天AI资讯"
    assert e["subtitle"] == "每天3分钟"
    assert e["cover_font_size"] == 80
    assert e["image_path"] == "assets/cover_image.png"
    assert e["audio_path"] == "assets/cover_audio.mp3"
    assert e["subtitle_lines"] == []

def test_build_cover_entry_no_audio_fallback():
    cfg = CoverCfg(enabled=True)
    e = build_cover_entry(cfg, _run(), image_rel="", audio_rel="", audio_ms=0)
    assert e["end_ms"] == COVER_FALLBACK_MS
    assert e["audio_path"] == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_cover.py -v -k build_cover_entry`
Expected: FAIL（`cannot import name 'build_cover_entry'`）

- [ ] **Step 3: 实现 `build_cover_entry`**

在 `backend/app/pipeline/cover.py` 追加：

```python
def build_cover_entry(cfg, run, *, image_rel: str, audio_rel: str, audio_ms: int) -> dict:
    """组装 timeline 头部的封面 entry（视觉字段全内联）。

    image_rel/audio_rel：相对 run_dir 的素材路径（调用方已把图/音频放进 run_dir/assets）。
    audio_ms：cover_audio 真实时长；<=0 则用 COVER_FALLBACK_MS。
    """
    dur = audio_ms if audio_ms and audio_ms > 0 else COVER_FALLBACK_MS
    return {
        "scene_id": 0,
        "is_cover": True,
        "start_ms": 0,
        "end_ms": dur,
        "image_path": image_rel,
        "audio_path": audio_rel or "",
        "audio_duration_ms": dur,
        "title": resolve_cover_text(cfg.title_template, run),
        "subtitle": resolve_cover_text(cfg.subtitle, run),
        "cover_font_size": cfg.font_size,
        "subtitle_text": "",
        "subtitle_lines": [],
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_cover.py -v`
Expected: 全部 passed（8）

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/cover.py backend/tests/test_cover.py
git commit -m "feat(cover): build_cover_entry 组装封面 entry"
```

---

## Phase 2 — 时间轴集成

### Task 4: `run_stage4` 接收并插入封面（TDD）

**Files:**
- Modify: `backend/app/pipeline/stage4_timeline.py:22`（`run_stage4` 签名与函数体）
- Test: `backend/tests/test_cover_timeline.py`

`run_stage4` 新增可选入参 `cover: dict | None`；非空时把它插到 entries 头部，后续场景 start/end 顺延，total 含封面。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_cover_timeline.py`：

```python
from app.pipeline.stage4_timeline import run_stage4


def _script():
    return {"scenes": [
        {"id": 1, "narration": "第一条新闻内容。", "title": "T1", "group_id": 1},
        {"id": 2, "narration": "第二条新闻内容。", "title": "T2", "group_id": 2},
    ]}


def _assets():
    return [
        {"scene_id": 1, "image": {"file_path": "/r/assets/scene_01_image.png"},
         "audio": {"file_path": "/r/assets/scene_01_audio.mp3", "duration_ms": 3000}},
        {"scene_id": 2, "image": {"file_path": "/r/assets/scene_02_image.png"},
         "audio": {"file_path": "/r/assets/scene_02_audio.mp3", "duration_ms": 4000}},
    ]


def test_no_cover_unchanged():
    tl = run_stage4(_script(), _assets(), scene_gap_ms=0)
    assert tl["entries"][0]["scene_id"] == 1
    assert tl["entries"][0]["start_ms"] == 0


def test_cover_prepended_and_shift():
    cover = {"scene_id": 0, "is_cover": True, "start_ms": 0, "end_ms": 5000,
             "image_path": "assets/cover_image.png", "audio_path": "assets/cover_audio.mp3",
             "audio_duration_ms": 5000, "title": "每日AI资讯", "subtitle": "",
             "cover_font_size": 72, "subtitle_text": "", "subtitle_lines": []}
    tl = run_stage4(_script(), _assets(), scene_gap_ms=0, cover=cover)
    e = tl["entries"]
    assert e[0]["is_cover"] is True and e[0]["start_ms"] == 0 and e[0]["end_ms"] == 5000
    # 第一条新闻顺延到封面之后
    assert e[1]["scene_id"] == 1 and e[1]["start_ms"] == 5000
    assert e[2]["scene_id"] == 2 and e[2]["start_ms"] == 5000 + 3000
    assert tl["total_duration_ms"] == 5000 + 3000 + 4000
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_cover_timeline.py -v`
Expected: FAIL（`run_stage4() got an unexpected keyword argument 'cover'`）

- [ ] **Step 3: 改 `run_stage4`**

`stage4_timeline.py`：① 函数签名末尾加 `cover: dict | None = None,`。② 函数末尾，把现有 `return {"entries": entries, "total_duration_ms": current_ms}`（约 line 79）改为先插封面再算偏移：

```python
    if cover:
        shift = int(cover.get("end_ms", 0))
        for e in entries:
            e["start_ms"] += shift
            e["end_ms"] += shift
            for sl in e.get("subtitle_lines", []):
                sl["start_ms"] += shift
                sl["end_ms"] += shift
        entries = [cover] + entries
        current_ms += shift

    return {"entries": entries, "total_duration_ms": current_ms}
```

> 注意：现有 `_split_subtitles` 产出的 `subtitle_lines` 的 start_ms/end_ms 是**相对场景**还是**绝对**？打开 `stage4_timeline.py` 确认（约 line 57）。若是相对场景则**不要**移它们（渲染时 `start_s + line.start_s` 已叠加场景 start）；若是绝对则要移。**先读代码确认**，据此保留或删掉上面 `for sl in ...` 两行。`generate_srt` 怎么用 lines 同样决定这点——以实际为准，测试里只断言 entry 的 start/end，先让 entry 偏移正确。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_cover_timeline.py tests/test_subtitle_split.py -v`
Expected: 全部 passed（含原有字幕测试不回归）

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/stage4_timeline.py backend/tests/test_cover_timeline.py
git commit -m "feat(cover): run_stage4 头部插封面 entry + 顺延"
```

---

### Task 5: SRT 偏移验证（TDD）

**Files:**
- Modify: `backend/tests/test_cover_timeline.py`
- （可能 Modify: `backend/app/pipeline/stage4_timeline.py` 的 `generate_srt`，仅当封面污染了字幕）

封面 `subtitle_lines: []` 不产字幕；新闻字幕时间应整体带封面偏移。

- [ ] **Step 1: 写测试**

追加到 `backend/tests/test_cover_timeline.py`：

```python
from app.pipeline.stage4_timeline import generate_srt


def test_srt_skips_cover_and_offsets_news():
    cover = {"scene_id": 0, "is_cover": True, "start_ms": 0, "end_ms": 5000,
             "image_path": "", "audio_path": "", "audio_duration_ms": 5000,
             "title": "每日AI资讯", "subtitle": "", "cover_font_size": 72,
             "subtitle_text": "", "subtitle_lines": []}
    tl = run_stage4(_script(), _assets(), scene_gap_ms=0, cover=cover)
    srt = generate_srt(tl)
    # 封面无字幕文本；首条新闻字幕从 ~00:00:05 起（封面偏移）
    assert "每日AI资讯" not in srt
    assert "00:00:05" in srt or "00:00:04," in srt  # 第一条新闻字幕起点在封面之后
```

- [ ] **Step 2: 运行**

Run: `cd backend && pytest tests/test_cover_timeline.py::test_srt_skips_cover_and_offsets_news -v`
Expected: PASS（封面 lines 为空自然跳过；新闻 entry start_ms 已带偏移）。**若 FAIL**（封面被算进 SRT 或偏移不对），读 `generate_srt`（line ~170）确认它按 entry 的绝对时间还是累加——按实际修正（封面 lines 空即应跳过，无需特判）。

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_cover_timeline.py backend/app/pipeline/stage4_timeline.py
git commit -m "test(cover): SRT 跳过封面 + 新闻字幕带偏移"
```

---

## Phase 3 — 渲染

### Task 6: 合成模板 `is_cover` 分支（TDD 渲染存在性）

**Files:**
- Modify: `backend/app/providers/composer/templates/composition.html.j2`
- Test: `backend/tests/test_cover_render.py`

模板对封面 entry 渲染：满屏图 + 居中大标题 + 副标题；不走底部字幕/分组标题；音频仅在有 audio_path 时渲染。

- [ ] **Step 1: 写测试（断言渲染产物含封面标记、字号）**

`backend/tests/test_cover_render.py`：

```python
from app.providers.composer.hyperframes_composer import HyperframesComposer


def _timeline(cover_audio=""):
    return {"total_duration_ms": 8000, "entries": [
        {"scene_id": 0, "is_cover": True, "start_s": 0, "end_s": 5, "duration_s": 5,
         "image_path": "assets/cover_image.png", "audio_path": cover_audio,
         "audio_duration_s": 5, "title": "每日AI资讯", "subtitle": "每天3分钟",
         "cover_font_size": 80, "subtitle_lines": [], "group_id": None, "title_overlays": []},
        {"scene_id": 1, "start_s": 5, "end_s": 8, "duration_s": 3,
         "image_path": "assets/scene_01_image.png", "audio_path": "assets/scene_01_audio.mp3",
         "audio_duration_s": 3, "subtitle_text": "新闻", "subtitle_lines": [],
         "title": "T1", "group_id": 1},
    ]}


def test_cover_html_has_title_and_fontsize():
    html = HyperframesComposer()._render_html(_timeline(), "1080x1920", __import__("pathlib").Path("."))
    assert "每日AI资讯" in html
    assert "每天3分钟" in html
    assert "80px" in html  # cover_font_size

def test_cover_without_audio_has_no_empty_audio_src():
    html = HyperframesComposer()._render_html(_timeline(cover_audio=""), "1080x1920", __import__("pathlib").Path("."))
    assert 'src=""' not in html
```

> 注：`_render_html` 入参是 timeline+resolution+run_dir；它内部会把 entries 转模板数据。**先读 `hyperframes_composer.py:64-128`** 确认 entries 经过怎样的预处理（`start_s`/`duration_s`/`image_path` 相对化等），按其真实结构补齐测试 timeline 字段，必要时直接喂它 `_render_html` 接受的 timeline（带 `start_ms`/`end_ms`/`audio_duration_ms`，让 `_render_html` 自己换算）。以实际签名为准调整测试输入。

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && pytest tests/test_cover_render.py -v`
Expected: FAIL（模板还没渲染封面/字号）

- [ ] **Step 3: 改 `hyperframes_composer._render_html` 透传封面字段 + 改模板**

① `_render_html`（line ~95-107 组装 entries 的循环）：把 `is_cover`/`title`/`subtitle`/`cover_font_size` 一并放进 entry 模板数据（其余字段已有）。对 `is_cover` entry 跳过 `subtitle_lines`/`title_overlays` 处理。

② `composition.html.j2`：在 scenes 循环（`{% for entry in entries %}` 渲染 `.scene` 那段，约 line 37-47）里对封面分支：

```jinja
{% for entry in entries %}
{% if entry.is_cover %}
<div class="scene clip cover" id="s{{ entry.scene_id }}"
     data-start="{{ entry.start_s }}" data-duration="{{ entry.duration_s }}" data-track-index="0"
     {% if not loop.first %}style="visibility:hidden;opacity:0;"{% endif %}>
  <div class="scene-content">
    {% if entry.image_path %}<img src="{{ entry.image_path }}" alt="cover">{% endif %}
    <div class="cover-overlay">
      <div class="cover-title" style="font-size:{{ entry.cover_font_size | default(72) }}px">{{ entry.title }}</div>
      {% if entry.subtitle %}<div class="cover-subtitle" style="font-size:{{ (entry.cover_font_size | default(72) * 0.55) | round | int }}px">{{ entry.subtitle }}</div>{% endif %}
    </div>
  </div>
</div>
{% else %}
... 原有普通场景渲染 ...
{% endif %}
{% endfor %}
```

CSS（`<style>` 内补）：

```css
.cover .cover-overlay { position:absolute; inset:0; display:flex; flex-direction:column;
  align-items:center; justify-content:center; gap:0.4em; text-align:center; padding:8%;
  background:rgba(0,0,0,0.28); }
.cover-title { color:#fff; font-weight:800; line-height:1.25;
  text-shadow:2px 2px 10px rgba(0,0,0,0.8); font-family:"Microsoft YaHei","PingFang SC",sans-serif; }
.cover-subtitle { color:#eee; line-height:1.4;
  text-shadow:1px 1px 6px rgba(0,0,0,0.8); font-family:"Microsoft YaHei","PingFang SC",sans-serif; }
```

③ 音频元素（line 60-67 `{% for entry in entries %}<audio ...>`）：改为仅在 `entry.audio_path` 非空时渲染：`{% if entry.audio_path %}<audio ...>{% endif %}`。

④ 字幕/分组标题循环（line 50-58、111-114）：跳过 `is_cover` entry（`{% if not entry.is_cover %}`）。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && pytest tests/test_cover_render.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/composer/templates/composition.html.j2 backend/app/providers/composer/hyperframes_composer.py backend/tests/test_cover_render.py
git commit -m "feat(cover): 合成模板 is_cover 分支（满屏图+居中标题/副标题）"
```

---

### Task 7: comfyui 跳过封面 + 封面片段渲染 + 拼接

**Files:**
- Modify: `backend/app/providers/composer/comfyui_composer.py`（遍历 entries 跳过 is_cover）
- Modify: `backend/app/providers/composer/hyperframes_composer.py`（加 `render_cover_clip`）
- Modify: `backend/app/pipeline/runner.py`（S5 comfyui 分支：渲封面片段 + FFmpeg 拼接）

这部分含 FFmpeg/npx，环境内难单测——以**手动冒烟**为主，代码要写全。

- [ ] **Step 1: comfyui_composer 跳过封面 entry**

打开 `comfyui_composer.py`，其遍历 entries 做 img2video 的循环（约 line 29-45）开头加：

```python
        for entry in timeline_json.get("entries", []):
            if entry.get("is_cover"):
                continue  # 封面不走 comfyui，改由 hyperframes 渲片段后拼接
            ...
```

- [ ] **Step 2: `HyperframesComposer.render_cover_clip`**

在 `hyperframes_composer.py` 加方法：用仅含封面 entry 的 timeline 渲一个独立片段 mp4。

```python
    async def render_cover_clip(self, cover_entry: dict, resolution: str, run_dir: Path, output_path: str) -> str:
        """把单个封面 entry 渲成独立片段（cover.mp4），供 comfyui 路拼接到开头。"""
        # 封面 entry 的 end_ms 即总时长；start 归零
        e = dict(cover_entry); e["start_ms"] = 0
        timeline = {"entries": [e], "total_duration_ms": int(e["end_ms"])}
        html = self._render_html(timeline, resolution, run_dir)
        (run_dir / "cover.html").write_text(html, encoding="utf-8")
        # 复用 compose 的 npx hyperframes 渲染路径；失败回退 FFmpeg（静态图+drawtext+音频）
        # 实现：参照 compose() 里 npx hyperframes render 的调用，cwd=run_dir，输入 cover.html，输出 output_path
        ...
        return output_path
```

> 实现细节：读 `compose()` 现有的 `npx hyperframes render` 调用方式（它写 `index.html` 后跑 npx）。把它抽成「渲指定 html → mp4」的内部步骤复用；render_cover_clip 用 `cover.html`。npx 失败时 FFmpeg 兜底：`ffmpeg -loop 1 -i cover_image -i cover_audio -vf "drawtext居中标题+副标题,scale=WxH" -t dur -shortest cover.mp4`（无音频则 `-t COVER_FALLBACK_MS/1000`）。**先读 compose() 全文再实现**，保持与现有 npx 调用一致。

- [ ] **Step 3: runner S5 comfyui 分支拼接**

`runner.py` 的 S5 comfyui 成功出 `main.mp4` 后（约 line 850-862，`ComfyUIVideoComposer(...).compose(...)` 之后），若封面启用：渲封面片段 + FFmpeg 拼接：

```python
            # comfyui 出片后，若有封面 → 渲封面片段并拼到开头
            cover_entry = next((e for e in timeline.get("entries", []) if e.get("is_cover")), None)
            if cover_entry and run.video_route == "comfyui":
                from app.providers.composer.hyperframes_composer import HyperframesComposer
                cover_mp4 = str(run_dir / "cover.mp4")
                await HyperframesComposer(overlay=cfg.overlay).render_cover_clip(
                    cover_entry, resolution, run_dir, cover_mp4)
                final_path = _ffmpeg_concat([cover_mp4, final_path], str(run_dir / "output.mp4"), resolution)
```

新增 `_ffmpeg_concat(parts, out, resolution)`（runner.py，参照现有 `_ffmpeg_compose`）：重编码拼接到统一分辨率/帧率（concat filter 或 demuxer）。**读 `_ffmpeg_compose` 风格后实现。**

- [ ] **Step 4: 手动冒烟（用户自跑后端）**

- 一个 comfyui 路线 run，启用封面 → 成片开头是封面片段（图+居中标题+副标题+旁白），之后是 comfyui 新闻视频，字幕时间对齐（带封面偏移）。
- 封面 npx 失败时走 FFmpeg 兜底仍出片。

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/composer/comfyui_composer.py backend/app/providers/composer/hyperframes_composer.py backend/app/pipeline/runner.py
git commit -m "feat(cover): comfyui 路跳过封面+渲封面片段+FFmpeg拼接到开头"
```

---

## Phase 4 — Runner 接线（封面构建落地）

### Task 8: stage3 出 cover_audio + 拷封面图；stage4 传 cover

**Files:**
- Modify: `backend/app/pipeline/runner.py`（stage3 末尾、stage4 调用处）
- Modify: `backend/app/pipeline/cover.py`（加 `prepare_cover_assets` helper）

集中在 runner 层准备封面素材并构建 entry，供 stage4 与（重跑场景）复用。

- [ ] **Step 1: `prepare_cover_assets` helper**

在 `cover.py` 加（含 IO，但单职责）：

```python
import shutil
from pathlib import Path
from app.providers.tts.audio_duration import measure_audio_ms


async def prepare_cover_assets(cfg_cover, run, run_dir: Path, tts, *, override_image: str = "") -> dict | None:
    """封面启用且非纯音频时，准备封面图/音频并返回封面 entry；否则 None。

    - 图：override_image（per-run 上传，绝对/相对皆可）优先，否则 cfg_cover.image；拷到 assets/cover_image.png。
    - 音：narration 解析后非空则 TTS 出 assets/cover_audio.mp3。
    tts：build_tts_provider 实例（None 则跳过出音频，用兜底时长）。
    """
    if not cfg_cover.enabled:
        return None
    assets = run_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    # 图片
    image_rel = ""
    src_img = override_image or cfg_cover.image
    if src_img:
        sp = Path(src_img)
        if not sp.is_absolute():
            sp = Path(__file__).resolve().parents[3] / src_img  # 仓库根相对
        if sp.is_file():
            dst = assets / "cover_image.png"
            shutil.copyfile(sp, dst)
            image_rel = "assets/cover_image.png"
    # 音频
    audio_rel, audio_ms = "", 0
    narration = resolve_cover_text(cfg_cover.narration, run)
    if narration and tts is not None:
        out = str(assets / "cover_audio.mp3")
        await tts.synthesize(text=narration, output_path=out)
        audio_ms = measure_audio_ms(out) or 0
        if audio_ms > 0:
            audio_rel = "assets/cover_audio.mp3"
    return build_cover_entry(cfg_cover, run, image_rel=image_rel, audio_rel=audio_rel, audio_ms=audio_ms)
```

- [ ] **Step 2: runner stage3 调它 + stage4 传 cover**

`runner.py`：
- stage3 段（`if 3 in selected:` 末尾、`run_stage4` 之前）加：仅 `run.video_route in ("hyperframes", "comfyui")` 时构建封面 entry，存到本地变量 `cover_entry`：

```python
        from app.pipeline.cover import prepare_cover_assets
        cover_entry = None
        if cfg.cover.enabled and run.video_route in ("hyperframes", "comfyui"):
            from app.providers.tts import build_tts_provider
            cover_entry = await prepare_cover_assets(cfg.cover, run, run_dir, build_tts_provider(cfg))
```

> 若 stage3 未选但 stage4 选了（罕见），`cover_entry` 为 None；可在 stage4 段开头兜底再 build（无音频则兜底时长）。MVP 先按 stage3+4 同跑处理。

- stage4 调用 `run_stage4(...)` 处（line ~768）加 `cover=cover_entry`。

- [ ] **Step 3: 手动冒烟**

hyperframes run 启用封面 → `runs/<id>/assets/cover_image.png`、`cover_audio.mp3` 存在；`timeline.json` 首个 entry `is_cover:true`；预览/成片开头是封面。

- [ ] **Step 4: Commit**

```bash
git add backend/app/pipeline/cover.py backend/app/pipeline/runner.py
git commit -m "feat(cover): stage3 备封面素材+stage4 注入封面 entry"
```

---

## Phase 5 — API（上传 + 重跑点注入 + 预览覆盖）

### Task 9: 封面图上传/回显接口

**Files:**
- Modify: `backend/app/api/settings.py`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: 后端上传 + GET**

`settings.py` 加（参照 `app/api/pipeline.py` 的 `import_article_file` 文件上传范式）：

```python
from fastapi import UploadFile, File
from fastapi.responses import FileResponse
from pathlib import Path
import shutil

_COVER_DIR = Path(__file__).resolve().parents[3] / "data" / "cover"

@router.post("/cover-image")
async def upload_cover_image(file: UploadFile = File(...)):
    _COVER_DIR.mkdir(parents=True, exist_ok=True)
    ext = (Path(file.filename or "").suffix or ".png").lower()
    dst = _COVER_DIR / f"cover{ext}"
    # 清掉旧的其它扩展名，避免残留
    for old in _COVER_DIR.glob("cover.*"):
        old.unlink(missing_ok=True)
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"path": f"data/cover/{dst.name}"}

@router.get("/cover-image")
def get_cover_image():
    files = sorted(_COVER_DIR.glob("cover.*")) if _COVER_DIR.is_dir() else []
    if not files:
        raise HTTPException(status_code=404, detail="no cover image")
    return FileResponse(files[0])
```

- [ ] **Step 2: 前端 client**

`client.ts` 的 settings 段加：

```ts
    coverImageUrl: () => `${BASE}/settings/cover-image`,
    uploadCoverImage: (file: File) => {
      const fd = new FormData(); fd.append("file", file);
      return fetch(`${BASE}/settings/cover-image`, { method: "POST", body: fd }).then(r => r.json() as Promise<{ path: string }>);
    },
```

- [ ] **Step 3: 手动冒烟 + Commit**

curl 上传一张图 → `data/cover/cover.png` 存在、GET 能取回。

```bash
git add backend/app/api/settings.py frontend/src/api/client.ts
git commit -m "feat(cover): 封面图上传/回显接口"
```

---

### Task 10: 所有"重跑 run_stage4"入口注入封面

**Files:**
- Modify: `backend/app/api/pipeline.py`（`get_preview_html`、`regen_scene_audio`；`regen_script→_regen_bg` 走 runner 已覆盖）

现有反推 scene_assets 重跑 run_stage4 的两处会丢封面。统一：反推时过滤 `is_cover`，重跑时重新注入。

- [ ] **Step 1: `get_preview_html` 注入封面 + 接收封面覆盖 query**

在 `get_preview_html`（line ~830）：
- query 新增 `cover_title`/`cover_subtitle`/`cover_font_size`（`str|int|None`）。
- 反推 scene_assets 时 `for e in timeline.get("entries", []) if not e.get("is_cover")`。
- 重跑 `run_stage4(...)` 传 `cover=`：从落盘 timeline 取原封面 entry（`next(e for e in entries if e.get("is_cover"))`），用 query 覆盖 `title`/`subtitle`/`cover_font_size`（其余如 audio/image/时长沿用落盘值；无则不加封面）。

```python
        cover_entry = next((e for e in timeline.get("entries", []) if e.get("is_cover")), None)
        if cover_entry is not None:
            cover_entry = dict(cover_entry)
            if cover_title is not None: cover_entry["title"] = cover_title
            if cover_subtitle is not None: cover_entry["subtitle"] = cover_subtitle
            if cover_font_size is not None: cover_entry["cover_font_size"] = cover_font_size
        new_timeline = run_stage4(script, scene_assets, ..., cover=cover_entry)
```

- [ ] **Step 2: `regen_scene_audio` 注入封面**

在 `regen_scene_audio`（line ~555 重建 timeline 处）：反推 scene_assets 同样 `if not e.get("is_cover")`，重跑时 `cover=next((e for e in timeline["entries"] if e.get("is_cover")), None)`。

- [ ] **Step 3: 手动冒烟**

- 启用封面的 run，预览页改字号/字幕配置点重新生成 → 封面仍在。
- 改某条新闻旁白重生音频 → 封面仍在、时间轴对。

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/pipeline.py
git commit -m "fix(cover): preview-html/regen-audio 重跑 stage4 时保留并注入封面"
```

---

## Phase 6 — 前端 UI

### Task 11: 类型 + 设置页「视频封面」section

**Files:**
- Modify: `frontend/src/types/index.ts`（`AppSettings.cover`）
- Modify: `frontend/src/pages/Settings.tsx`（默认值 + section）

- [ ] **Step 1: 类型**

`types/index.ts` 的 `AppSettings` 加：

```ts
  cover: { enabled: boolean; image: string; title_template: string; subtitle: string; narration: string; font_size: number };
```

- [ ] **Step 2: 默认值 + section**

`Settings.tsx`：① `DEFAULT_SETTINGS` 加 `cover: { enabled: false, image: "", title_template: "{period}AI资讯", subtitle: "", narration: "", font_size: 72 }`。② 在「画面标题」`<Section>` 之后加「视频封面」Section（参照画面标题 section 的 Field 写法）：开关、封面图上传（`api.settings.uploadCoverImage` → `patch("cover",{image:path})`，缩略用 `api.settings.coverImageUrl()`）、标题模板输入、副标题输入、旁白多行、字号滑块。section `desc`：「封面统一用 hyperframes 渲染；comfyui 视频路线会把封面片段自动拼接到成片开头。纯音频路线不出封面。」

- [ ] **Step 3: 验证**

Run: `cd frontend && npx tsc --noEmit`
Expected: 通过

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/pages/Settings.tsx
git commit -m "feat(cover): 设置页视频封面 section"
```

---

### Task 12: 预览页封面 per-run 覆盖

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`（S4 预览设置区）
- Modify: `frontend/src/api/client.ts`（`previewHtmlUrl` 带 cover query）

- [ ] **Step 1: previewUrl 带封面覆盖参数**

Dashboard 的 `applied` 快照与 previewUrl 拼接（复用现有 per-run 覆盖机制）加 `cover_title`/`cover_subtitle`/`cover_font_size`。预览设置区加「封面」子项（标题/副标题输入 + 字号滑块），状态纳入 `applied`/`isDirty`，「重新生成」时带进 query。

> per-run 封面图覆盖（上传到 run 目录）作为本任务**可选延伸**：MVP 先支持文字/字号覆盖；图片覆盖留作后续（spec 已列）。

- [ ] **Step 2: 验证 + 手动冒烟**

Run: `cd frontend && npx tsc --noEmit`（通过）。预览页改封面标题/字号 → 重新生成 → 预览封面实时变，不写全局。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/api/client.ts
git commit -m "feat(cover): 预览页封面 per-run 覆盖（标题/副标题/字号）"
```

---

## 收尾

- [ ] 全量回归：`cd backend && pytest` 全绿；`cd frontend && npx tsc --noEmit` 通过、`npx eslint src/pages/Dashboard.tsx src/pages/Settings.tsx` 无新增。
- [ ] 端到端手动冒烟（用户自跑后端，三选）：
  - hyperframes run 启用封面 → 预览/成片开头有封面（图+居中标题/副标题+旁白），字幕带偏移。
  - comfyui run 启用封面 → 封面片段拼到成片开头。
  - 纯音频 run → 无封面、不受影响。
  - 预览页临时改封面标题/字号 → 实时变、不污染全局；改新闻旁白重生 → 封面仍在。
- [ ] 更新 `CLAUDE.md` 的 Configuration 段（提一句 `config.yaml` 新增 `cover` 封面段）。

## 风险备忘
- `subtitle_lines` 的 start/end 是相对场景还是绝对——Task 4 Step 3 必须先读代码确认，决定偏移是否要移 lines。
- `render_cover_clip` 的 npx 调用要复用 `compose()` 现有方式；FFmpeg 兜底为次选路径。
- comfyui 拼接重编码要统一分辨率/帧率，否则 concat 报错。
