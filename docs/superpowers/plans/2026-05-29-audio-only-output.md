# 纯语音成品模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `video_route="audio"` 纯语音成品模式：跳过图片/视频/预览，产出合并 MP3；阶段更名；发布平台按媒体类型分类并新增 4 个语音平台。

**Architecture:** 复用 `PipelineRun.video_route`（新增取值 `"audio"`）。后端 S3 增 `audio_only` 跳过图片，runner 在 audio 路线跳过 S4、S5 改为 ffmpeg 合并逐条音频为 `output.mp3`；产物端点按扩展名返回正确 content-type。前端把"视频路线"改"音视频路线"+纯语音选项，按模式隐藏图片/预览元素、改阶段名、过滤发布平台。

**Tech Stack:** Python (FastAPI), ffmpeg (subprocess), React + TypeScript (Vite), pytest, SWR。

---

## 文件结构

后端：
- `backend/app/pipeline/stage3_assets.py` — `run_stage3` 加 `audio_only`
- `backend/app/pipeline/runner.py` — `_ffmpeg_merge_audio` 新 helper；`_run_inner` audio 路线分支
- `backend/app/api/pipeline.py` — `_output_media_meta` helper + `get_video` 按扩展名；`_render_video_async` audio 分支
- `backend/app/providers/publisher/{ximalaya,xiaoyuzhou,netease_music,apple_podcasts}.py` — 4 个占位适配器
- `backend/tests/test_stage3_audio_only.py`、`test_audio_merge.py`、`test_output_media_meta.py`、`test_audio_publishers.py`

前端：
- `frontend/src/types/index.ts` — `video_route` 加 audio、`STAGE_LABELS[5]`、平台目录、`PLATFORM_MEDIA`
- `frontend/src/components/CreateRunDialog.tsx` — 音视频路线 + 纯语音联动 + 发布平台过滤
- `frontend/src/pages/Dashboard.tsx` — Stepper/标签/面板按模式调整
- `frontend/src/pages/Publishers.tsx` — 媒体徽标 + 新平台配置字段

---

## Task 1: `run_stage3` 增加 audio_only（跳过图片）

**Files:**
- Modify: `backend/app/pipeline/stage3_assets.py`
- Test: `backend/tests/test_stage3_audio_only.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_stage3_audio_only.py
import asyncio
from app.pipeline.stage3_assets import run_stage3


class _FakeImg:
    def __init__(self): self.calls = 0
    async def generate(self, prompt, size="1080x1920", output_path=""):
        self.calls += 1
        raise AssertionError("image generate must not be called in audio_only")


class _FakeTTS:
    def __init__(self): self.calls = 0
    async def synthesize(self, text, voice="", speed=1.0, output_path=""):
        self.calls += 1
        class R: file_path = output_path; duration_ms = 1000
        return R()


def test_audio_only_skips_image(tmp_path):
    script = {"scenes": [{"id": 1, "narration": "你好", "image_prompt": "x"},
                          {"id": 2, "narration": "世界", "image_prompt": "y"}]}
    img, tts = _FakeImg(), _FakeTTS()
    assets = asyncio.run(run_stage3(script, img, tts, str(tmp_path), audio_only=True))
    assert img.calls == 0
    assert tts.calls == 2
    assert all("image" not in a for a in assets)
    assert all(a.get("audio") for a in assets)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_stage3_audio_only.py -q`
Expected: FAIL（`run_stage3` 不接受 `audio_only` 关键字 → TypeError）

- [ ] **Step 3: 实现**

`run_stage3` 签名加 `audio_only: bool = False`，把图片块包进 `if not audio_only:`：

