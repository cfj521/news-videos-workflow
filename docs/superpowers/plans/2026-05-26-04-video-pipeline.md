# Plan 4: Stage 4+5 Video Pipeline — 时间轴对齐、Hyperframes 合成

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Stage 4（时间轴校验对齐）和 Stage 5（Hyperframes HTML→MP4 视频合成），从素材资产到最终视频文件。

**Architecture:** Stage 4 对齐音频时长和图片展示时长生成 Timeline JSON。Stage 5 用 Jinja2 模板生成 Hyperframes HTML，然后调用 `npx hyperframes render` 输出 MP4。

**Tech Stack:** Jinja2, mutagen (音频时长检测), Node.js + Hyperframes CLI, FFmpeg

**前置依赖:** Plan 1 + Plan 2 + Plan 3 已完成

---

### Task 1: 音频时长检测工具

**Files:**
- Create: `backend/app/services/audio_utils.py`
- Test: `backend/tests/test_audio_utils.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_audio_utils.py
import pytest
from app.services.audio_utils import get_audio_duration_ms


def test_get_duration_from_valid_mp3(tmp_path):
    # 创建一个最小的有效 MP3 文件（静音帧）
    # 实际项目中会用 edge-tts 生成的真实文件测试
    # 这里测试文件不存在时的 fallback
    duration = get_audio_duration_ms(str(tmp_path / "nonexistent.mp3"))
    assert duration == 0


def test_get_duration_fallback():
    duration = get_audio_duration_ms("/no/such/file.mp3")
    assert duration == 0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_audio_utils.py -v`
Expected: FAIL

- [ ] **Step 3: 实现音频工具**

```python
# backend/app/services/audio_utils.py
from pathlib import Path


def get_audio_duration_ms(file_path: str) -> int:
    if not Path(file_path).exists():
        return 0
    try:
        from mutagen.mp3 import MP3
        audio = MP3(file_path)
        return int(audio.info.length * 1000)
    except Exception:
        return 0
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_audio_utils.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/audio_utils.py backend/tests/test_audio_utils.py
git commit -m "feat: add audio duration detection utility"
```

---

### Task 2: Stage 4 — 时间轴生成

**Files:**
- Create: `backend/app/pipeline/stage4_timeline.py`
- Test: `backend/tests/test_stage4.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_stage4.py
import pytest
from app.pipeline.stage4_timeline import run_stage4, generate_srt


def test_stage4_generates_timeline():
    scene_assets = [
        {
            "scene_id": 1,
            "image": {"file_path": "assets/scene_01_image.png"},
            "audio": {"file_path": "assets/scene_01_audio.mp3", "duration_ms": 5000},
        },
        {
            "scene_id": 2,
            "image": {"file_path": "assets/scene_02_image.png"},
            "audio": {"file_path": "assets/scene_02_audio.mp3", "duration_ms": 7000},
        },
    ]

    script = {
        "scenes": [
            {"id": 1, "narration": "第一段旁白", "duration_hint": 5},
            {"id": 2, "narration": "第二段旁白", "duration_hint": 5},
        ],
    }

    timeline = run_stage4(script=script, scene_assets=scene_assets)

    assert timeline["total_duration_ms"] == 12000  # 5000 + 7000
    assert len(timeline["entries"]) == 2
    assert timeline["entries"][0]["start_ms"] == 0
    assert timeline["entries"][0]["end_ms"] == 5000
    assert timeline["entries"][1]["start_ms"] == 5000
    assert timeline["entries"][1]["end_ms"] == 12000


def test_stage4_uses_audio_duration_over_hint():
    scene_assets = [
        {
            "scene_id": 1,
            "image": {"file_path": "img.png"},
            "audio": {"file_path": "audio.mp3", "duration_ms": 8000},
        },
    ]
    script = {"scenes": [{"id": 1, "narration": "Text", "duration_hint": 5}]}

    timeline = run_stage4(script=script, scene_assets=scene_assets)

    assert timeline["entries"][0]["end_ms"] == 8000  # audio 时长优先


def test_stage4_skips_errored_scenes():
    scene_assets = [
        {"scene_id": 1, "image": {"file_path": "img.png"},
         "audio": {"file_path": "a.mp3", "duration_ms": 5000}},
        {"scene_id": 2, "error": "generation failed"},
    ]
    script = {
        "scenes": [
            {"id": 1, "narration": "OK", "duration_hint": 5},
            {"id": 2, "narration": "Failed", "duration_hint": 5},
        ],
    }

    timeline = run_stage4(script=script, scene_assets=scene_assets)
    assert len(timeline["entries"]) == 1
    assert timeline["total_duration_ms"] == 5000


def test_generate_srt():
    timeline = {
        "entries": [
            {"scene_id": 1, "start_ms": 0, "end_ms": 5000, "subtitle_text": "第一段"},
            {"scene_id": 2, "start_ms": 5000, "end_ms": 10000, "subtitle_text": "第二段"},
        ],
    }
    srt = generate_srt(timeline)
    assert "1\n00:00:00,000 --> 00:00:05,000\n第一段" in srt
    assert "2\n00:00:05,000 --> 00:00:10,000\n第二段" in srt
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_stage4.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 Stage 4**

```python
# backend/app/pipeline/stage4_timeline.py