```python
async def run_stage3(
    script: dict,
    image_provider: ImageProvider,
    tts_provider: TTSProvider,
    assets_dir: str,
    resolution: str = "1080x1920",
    video_route: str = "hyperframes",
    audio_only: bool = False,
) -> list[dict]:
    Path(assets_dir).mkdir(parents=True, exist_ok=True)
    scenes = script["scenes"]
    total = len(scenes)
    log.info("Generating assets for %d scenes (resolution=%s, audio_only=%s)", total, resolution, audio_only)
    scene_assets: list[dict] = []

    for i, scene in enumerate(scenes, 1):
        scene_id = scene["id"]
        entry: dict = {"scene_id": scene_id}

        if not audio_only:
            try:
                image_path = str(Path(assets_dir) / f"scene_{scene_id:02d}_image.png")
                log.info("[%d/%d] Image S%d: %s", i, total, scene_id, scene["image_prompt"][:60])
                image_result = await image_provider.generate(prompt=scene["image_prompt"], size=resolution, output_path=image_path)
                entry["image"] = {"file_path": image_result.file_path, "duration_ms": image_result.duration_ms}
            except Exception:
                log.exception("[%d/%d] Image S%d FAILED", i, total, scene_id)
                entry["error"] = "image generation failed"

        try:
            audio_path = str(Path(assets_dir) / f"scene_{scene_id:02d}_audio.mp3")
            log.info("[%d/%d] TTS S%d: %s...", i, total, scene_id, scene["narration"][:30])
            audio_result = await tts_provider.synthesize(text=scene["narration"], output_path=audio_path)
            entry["audio"] = {"file_path": audio_result.file_path, "duration_ms": audio_result.duration_ms}
        except Exception:
            log.exception("[%d/%d] TTS S%d FAILED", i, total, scene_id)
            entry.setdefault("error", "")
            entry["error"] += " tts failed"

        scene_assets.append(entry)

    ok = sum(1 for a in scene_assets if "error" not in a)
    log.info("Asset generation done: %d/%d ok", ok, total)
    return scene_assets
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_stage3_audio_only.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/stage3_assets.py backend/tests/test_stage3_audio_only.py
git commit -m "feat(stage3): audio_only 跳过图片生成"
```

---

## Task 2: `_ffmpeg_merge_audio` 合并逐条音频

**Files:**
- Modify: `backend/app/pipeline/runner.py`（新增函数，放在 `_ffmpeg_compose` 附近）
- Test: `backend/tests/test_audio_merge.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_audio_merge.py
import subprocess
from pathlib import Path
import pytest
from app.pipeline.runner import _ffmpeg_merge_audio


def _make_assets(assets_dir: Path, ids):
    assets_dir.mkdir(parents=True, exist_ok=True)
    for i in ids:
        (assets_dir / f"scene_{i:02d}_audio.mp3").write_bytes(b"x")


def test_merge_orders_by_scene_and_calls_ffmpeg(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    _make_assets(assets, [1, 2, 3])
    script = {"scenes": [{"id": 2}, {"id": 1}, {"id": 3}]}  # 顺序按 script

    calls = {}
    def fake_run(args, **kw):
        calls["args"] = args
        # 模拟 ffmpeg 产出
        Path(args[args.index("-i") + 2] if False else (tmp_path / "output.mp3")).write_bytes(b"merged")
        class R: returncode = 0
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)

    out = _ffmpeg_merge_audio(script, assets, tmp_path)
    assert out.endswith("output.mp3")
    # concat 列表顺序应为 scene 2,1,3
    list_txt = (tmp_path / "audio_concat.txt").read_text(encoding="utf-8")
    assert list_txt.index("scene_02") < list_txt.index("scene_01") < list_txt.index("scene_03")


def test_merge_no_audio_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        _ffmpeg_merge_audio({"scenes": [{"id": 1}]}, tmp_path / "assets", tmp_path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_audio_merge.py -q`
Expected: FAIL（`_ffmpeg_merge_audio` 不存在 → ImportError）

- [ ] **Step 3: 实现**

在 `backend/app/pipeline/runner.py` 增加（`_ffmpeg_compose` 函数之后）：

```python
def _ffmpeg_merge_audio(script: dict, assets_dir, run_dir) -> str:
    """按 script 分镜顺序合并逐条音频为单个 MP3。"""
    import subprocess
    from pathlib import Path

    assets_dir = Path(assets_dir)
    run_dir = Path(run_dir)
    output_path = str((run_dir / "output.mp3").resolve())

    paths = []
    for scene in script.get("scenes", []):
        p = assets_dir / f"scene_{scene['id']:02d}_audio.mp3"
        if p.exists():
            paths.append(p.resolve())

    if not paths:
        raise RuntimeError("No audio to merge")

    list_file = run_dir / "audio_concat.txt"
    list_file.write_text("".join(f"file '{p.as_posix()}'\n" for p in paths), encoding="utf-8")

    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c:a", "libmp3lame", "-q:a", "2", output_path],
        check=True, capture_output=True,
    )
    get_logger("runner").info("Merged %d audio clips → %s", len(paths), output_path)
    return output_path
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_audio_merge.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/runner.py backend/tests/test_audio_merge.py
git commit -m "feat(runner): _ffmpeg_merge_audio 按分镜顺序合并 MP3"
```

---

## Task 3: runner audio 路线编排（S3 audio_only / 跳过 S4 / S5 合并）

**Files:**
- Modify: `backend/app/pipeline/runner.py`（`_run_inner` 的 S3、S4、S5 块）

> 说明：`_run_inner` 是大型异步函数，依赖 DB/provider/文件系统，本仓库既有测试未对其做集成测试。本任务的正确性由 Task 1/2 的单元测试 + 浏览器实测覆盖；本任务只做接线，无新单测。

- [ ] **Step 1: S3 块传入 audio_only**

在 S3 块（`if 3 in selected:`）内，构造 `scene_assets = await run_stage3(...)` 处加 `audio_only`：

```python
        audio_only = run.video_route == "audio"
        scene_assets = await run_stage3(
            script=script,
            image_provider=TrackedImageProvider(image_provider),
            tts_provider=TrackedTTSProvider(tts_provider),
            assets_dir=str(assets_dir),
            resolution=cfg.video.resolution,
            audio_only=audio_only,
        )
```

（图片相关 `img_count` 进度在 audio_only 下不会触发，因为 `TrackedImageProvider.generate` 不会被调用——无需额外改动。）

- [ ] **Step 2: S4 块在 audio 路线整体跳过**

把 `if 4 in selected:` 改为：

```python
    # ─── Stage 4: 预览 ────────────────────────────────────
    if 4 in selected and run.video_route != "audio":
```

- [ ] **Step 3: S5 块在 audio 路线改为音频合并**

在 `if 5 in selected:` 内、`output_mp4 = ...` 之前插入 audio 分支并在其后 `return`/跳过视频逻辑。把 S5 开头改为：

```python
    # ─── Stage 5: 合成渲染 ────────────────────────────────
    if 5 in selected:
        t0 = time.time()

        if run.video_route == "audio":
            _update(db, run, current_stage=5, progress_detail="S5 合成音频中...")
            log.info("[S5] Merging audio — %d scenes", len(script.get("scenes", [])))
            try:
                final_path = _ffmpeg_merge_audio(script, assets_dir, run_dir)
            except Exception as e:
                _update(db, run, status="failed", error_message=f"音频合成失败: {e}", finished_at=datetime.now(timezone.utc))
                log.exception("[S5] Audio merge failed")
                return
            if Path(final_path).exists():
                size_mb = Path(final_path).stat().st_size / 1024 / 1024
                _update(db, run, progress_detail=f"S5 合成完成 — {size_mb:.1f} MB ({time.time()-t0:.1f}s)", output_path=final_path)
                log.info("[S5] Audio merged — %.1f MB", size_mb)
            else:
                _update(db, run, status="failed", error_message="音频文件未生成", finished_at=datetime.now(timezone.utc))
                return
            if run.mode == "manual":
                _update(db, run, status="review", progress_detail="S5 合成完成，等待审核")
                await _wait_for_resume(run_id, db)
                run = db.get(PipelineRun, run_id)
        else:
            if not timeline:
                _update(db, run, status="failed", error_message="No timeline for rendering", finished_at=datetime.now(timezone.utc))
                log.error("No timeline — cannot render")
                return
            output_mp4 = str((run_dir / "output.mp4").resolve())
            # ...（保留原有视频合成逻辑，整体缩进进 else 分支）...
```

> 注意：原 S5 块从 `output_mp4 = ...` 到 manual review 的全部视频逻辑移入 `else:` 分支（保持原样，仅整体多一级缩进）。`t0 = time.time()` 提到分支判断之前（如上）。

- [ ] **Step 4: 验证后端无语法错误 + 全量测试**

Run: `python -m pytest -q`
Expected: 既有用例 + 新增 Task1/2 用例全部 PASS（无回归）

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/runner.py
git commit -m "feat(runner): audio 路线 — S3 仅语音、跳过 S4、S5 合并 MP3"
```

---

## Task 4: 产物端点按扩展名 + 重合成 audio 分支

**Files:**
- Modify: `backend/app/api/pipeline.py`（新增 `_output_media_meta`、改 `get_video`、`_render_video_async` 加 audio 分支）
- Test: `backend/tests/test_output_media_meta.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_output_media_meta.py
from pathlib import Path
from app.api.pipeline import _output_media_meta