def run_stage4(
    script: dict,
    scene_assets: list[dict],
    min_scene_ms: int = 2000,
    max_scene_ms: int = 15000,
) -> dict:
    narration_map = {s["id"]: s for s in script["scenes"]}
    entries: list[dict] = []
    current_ms = 0

    for asset in scene_assets:
        if "error" in asset and not asset.get("audio"):
            continue

        scene_id = asset["scene_id"]
        scene_data = narration_map.get(scene_id, {})

        audio_duration = 0
        if asset.get("audio"):
            audio_duration = asset["audio"].get("duration_ms", 0)

        hint_ms = int(scene_data.get("duration_hint", 5) * 1000)
        duration_ms = audio_duration if audio_duration > 0 else hint_ms
        duration_ms = max(min_scene_ms, min(duration_ms, max_scene_ms))

        entry = {
            "scene_id": scene_id,
            "start_ms": current_ms,
            "end_ms": current_ms + duration_ms,
            "image_path": asset.get("image", {}).get("file_path", ""),
            "audio_path": asset.get("audio", {}).get("file_path", ""),
            "audio_duration_ms": audio_duration,
            "subtitle_text": scene_data.get("narration", ""),
        }
        entries.append(entry)
        current_ms += duration_ms

    return {
        "entries": entries,
        "total_duration_ms": current_ms,
    }


def generate_srt(timeline: dict) -> str:
    lines: list[str] = []
    for i, entry in enumerate(timeline["entries"], 1):
        start = _ms_to_srt_time(entry["start_ms"])
        end = _ms_to_srt_time(entry["end_ms"])
        text = entry.get("subtitle_text", "")
        if text:
            lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _ms_to_srt_time(ms: int) -> str:
    hours = ms // 3_600_000
    minutes = (ms % 3_600_000) // 60_000
    seconds = (ms % 60_000) // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_stage4.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/stage4_timeline.py backend/tests/test_stage4.py
git commit -m "feat: add Stage 4 - timeline generation and SRT subtitle output"
```

---

### Task 3: Hyperframes HTML 模板

**Files:**
- Create: `backend/app/providers/composer/templates/composition.html.j2`
- Test: `backend/tests/test_hyperframes_template.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_hyperframes_template.py
import pytest
from app.providers.composer.hyperframes_composer import HyperframesComposer