def test_mp3_meta():
    assert _output_media_meta(Path("/x/output.mp3")) == ("audio/mpeg", "mp3")


def test_mp4_meta():
    assert _output_media_meta(Path("/x/output.mp4")) == ("video/mp4", "mp4")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_output_media_meta.py -q`
Expected: FAIL（`_output_media_meta` 不存在）

- [ ] **Step 3: 实现 helper + 改 get_video**

在 `backend/app/api/pipeline.py` 增加 helper（靠近 `get_video`）：

```python
def _output_media_meta(path: Path) -> tuple[str, str]:
    if path.suffix.lower() == ".mp3":
        return "audio/mpeg", "mp3"
    return "video/mp4", "mp4"
```

改 `get_video` 末行：

```python
@router.get("/runs/{run_id}/video")
def get_video(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run or not run.output_path:
        raise HTTPException(status_code=404, detail="Output not available")
    path = Path(run.output_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")
    media_type, ext = _output_media_meta(path)
    return FileResponse(path, media_type=media_type, filename=f"run_{run_id}.{ext}")
```

- [ ] **Step 4: `_render_video_async` 加 audio 分支**

在 `_render_video_async` 内、`timeline = json.loads(...)` 之前插入 audio 早返回分支：

```python
        cfg = get_settings()
        rd = _run_dir(run_id)

        if run.video_route == "audio":
            from app.pipeline.runner import _ffmpeg_merge_audio
            _update(db, run, progress_detail="重新合成音频中...")
            script = json.loads((rd / "script.json").read_text(encoding="utf-8"))
            final_path = _ffmpeg_merge_audio(script, rd / "assets", rd)
            if Path(final_path).exists():
                size_mb = Path(final_path).stat().st_size / 1024 / 1024
                _update(db, run, progress_detail=f"S5 合成完成 — {size_mb:.1f} MB", output_path=final_path)
            else:
                _update(db, run, status="failed", error_message="音频文件未生成", finished_at=datetime.now(timezone.utc))
            return

        timeline = json.loads((rd / "timeline.json").read_text(encoding="utf-8"))
        output_mp4 = str((rd / "output.mp4").resolve())
        # ...（原有视频逻辑不变）...
```

- [ ] **Step 5: 跑测试 + 提交**

Run: `python -m pytest tests/test_output_media_meta.py -q`
Expected: PASS

```bash
git add backend/app/api/pipeline.py backend/tests/test_output_media_meta.py
git commit -m "feat(api): 产物按扩展名返回 + audio 重合成分支"
```

---

## Task 5: 4 个语音平台占位适配器

**Files:**
- Create: `backend/app/providers/publisher/ximalaya.py`、`xiaoyuzhou.py`、`netease_music.py`、`apple_podcasts.py`
- Test: `backend/tests/test_audio_publishers.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_audio_publishers.py
import asyncio
import pytest
from app.providers.publisher.ximalaya import XimalayaPublisher
from app.providers.publisher.xiaoyuzhou import XiaoyuzhouPublisher
from app.providers.publisher.netease_music import NeteaseMusicPublisher
from app.providers.publisher.apple_podcasts import ApplePodcastsPublisher


@pytest.mark.parametrize("cls,platform", [
    (XimalayaPublisher, "ximalaya"),
    (XiaoyuzhouPublisher, "xiaoyuzhou"),
    (NeteaseMusicPublisher, "netease_music"),
    (ApplePodcastsPublisher, "apple_podcasts"),
])
def test_audio_publisher_graceful_without_creds(cls, platform):
    pub = cls()
    res = asyncio.run(pub.publish("out.mp3", None, "标题", "简介", ["tag"]))
    assert res.platform == platform
    assert res.status == "failed"
    assert res.error_message
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_audio_publishers.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 4 个适配器**

`backend/app/providers/publisher/ximalaya.py`：

```python
from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.ximalaya")


class XimalayaPublisher(PublisherAdapter):
    """喜马拉雅（音频）。占位适配器：需开放平台凭证，暂未实现实际上传。"""

    def __init__(self, access_token: str = "", **kwargs):
        self._token = access_token

    async def publish(self, video_path, thumbnail_path, title, description, tags) -> PublishResult:
        if not self._token:
            return PublishResult(platform="ximalaya", status="failed", error_message="Missing Ximalaya access_token")
        return PublishResult(platform="ximalaya", status="failed", error_message="Ximalaya 发布暂未实现")
```

`xiaoyuzhou.py`（小宇宙，字段 `cookie`）：

```python
from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.xiaoyuzhou")


class XiaoyuzhouPublisher(PublisherAdapter):
    """小宇宙（音频/播客）。占位适配器：小宇宙无公开发布 API，需 cookie/人工。"""

    def __init__(self, cookie: str = "", **kwargs):
        self._cookie = cookie

    async def publish(self, video_path, thumbnail_path, title, description, tags) -> PublishResult:
        if not self._cookie:
            return PublishResult(platform="xiaoyuzhou", status="failed", error_message="Missing Xiaoyuzhou cookie")
        return PublishResult(platform="xiaoyuzhou", status="failed", error_message="小宇宙 发布暂未实现")
```

`netease_music.py`（网易云音乐，字段 `cookie`）：

```python
from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.netease_music")


class NeteaseMusicPublisher(PublisherAdapter):
    """网易云音乐（音频）。占位适配器：需登录态/创作者权限，暂未实现。"""

    def __init__(self, cookie: str = "", **kwargs):
        self._cookie = cookie

    async def publish(self, video_path, thumbnail_path, title, description, tags) -> PublishResult:
        if not self._cookie:
            return PublishResult(platform="netease_music", status="failed", error_message="Missing NetEase Music cookie")
        return PublishResult(platform="netease_music", status="failed", error_message="网易云音乐 发布暂未实现")
```

`apple_podcasts.py`（Apple Podcasts，字段 `rss_url`）：

```python
from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult

log = get_logger("publisher.apple_podcasts")


class ApplePodcastsPublisher(PublisherAdapter):
    """Apple Podcasts（音频）。占位适配器：Apple 走 RSS 分发，需托管 RSS，暂未实现。"""

    def __init__(self, rss_url: str = "", **kwargs):
        self._rss_url = rss_url

    async def publish(self, video_path, thumbnail_path, title, description, tags) -> PublishResult:
        if not self._rss_url:
            return PublishResult(platform="apple_podcasts", status="failed", error_message="Missing Apple Podcasts rss_url")
        return PublishResult(platform="apple_podcasts", status="failed", error_message="Apple Podcasts 发布暂未实现（需 RSS 托管）")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_audio_publishers.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/publisher/ximalaya.py backend/app/providers/publisher/xiaoyuzhou.py backend/app/providers/publisher/netease_music.py backend/app/providers/publisher/apple_podcasts.py backend/tests/test_audio_publishers.py
git commit -m "feat(publisher): 新增 4 个语音平台占位适配器"
```

---

## Task 6: 前端类型与平台目录

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: `video_route` 加 audio**

```ts
export interface PipelineRun {
  // ...
  video_route: "hyperframes" | "ltx" | "audio";
  // ...
}
```

- [ ] **Step 2: 阶段标签 S5 改名**

```ts
export const STAGE_LABELS: Record<number, string> = {
  1: "搜索整理",
  2: "脚本/图片生成",
  3: "素材生成",
  4: "预览",
  5: "合成渲染",
  6: "发布",
};
```

- [ ] **Step 3: 平台目录 + 媒体分类**

`PLATFORM_LABELS` 增加 4 个语音平台；新增 `PLATFORM_MEDIA`：

```ts
export const PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube",
  instagram: "Instagram Reels",
  bilibili: "Bilibili",
  douyin: "抖音",
  kuaishou: "快手",
  ximalaya: "喜马拉雅",
  xiaoyuzhou: "小宇宙",
  netease_music: "网易云音乐",
  apple_podcasts: "Apple Podcasts",
};

export type MediaType = "video" | "audio" | "both";

export const PLATFORM_MEDIA: Record<string, MediaType> = {
  youtube: "video",
  instagram: "video",
  bilibili: "both",
  douyin: "video",
  kuaishou: "video",
  ximalaya: "audio",
  xiaoyuzhou: "audio",
  netease_music: "audio",
  apple_podcasts: "audio",
};
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 通过（`PipelineRun.video_route` 变更不会引入错误，因为现有比较都是字符串）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types/index.ts
git commit -m "feat(types): video_route 加 audio、合成渲染改名、平台媒体分类"
```

---

## Task 7: 创建对话框 — 音视频路线 + 纯语音联动

**Files:**
- Modify: `frontend/src/components/CreateRunDialog.tsx`

- [ ] **Step 1: 路线标签与选项**

把"视频路线"块标签改"音视频路线"，加纯语音选项：

```tsx
          <div>
            <label className={labelCls}>音视频路线</label>
            <Select value={videoRoute} onChange={setVideoRoute} options={[
              { value: "hyperframes", label: "Hyperframes" },
              { value: "ltx", label: "LTX 2.3" },
              { value: "audio", label: "纯语音" },
            ]} />
          </div>
```

- [ ] **Step 2: 纯语音模式下计算可见阶段与标签**

在组件内（`return` 之前）加：

```tsx
  const audioOnly = videoRoute === "audio";
  const dialogStages = audioOnly ? VISIBLE_STAGES.filter((s) => s !== 4) : VISIBLE_STAGES;
  const stageLabel = (s: number) =>
    audioOnly && s === 2 ? "脚本/语音生成" : STAGE_LABELS[s];
```

把执行阶段 `VISIBLE_STAGES.map((s) => ...)` 改为 `dialogStages.map((s) => ...)`，并把内部 `{STAGE_LABELS[s]}` 改为 `{stageLabel(s)}`。

> `selectedVisual` 初始含 4；切换到 audio 时需把 4 去掉以免提交无效阶段。加 effect：

```tsx
  useEffect(() => {
    if (audioOnly) setSelectedVisual((prev) => {
      if (!prev.has(4)) return prev;
      const next = new Set(prev); next.delete(4); return next;
    });
  }, [audioOnly]);
```

（`useEffect` 当前文件未引入——需把首行改为 `import { useState, useEffect } from "react";`）

> 注：`VISUAL_DEPS[5] = [1,2,4]`，故 audio 模式下若用户 toggle 阶段5 会把阶段4加回 `selectedVisual`。这是无害的——runner 的 S4 块已用 `run.video_route != "audio"` 守卫跳过（Task 3 Step 2），Stepper（Task 8）也按模式过滤掉阶段4显示。无需改 `VISUAL_DEPS`。

- [ ] **Step 3: 发布平台按媒体过滤**

`PLATFORMS` 改为从 `PLATFORM_MEDIA` 派生，并在 audio 模式过滤：

```tsx
import { STAGE_LABELS, VISIBLE_STAGES } from "../types";
import { PLATFORM_LABELS, PLATFORM_MEDIA } from "../types";

// 替换原 PLATFORMS 常量：
const ALL_PLATFORMS = Object.keys(PLATFORM_MEDIA).map((k) => ({ value: k, label: PLATFORM_LABELS[k] ?? k }));
```

在组件内：

```tsx
  const platformOptions = audioOnly
    ? ALL_PLATFORMS.filter((p) => PLATFORM_MEDIA[p.value] !== "video")
    : ALL_PLATFORMS.filter((p) => PLATFORM_MEDIA[p.value] !== "audio");
```

把发布平台渲染处 `PLATFORMS.map(...)` 改为 `platformOptions.map(...)`。切换到 audio 时清掉已选的非音频平台：

```tsx
  useEffect(() => {
    setPlatforms((prev) => {
      const allowed = new Set(platformOptions.map((p) => p.value));
      const next = new Set([...prev].filter((p) => allowed.has(p)));
      return next.size === prev.size ? prev : next;
    });
  }, [audioOnly]);
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend && pnpm build`
Expected: 通过

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/CreateRunDialog.tsx
git commit -m "feat(create-run): 音视频路线 + 纯语音联动 + 发布平台按媒体过滤"
```

---

## Task 8: 任务详情 — 阶段/面板按模式调整

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Stepper 按模式过滤 S4 + 标签**

`Stepper` 内用 run.video_route 计算：

```tsx
function Stepper({ run, onSelect, activeStage }: { run: PipelineRun; onSelect: (s: number) => void; activeStage: number }) {
  const selected: number[] = (() => { try { return JSON.parse(run.selected_stages); } catch { return []; } })();
  const audioOnly = run.video_route === "audio";
  const stages = audioOnly ? VISIBLE_STAGES.filter((s) => s !== 4) : VISIBLE_STAGES;
  const labelOf = (s: number) => (audioOnly && s === 2 ? "脚本/语音生成" : STAGE_LABELS[s]);
  // ...statusOf 不变...
```

把渲染处 `VISIBLE_STAGES.map((s, i) => ...)` 改为 `stages.map((s, i) => ...)`，`{STAGE_LABELS[s]}` 改 `{labelOf(s)}`，`i < VISIBLE_STAGES.length - 1` 改 `i < stages.length - 1`。

- [ ] **Step 2: S2Panel/SceneEditor 隐藏图片元素**

`StagePanel` 传 `run` 给 S2Panel；S2Panel 传 `audioOnly` 给 SceneEditor：

```tsx
function StagePanel({ stage, runId, run }: { stage: number; runId: number; run: PipelineRun }) {
  switch (stage) {
    case 1: return <S1Panel runId={runId} />;
    case 2: return <S2Panel runId={runId} audioOnly={run.video_route === "audio"} />;
    case 4: return <S4Panel runId={runId} run={run} />;
    case 5: return <S5Panel runId={runId} run={run} />;
    case 6: return <S6Panel run={run} />;
    default: return null;
  }
}
```

`S2Panel` 签名加 `audioOnly`，把它透传给 `SceneEditor`：

```tsx
function S2Panel({ runId, audioOnly }: { runId: number; audioOnly: boolean }) {
  // ...
  // 在标题行的"图片尺寸"控件外层包条件：audio 模式不显示
  // <SceneEditor ... audioOnly={audioOnly} />
}
```

标题行图片尺寸控件包 `{!audioOnly && (<div className="flex items-center gap-2 ...">...</div>)}`。
SceneEditor 调用加 `audioOnly={audioOnly}`。

`SceneEditor` 签名加 `audioOnly?: boolean`；缩略图块与"图片提示词"块按 audio 隐藏：

```tsx
function SceneEditor({ runId, scene, durationS, mutateScript, imgSize, onDelete, canDelete, audioOnly }: {
  runId: number; scene: ScriptData["scenes"][0]; durationS: string | null; mutateScript: () => void; imgSize: string; onDelete?: () => void; canDelete?: boolean; audioOnly?: boolean;
}) {
  // ...
  // 左侧缩略图块：audio 时只渲染 audio，不渲染 <img>
  // 右侧"图片提示词"整块（含重生成提示词/重新生成图片）用 {!audioOnly && (...)} 包裹
}
```

左侧块改为：

```tsx
        <div className="w-[200px] shrink-0">
          {!audioOnly && (
            <img src={imgTs ? `${imgSrc}?t=${imgTs}` : imgSrc} className="w-full rounded-lg bg-white/[0.02]" onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0.15"; }} />
          )}
          <audio controls src={audioTs ? `${audioSrc}?t=${audioTs}` : audioSrc} className={`w-full ${audioOnly ? "" : "mt-2"}`} />
        </div>
```

右侧"图片提示词" `<div>...</div>` 整块用 `{!audioOnly && ( ... )}` 包裹。

- [ ] **Step 3: S5Panel 音频模式（试听 + 下载 MP3）**

`S5Panel` 用 `run.video_route === "audio"` 分支。把渲染按钮文案与成品展示按模式切换：

```tsx
function S5Panel({ runId, run }: { runId: number; run: PipelineRun }) {
  const [rendering, setRendering] = useState(false);
  const { showToast } = useToast();
  const audioOnly = run.video_route === "audio";
  const actionLabel = audioOnly ? "合成" : "渲染";

  const handleRender = async () => {
    setRendering(true);
    try { await api.runs.triggerRender(runId); showToast(`开始${actionLabel}...`, "success"); }
    catch { showToast(`${actionLabel}启动失败`, "error"); setRendering(false); }
  };

  if (!run.output_path) {
    const isRendering = (run.current_stage === 5 && run.status === "processing") || rendering;
    return (
      <div className={`${cardCls} p-8 text-center`}>
        {isRendering ? (
          <div>
            <div className="text-white/40 text-sm mb-1">{actionLabel}中...</div>
            {run.progress_detail && <div className="text-xs text-white/25">{run.progress_detail}</div>}
          </div>
        ) : (
          <div>
            <p className="text-white/30 text-sm mb-4">尚未{audioOnly ? "合成音频" : "渲染成片"}</p>
            <button onClick={handleRender} disabled={rendering} className={btnPrimary}>{audioOnly ? "合成音频" : "渲染成片"}</button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`${cardCls} p-5`}>
      {audioOnly ? (
        <audio controls className="w-full max-w-2xl mx-auto" src={api.runs.videoUrl(runId)} />
      ) : (
        <video controls className="w-full max-w-2xl mx-auto rounded-lg" src={api.runs.videoUrl(runId)} />
      )}
      <div className="flex justify-center gap-3 mt-4">
        <a href={api.runs.videoUrl(runId)} download className={btnPrimary}>{audioOnly ? "下载 MP3" : "下载 MP4"}</a>
        <button onClick={handleRender} disabled={rendering} className={btnCompact}>
          {rendering ? `${actionLabel}中...` : `重新${actionLabel}`}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend && pnpm build`
Expected: 通过

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "feat(dashboard): audio 模式隐藏图片/预览、合成渲染试听+下载 MP3"
```

---

## Task 9: 发布管理页 — 媒体徽标 + 新平台配置字段

**Files:**
- Modify: `frontend/src/pages/Publishers.tsx`

- [ ] **Step 1: 新平台配置字段**

`PLATFORM_FIELDS` 增加：

```tsx
  ximalaya: [
    { key: "access_token", label: "Access Token", secret: true },
  ],
  xiaoyuzhou: [
    { key: "cookie", label: "Cookie", secret: true },
  ],
  netease_music: [
    { key: "cookie", label: "Cookie", secret: true },
  ],
  apple_podcasts: [
    { key: "rss_url", label: "RSS URL", placeholder: "https://feeds.example.com/podcast.xml" },
  ],
```

- [ ] **Step 2: 媒体徽标 + 平台色**

引入 `PLATFORM_MEDIA`，在平台卡片标题处加媒体类型徽标；`PLATFORM_CHIP` 加新平台颜色：

```tsx
import { PLATFORM_LABELS, PLATFORM_MEDIA } from "../types";

const MEDIA_LABEL: Record<string, string> = { video: "视频", audio: "音频", both: "音视频" };

const PLATFORM_CHIP: Record<string, string> = {
  youtube: "bg-red-500/15 text-red-300",
  instagram: "bg-pink-500/15 text-pink-300",
  bilibili: "bg-blue-500/15 text-blue-300",
  douyin: "bg-cyan-500/15 text-cyan-300",
  kuaishou: "bg-orange-500/15 text-orange-300",
  ximalaya: "bg-red-500/15 text-red-300",
  xiaoyuzhou: "bg-purple-500/15 text-purple-300",
  netease_music: "bg-red-500/15 text-red-300",
  apple_podcasts: "bg-violet-500/15 text-violet-300",
};
```

在卡片平台 chip 之后加媒体徽标：

```tsx
                    <span className={`${chipCls} bg-white/[0.06] text-white/40`}>
                      {MEDIA_LABEL[PLATFORM_MEDIA[t.platform] ?? "video"]}
                    </span>
```

- [ ] **Step 3: 构建验证**

Run: `cd frontend && pnpm build`
Expected: 通过

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/Publishers.tsx
git commit -m "feat(publishers): 媒体类型徽标 + 4 个语音平台配置字段"
```

---

## 最终验收（全部任务后）

- [ ] 后端全量：`cd backend && python -m pytest -q` → 全绿。
- [ ] 前端构建：`cd frontend && pnpm build` → 通过。
- [ ] 浏览器实测（用户已启动前后端）：
  - 创建任务选"音视频路线 = 纯语音"：执行阶段无"预览"；S2 标签"脚本/语音生成"；发布平台仅列音频/音视频平台。
  - 运行后详情页：无"预览"标签；S2 分镜隐藏图片缩略图与图片提示词/重生成图片；"合成渲染"标签展示合并音频播放器 + 下载 MP3。
  - Publishers 页：每个平台显示媒体类型徽标；新增 4 个语音平台可添加并填配置。
  - 回归：视频模式任务仍正常，阶段名显示"合成渲染"。

---

## 测试策略说明

- 可单测的纯函数/单元（stage3 audio_only、`_ffmpeg_merge_audio` 顺序与报错、`_output_media_meta`、占位适配器优雅失败）均有 pytest。
- `_run_inner` / `_render_video_async` 的接线为集成路径，依赖 provider/ffmpeg/DB，沿用本仓库既有约定（不对 `_run_inner` 做集成测试），由单元测试 + 浏览器实测覆盖。
- 前端无单测框架配置，按 spec 用 `pnpm build`（tsc）+ 浏览器实测验收。