def test_render_html_template():
    composer = HyperframesComposer()
    timeline = {
        "entries": [
            {
                "scene_id": 1,
                "start_ms": 0,
                "end_ms": 5000,
                "image_path": "assets/scene_01_image.png",
                "audio_path": "assets/scene_01_audio.mp3",
                "audio_duration_ms": 5000,
                "subtitle_text": "第一段旁白文本",
            },
            {
                "scene_id": 2,
                "start_ms": 5000,
                "end_ms": 11000,
                "image_path": "assets/scene_02_image.png",
                "audio_path": "assets/scene_02_audio.mp3",
                "audio_duration_ms": 6000,
                "subtitle_text": "第二段旁白文本",
            },
        ],
        "total_duration_ms": 11000,
    }

    html = composer._render_html(timeline, resolution="1080x1920")

    assert 'data-composition-id="main"' in html
    assert 'data-width="1080"' in html
    assert 'data-height="1920"' in html
    assert 'data-duration="11"' in html
    assert 'id="s1"' in html
    assert 'id="s2"' in html
    assert "scene_01_image.png" in html
    assert "scene_01_audio.mp3" in html
    assert "第一段旁白文本" in html
    assert "gsap.timeline" in html or "window.__timelines" in html
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_hyperframes_template.py -v`
Expected: FAIL

- [ ] **Step 3: 创建 HTML 模板**

```html
{# backend/app/providers/composer/templates/composition.html.j2 #}
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { background: #000; overflow: hidden; }
    .scene { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }
    .scene img { width: 100%; height: 100%; object-fit: cover; }
    .subtitle {
      position: absolute; bottom: 80px; left: 50%; transform: translateX(-50%);
      font-size: 36px; color: white; text-align: center; max-width: 80%;
      text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      visibility: hidden;
    }
  </style>
</head>
<body>
  <div id="main"
       data-composition-id="main"
       data-width="{{ width }}"
       data-height="{{ height }}"
       data-start="0"
       data-duration="{{ total_duration_s }}">

    {% for entry in entries %}
    <div class="scene clip" id="s{{ entry.scene_id }}"
         data-start="{{ entry.start_s }}"
         data-duration="{{ entry.duration_s }}"
         data-track-index="0"
         {% if not loop.first %}style="visibility:hidden;"{% endif %}>
      <div class="scene-content">
        <img src="{{ entry.image_path }}" alt="scene {{ entry.scene_id }}">
        {% if entry.subtitle_text %}
        <div class="subtitle" id="sub{{ entry.scene_id }}">{{ entry.subtitle_text }}</div>
        {% endif %}
      </div>
    </div>
    {% endfor %}

    {% for entry in entries %}
    <audio id="narration-{{ entry.scene_id }}"
           data-start="{{ entry.start_s }}"
           data-duration="{{ entry.audio_duration_s }}"
           data-track-index="1"
           data-volume="1.0"
           src="{{ entry.audio_path }}"></audio>
    {% endfor %}
  </div>

  <script>
    const tl = gsap.timeline();

    {% for entry in entries %}
    // Scene {{ entry.scene_id }}
    {% if not loop.first %}
    tl.set("#s{{ entry.scene_id }}", { autoAlpha: 1 }, {{ entry.start_s }});
    {% endif %}
    {% if not loop.first %}
    tl.set("#s{{ entries[loop.index0 - 1].scene_id }}", { autoAlpha: 0 }, {{ entry.start_s }});
    {% endif %}

    // Ken Burns
    tl.from("#s{{ entry.scene_id }} img", {
      scale: 1.06, duration: {{ entry.duration_s }}, ease: "sine.inOut"
    }, {{ entry.start_s }});

    {% if entry.subtitle_text %}
    // Subtitle
    tl.set("#sub{{ entry.scene_id }}", { autoAlpha: 1 }, {{ entry.start_s + 0.3 }});
    tl.set("#sub{{ entry.scene_id }}", { autoAlpha: 0 }, {{ entry.end_s - 0.2 }});
    tl.from("#sub{{ entry.scene_id }}", {
      y: 20, autoAlpha: 0, duration: 0.4, ease: "power3.out"
    }, {{ entry.start_s + 0.3 }});
    {% endif %}

    {% endfor %}

    window.__timelines = { main: tl };
  </script>
</body>
</html>
```

- [ ] **Step 4: 实现 HyperframesComposer（模板渲染部分）**

```python
# backend/app/providers/composer/hyperframes_composer.py
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.providers.base import ComposerProvider, VideoResult


TEMPLATE_DIR = Path(__file__).parent / "templates"


class HyperframesComposer(ComposerProvider):
    async def compose(
        self,
        timeline_json: dict,
        assets_dir: str,
        output_path: str,
        resolution: str = "1080x1920",
    ) -> VideoResult:
        html = self._render_html(timeline_json, resolution)

        project_dir = Path(assets_dir).parent / "hyperframes_project"
        project_dir.mkdir(parents=True, exist_ok=True)
        index_html = project_dir / "index.html"
        index_html.write_text(html, encoding="utf-8")

        self._symlink_assets(assets_dir, project_dir)

        result = subprocess.run(
            ["npx", "hyperframes", "render", "--output", output_path, "--fps", "30", "--quality", "standard"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Hyperframes render failed: {result.stderr}")

        thumbnail_path = output_path.replace(".mp4", "_thumb.jpg")
        self._extract_thumbnail(output_path, thumbnail_path)

        return VideoResult(
            file_path=output_path,
            thumbnail_path=thumbnail_path if Path(thumbnail_path).exists() else None,
            duration_ms=timeline_json.get("total_duration_ms", 0),
            resolution=resolution,
        )

    def _render_html(self, timeline: dict, resolution: str) -> str:
        parts = resolution.split("x")
        width, height = int(parts[0]), int(parts[1])
        total_ms = timeline["total_duration_ms"]
        total_s = total_ms / 1000

        entries = []
        for entry in timeline["entries"]:
            entries.append({
                "scene_id": entry["scene_id"],
                "start_s": round(entry["start_ms"] / 1000, 3),
                "end_s": round(entry["end_ms"] / 1000, 3),
                "duration_s": round((entry["end_ms"] - entry["start_ms"]) / 1000, 3),
                "image_path": entry["image_path"],
                "audio_path": entry["audio_path"],
                "audio_duration_s": round(entry.get("audio_duration_ms", 0) / 1000, 3),
                "subtitle_text": entry.get("subtitle_text", ""),
            })

        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        template = env.get_template("composition.html.j2")
        return template.render(
            width=width,
            height=height,
            total_duration_s=round(total_s, 3),
            entries=entries,
        )

    def _symlink_assets(self, assets_dir: str, project_dir: Path) -> None:
        assets_link = project_dir / "assets"
        if not assets_link.exists():
            assets_src = Path(assets_dir).resolve()
            try:
                assets_link.symlink_to(assets_src)
            except OSError:
                import shutil
                shutil.copytree(str(assets_src), str(assets_link))

    def _extract_thumbnail(self, video_path: str, thumb_path: str) -> None:
        try:
            subprocess.run(
                ["ffmpeg", "-i", video_path, "-ss", "1", "-vframes", "1",
                 "-q:v", "2", thumb_path, "-y"],
                capture_output=True, timeout=30,
            )
        except Exception:
            pass
```

- [ ] **Step 5: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_hyperframes_template.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/providers/composer/ backend/tests/test_hyperframes_template.py
git commit -m "feat: add Hyperframes composer with HTML template rendering"
```

---

### Task 4: Stage 5 Pipeline 入口

**Files:**
- Create: `backend/app/pipeline/stage5_compose.py`
- Test: `backend/tests/test_stage5.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_stage5.py
import pytest
from unittest.mock import AsyncMock
from app.pipeline.stage5_compose import run_stage5
from app.providers.base import VideoResult


@pytest.mark.asyncio
async def test_stage5_calls_composer():
    mock_composer = AsyncMock()
    mock_composer.compose.return_value = VideoResult(
        file_path="output.mp4",
        thumbnail_path="thumb.jpg",
        duration_ms=11000,
        resolution="1080x1920",
    )

    timeline = {
        "entries": [
            {"scene_id": 1, "start_ms": 0, "end_ms": 5000,
             "image_path": "img.png", "audio_path": "audio.mp3",
             "audio_duration_ms": 5000, "subtitle_text": "Text"},
        ],
        "total_duration_ms": 5000,
    }

    result = await run_stage5(
        timeline=timeline,
        composer=mock_composer,
        assets_dir="/tmp/assets",
        output_path="/tmp/output.mp4",
    )

    assert result.file_path == "output.mp4"
    mock_composer.compose.assert_called_once()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_stage5.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 Stage 5**

```python
# backend/app/pipeline/stage5_compose.py
from app.providers.base import ComposerProvider, VideoResult


async def run_stage5(
    timeline: dict,
    composer: ComposerProvider,
    assets_dir: str,
    output_path: str,
    resolution: str = "1080x1920",
) -> VideoResult:
    return await composer.compose(
        timeline_json=timeline,
        assets_dir=assets_dir,
        output_path=output_path,
        resolution=resolution,
    )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_stage5.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/stage5_compose.py backend/tests/test_stage5.py
git commit -m "feat: add Stage 5 - video composition pipeline entry"
```

---

## Plan 4 完成检查

- ✅ 音频时长检测工具
- ✅ Stage 4 时间轴生成 + SRT 字幕输出
- ✅ Hyperframes HTML 模板（Ken Burns + 字幕 + 音轨）
- ✅ HyperframesComposer（模板渲染 + CLI 调用 + 封面提取）
- ✅ Stage 5 pipeline 入口
