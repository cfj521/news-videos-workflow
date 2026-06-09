# 分镜画面标题烧录 + AI HOT 内容直用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI HOT 信息源改为"item.title 烧录到画面右上角 + item.summary 直接当旁白"，每条 item 经既有 `ScoringService` 选 top N 后 1→1 成镜；标题贯穿 hyperframes / comfyui / FFmpeg 兜底三条成片路线烧录。

**Architecture:** 复用 `RawArticleData` + `ScoringService.select_top` 作选取接缝（不新造抽象）。渲染层只认每个 scene 的 `title` + `group_id`。HTML 路用 CSS 圆角 pill，FFmpeg 两路用 drawtext 直角半透明底（共用一个 `overlay.py` 拼 filter 的 helper）。

**Tech Stack:** Python / FastAPI / pydantic、Jinja2 + GSAP（HTML 渲染）、FFmpeg drawtext、React + TS（设置页）、pytest。

详见 spec：`docs/superpowers/specs/2026-06-09-burned-scene-title-design.md`

---

## 文件结构

- `backend/app/config.py` — 新增 `OverlayCfg`，`Settings.overlay`，`PipelineCfg.aihot_top_n`
- `config.yaml.example` — 新增 `overlay:` 段 + `pipeline.aihot_top_n`
- `backend/app/pipeline/stage1_collect.py` — items 模式全量透传
- `backend/app/pipeline/stage2_script.py` — AI HOT 直用路径（候选归一 + 评分选取 + 轻量出图 prompt），清理死代码
- `backend/app/pipeline/stage4_timeline.py` — entry 补 `title` + `group_id`
- `backend/app/providers/composer/overlay.py` —（新建）drawtext filter 拼装 + 字体容错，FFmpeg 两路共用
- `backend/app/providers/composer/comfyui_composer.py` — `_mux_segment` 追加 drawtext
- `backend/app/pipeline/runner.py` — `_ffmpeg_compose` 逐镜 drawtext；composer 构造传 `overlay`
- `backend/app/providers/composer/hyperframes_composer.py` — 聚合 `title_overlays`，传模板
- `backend/app/providers/composer/templates/composition.html.j2` — `.group-title` 图层 + GSAP
- `frontend/src/pages/Settings.tsx` + `frontend/src/types/index.ts` — 「画面标题」开关 + `aihot_top_n`
- `CLAUDE.md` / `README` — CJK 字体依赖（仅 FFmpeg 路）

---

## Task 1: 配置 OverlayCfg + aihot_top_n

**Files:**
- Modify: `backend/app/config.py`（`PipelineCfg` ~110、`Settings` ~202）
- Modify: `config.yaml.example`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_config.py` 末尾追加：

```python
def test_overlay_defaults():
    from app.config import Settings
    s = Settings()
    assert s.overlay.enabled is True
    assert s.overlay.font_file.endswith("msyh.ttc")
    assert s.overlay.font_size_ratio == 0.035
    assert s.overlay.bg_opacity == 0.45
    assert s.pipeline.aihot_top_n == 10
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_config.py::test_overlay_defaults -v`
Expected: FAIL（`Settings` 无 `overlay` 属性 / `pipeline` 无 `aihot_top_n`）

- [ ] **Step 3: 实现配置**

`config.py` 的 `PipelineCfg` 内（如紧接 `default_max_articles` 后）加一行：

```python
    aihot_top_n: int = 10  # AI HOT 直用模式：经 ScoringService 选取的 item 上限（1 item→1 分镜）
```

在 `HyperframesCfg` 定义之后新增类：

```python
class OverlayCfg(BaseModel):
    """画面标题烧录样式（右上角）。font_file 仅 FFmpeg 两路使用；HTML 路走 CSS 字体。"""
    enabled: bool = True
    font_file: str = "C:/Windows/Fonts/msyh.ttc"  # FFmpeg drawtext 必需的 CJK 字体文件
    font_size_ratio: float = 0.035   # 相对画面高度
    color: str = "white"
    bg_opacity: float = 0.45
    margin_ratio: float = 0.03       # 距右/上边距，相对画面短边
```

在 `Settings` 类内 `hyperframes: HyperframesCfg = HyperframesCfg()` 之后加：

```python
    overlay: OverlayCfg = OverlayCfg()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_config.py::test_overlay_defaults -v`
Expected: PASS

- [ ] **Step 5: 更新 config.yaml.example**

在 `config.yaml.example` 的 `pipeline:` 段内加一行 `  aihot_top_n: 10`；并在 `hyperframes:` 段之后追加：

```yaml
overlay:
  enabled: true
  font_file: "C:/Windows/Fonts/msyh.ttc"   # 仅 FFmpeg(comfyui/兜底)路烧标题需要；HTML 路不读
  font_size_ratio: 0.035
  color: "white"
  bg_opacity: 0.45
  margin_ratio: 0.03
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py config.yaml.example backend/tests/test_config.py
git commit -m "feat(config): 新增 overlay 标题烧录配置 + pipeline.aihot_top_n"
```

---

## Task 2: stage1 — AI HOT items 模式全量透传

**Files:**
- Modify: `backend/app/pipeline/stage1_collect.py:70-71`
- Test: `backend/tests/test_stage1.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_stage1.py` 末尾追加（参照该文件已有 collector mock 写法；如已有 helper 复用之）：

```python
@pytest.mark.asyncio
async def test_aihot_items_passthrough_all(monkeypatch):
    from app.pipeline.stage1_collect import run_stage1
    from app.providers.base import RawArticleData

    arts = [RawArticleData(title=f"i{i}", content="c", source_url="u", source_name="AI HOT",
                           metadata={"source_group": "aihot", "aihot_method": "items"}) for i in range(15)]

    class Col:
        async def collect(self, source_config, time_range): return arts

    out = await run_stage1(sources=[{"type": "aihot", "name": "AI HOT"}],
                           collectors={"aihot": Col()}, max_articles=5)
    assert len(out) == 15  # 不再被 max_articles 截断，全量交给 stage2 评分选取
```

（文件顶部若无 `import pytest` 请补上。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_stage1.py::test_aihot_items_passthrough_all -v`
Expected: FAIL（`len(out) == 5`，被旧的 `[:max_articles]` 截断）

- [ ] **Step 3: 实现透传**

`stage1_collect.py` 把 items 分支（约 70-71 行）：

```python
        log.info("AI HOT items — taking top %d (curated, no dedup/scoring/compliance)", max_articles)
        return all_articles[:max_articles]
```

改为：

```python
        log.info("AI HOT items — passthrough %d (选取交给 stage2 评分)", len(all_articles))
        return all_articles
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_stage1.py -v`
Expected: PASS（新测试通过，其它 stage1 测试不回归）

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/stage1_collect.py backend/tests/test_stage1.py
git commit -m "feat(stage1): AI HOT items 全量透传，选取交给 stage2"
```

---

## Task 3: stage2 — AI HOT 直用（候选归一 + 评分选取 + 轻量出图 prompt）

**Files:**
- Modify: `backend/app/pipeline/stage2_script.py`
- Test: `backend/tests/test_stage2_multi.py`

- [ ] **Step 1: 写失败测试（替换旧 daily/weekly 行为断言）**

`test_stage2_multi.py` 中**删除** `test_multi_daily_groups_by_category`、`test_multi_weekly_groups_like_daily`、`test_batch_items` 三个测试（它们断言的是将被替换的旧批处理），并把顶部 import 行 `from app.pipeline.stage2_script import _batch_items, replan_scenes_to_limit, run_stage2_multi` 改为 `from app.pipeline.stage2_script import replan_scenes_to_limit, run_stage2_multi`（去掉 `_batch_items`）。然后在文件末尾追加：

```python
from unittest.mock import patch


def _aihot_daily_article():
    daily_sections = [
        {"label": "模型", "items": [{"title": f"模型{i}", "summary": f"摘要{i}"} for i in range(5)]},
        {"label": "行业", "items": [{"title": f"行业{i}", "summary": f"摘要{i}"} for i in range(2)]},
    ]
    return RawArticleData(title="日报", content="c", source_url="u", source_name="AI HOT 日报",
                          metadata={"source_group": "aihot", "aihot_method": "daily",
                                    "daily_sections": daily_sections})


@pytest.mark.asyncio
async def test_aihot_daily_direct_use(monkeypatch):
    # aihot_top_n=3 → 7 条 item 选 3 条，1 item→1 scene；narration=summary 原样，不调 AI 生成旁白
    monkeypatch.setattr(config, "_settings",
                        config.Settings(pipeline=config.PipelineCfg(aihot_top_n=3)))
    tp = AsyncMock()
    # 出图 prompt（每条1次）+ summary_meta（1次）会调 AI；旁白不调
    tp.generate.side_effect = ["画面A", "画面B", "画面C",
                               json.dumps({"title": "日报汇总", "description": "d", "tags": []})]
    script = await run_stage2_multi([_aihot_daily_article()], tp)

    assert len(script["scenes"]) == 3
    assert [s["id"] for s in script["scenes"]] == [1, 2, 3]
    assert [s["group_id"] for s in script["scenes"]] == [1, 2, 3]   # 每条 item 自成一组
    for s in script["scenes"]:
        assert s["title"] == s["group_title"]                       # 烧录文字 = item.title
        assert s["narration"].startswith("摘要")                    # 旁白 = summary 原样
        assert s["title"].startswith(("模型", "行业"))
    assert tp.generate.call_count == 4                              # 3 出图 prompt + 1 meta，无旁白生成


@pytest.mark.asyncio
async def test_aihot_items_direct_use(monkeypatch):
    monkeypatch.setattr(config, "_settings",
                        config.Settings(pipeline=config.PipelineCfg(aihot_top_n=10)))
    tp = AsyncMock()
    tp.generate.side_effect = ["画面1", "画面2",
                               json.dumps({"title": "动态", "description": "d", "tags": []})]
    arts = [RawArticleData(title=f"动态{i}", content=f"内容{i}", summary=f"摘要{i}",
                           source_url="u", source_name="AI HOT",
                           metadata={"source_group": "aihot", "aihot_method": "items"}) for i in range(2)]
    script = await run_stage2_multi(arts, tp)
    assert len(script["scenes"]) == 2
    assert {s["title"] for s in script["scenes"]} == {"动态0", "动态1"}
    assert all(s["narration"].startswith("摘要") for s in script["scenes"])


@pytest.mark.asyncio
async def test_aihot_image_prompt_fallback_to_title(monkeypatch):
    monkeypatch.setattr(config, "_settings",
                        config.Settings(pipeline=config.PipelineCfg(aihot_top_n=1)))
    tp = AsyncMock()
    tp.generate.side_effect = [Exception("出图prompt失败"),
                               json.dumps({"title": "t", "description": "d", "tags": []})]
    script = await run_stage2_multi([_aihot_daily_article()], tp)
    assert script["scenes"][0]["image_prompt"] == script["scenes"][0]["title"]  # 退化为 title
```

同时确认 `test_multi_normal_articles_group_per_article` 仍在，并在其断言末尾补一行（普通源也要带 title）：

```python
    assert all(s["title"] == s["group_title"] for s in script["scenes"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_stage2_multi.py -v`
Expected: FAIL（`run_stage2_multi` 未走 aihot 直用；普通源 scene 无 `title`）

- [ ] **Step 3: 实现 AI HOT 直用**

`stage2_script.py` 顶部 import 区加：

```python
from app import config
from app.services.scoring import ScoringService
```

新增三个函数（放在 `run_stage2_multi` 之前）：

```python
def _aihot_candidates(articles: list) -> list:
    """把 AI HOT 三种模式归一为 RawArticleData 候选列表（供 ScoringService 评分）。"""
    from app.providers.base import RawArticleData
    out: list = []
    for art in articles:
        method = art.metadata.get("aihot_method", "items")
        sections = art.metadata.get("daily_sections")
        if method in ("daily", "weekly") and sections:
            for sec in sections:
                label = sec.get("label", "")
                for it in sec.get("items", []):
                    out.append(RawArticleData(
                        title=it.get("title", ""), content=it.get("summary", ""),
                        summary=it.get("summary", ""), source_url=art.source_url,
                        source_name=art.source_name, published_at=art.published_at,
                        category=label, metadata={}))
        else:  # items 模式：article 本身即一条 item
            out.append(art)
    return out


async def _gen_image_prompt(cand, tp, language: str = "zh") -> str:
    """把新闻 title+summary 转成一句视觉画面描述供文生图（非重写旁白）。失败退化为 title。"""
    sys = ("Turn the news into ONE concise visual scene description for image generation "
           "(subject + setting + style). Output the description only, no quotes."
           if _is_en(language) else
           "把这条新闻转成一句用于文生图的画面描述（主体+场景+风格），只输出该句，不要引号。")
    try:
        resp = await tp.generate(prompt=f"{cand.title}。{cand.summary}", system_prompt=sys)
        text = resp.strip().strip('"').strip("「」")
        return text or cand.title
    except Exception:
        log.warning("[S2] image prompt gen failed for '%s' — fallback to title", cand.title[:40])
        return cand.title


async def _run_aihot_direct(articles: list, tp, language: str = "zh") -> dict:
    """AI HOT 直用：归一候选 → ScoringService 选 top N → 每条 1 scene（不 AI 生成旁白）。"""
    candidates = _aihot_candidates(articles)
    top_n = config.get_settings().pipeline.aihot_top_n
    selected = ScoringService().select_top(candidates, n=top_n)  # 规则分；将来换 select_top_with_llm
    scenes: list[dict] = []
    groups: list[dict] = []
    titles: list[str] = []
    for i, cand in enumerate(selected, start=1):
        image_prompt = await _gen_image_prompt(cand, tp, language)
        scenes.append({
            "id": i, "group_id": i, "group_title": cand.title, "title": cand.title,
            "narration": cand.summary or cand.content, "image_prompt": image_prompt,
            "motion_prompt": "", "duration_hint": 5,
        })
        groups.append({"id": i, "title": cand.title, "source_index": 0})
        titles.append(cand.title)
    meta = await _gen_summary_meta(titles, tp, language)
    log.info("[S2] AI HOT direct: %d candidates → %d scenes (top_n=%d)", len(candidates), len(scenes), top_n)
    return {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
            "groups": groups, "scenes": scenes}
```

在 `run_stage2_multi` 函数体**最开头**加路由（aihot 整批直接走直用，提前返回）：

```python
    if articles and articles[0].metadata.get("source_group") == "aihot":
        return await _run_aihot_direct(articles, text_provider, language)
```

加了该路由后，原 `run_stage2_multi` 主循环里 `if article.metadata.get("aihot_method") in ("daily", "weekly") and sections:` 这个 daily 批处理分支对非-aihot 永不命中、且会调用即将删除的 `_gen_daily_batch_scenes` → **删除该 `if` 分支整块**，只保留 `else` 的 `_gen_article_scenes` 普通源逻辑（去掉 `if/else` 缩进一层）。

并在普通源 `_gen_article_scenes` 回填那段（`for sc in art_scenes:` 循环内）加一行
`sc["title"] = article.title`，使普通源 scene 也带 `title`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_stage2_multi.py -v`
Expected: PASS（aihot 三测 + 普通源 title 断言全过）

- [ ] **Step 5: 清理死代码**

确认 `_gen_daily_batch_scenes`、`_batch_items` 已无调用方（删除旧 daily 批处理后）：

Run: `cd backend && grep -rn "_gen_daily_batch_scenes\|_batch_items\|daily_batch" app/ tests/`
若仅剩定义处：删除 `stage2_script.py` 中 `_gen_daily_batch_scenes`、`_batch_items` 两函数，
并删除 `app/prompts.py` 中 `daily_batch` 的 `PromptDef`（若存在）。再跑：

Run: `cd backend && pytest tests/test_stage2_multi.py tests/test_prompts.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/stage2_script.py backend/app/prompts.py backend/tests/test_stage2_multi.py
git commit -m "feat(stage2): AI HOT 直用(复用ScoringService选取+轻量出图prompt)，清理旧批处理"
```

---

## Task 4: stage4 — entry 补 title + group_id

**Files:**
- Modify: `backend/app/pipeline/stage4_timeline.py:59-68`
- Test: `backend/tests/test_stage4.py`

- [ ] **Step 1: 写失败测试**

`test_stage4.py` 末尾追加：

```python
def test_stage4_entry_carries_title_and_group_id():
    scene_assets = [
        {"scene_id": 1, "image": {"file_path": "i1.png"}, "audio": {"file_path": "a1.mp3", "duration_ms": 4000}},
        {"scene_id": 2, "image": {"file_path": "i2.png"}, "audio": {"file_path": "a2.mp3", "duration_ms": 4000}},
    ]
    script = {"scenes": [
        {"id": 1, "narration": "n1", "title": "标题1", "group_id": 1, "duration_hint": 5},
        {"id": 2, "narration": "n2", "title": "标题2", "group_id": 2, "duration_hint": 5},
    ]}
    timeline = run_stage4(script=script, scene_assets=scene_assets, scene_gap_ms=0)
    assert [e["title"] for e in timeline["entries"]] == ["标题1", "标题2"]
    assert [e["group_id"] for e in timeline["entries"]] == [1, 2]


def test_stage4_title_falls_back_to_group_title():
    scene_assets = [{"scene_id": 1, "image": {"file_path": "i.png"}, "audio": {"file_path": "a.mp3", "duration_ms": 3000}}]
    script = {"scenes": [{"id": 1, "narration": "n", "group_title": "组标题", "group_id": 7, "duration_hint": 5}]}
    timeline = run_stage4(script=script, scene_assets=scene_assets, scene_gap_ms=0)
    assert timeline["entries"][0]["title"] == "组标题"
    assert timeline["entries"][0]["group_id"] == 7
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_stage4.py::test_stage4_entry_carries_title_and_group_id -v`
Expected: FAIL（entry 无 `title`/`group_id`）

- [ ] **Step 3: 实现**

`stage4_timeline.py` 构造 `entry` 的字典（约 59-68 行）里，在 `"subtitle_lines": subtitle_lines,` 后加两行：

```python
            "title": scene_data.get("title") or scene_data.get("group_title", ""),
            "group_id": scene_data.get("group_id"),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_stage4.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/stage4_timeline.py backend/tests/test_stage4.py
git commit -m "feat(stage4): timeline entry 携带 title + group_id"
```

---

## Task 5: overlay.py — drawtext filter 拼装（FFmpeg 两路共用）

**Files:**
- Create: `backend/app/providers/composer/overlay.py`
- Test: `backend/tests/test_overlay_drawtext.py`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_overlay_drawtext.py`：

```python
from app.config import OverlayCfg
from app.providers.composer.overlay import build_drawtext


def test_build_drawtext_escapes_windows_path(tmp_path):
    font = tmp_path / "msyh.ttc"
    font.write_bytes(b"FONT")
    ov = OverlayCfg(font_file=str(font))
    txt = tmp_path / "t1.txt"
    f = build_drawtext("标题甲", 1080, 1920, ov, str(txt))
    assert f is not None
    assert "drawtext=" in f
    assert "\\:" in f                       # 路径冒号被转义（盘符或 tmp 路径）
    assert "x=w-tw-" in f and "box=1" in f
    assert txt.read_text(encoding="utf-8") == "标题甲"   # 文本写入 textfile


def test_build_drawtext_skips_when_font_missing(tmp_path):
    ov = OverlayCfg(font_file=str(tmp_path / "nope.ttc"))
    assert build_drawtext("标题", 1080, 1920, ov, str(tmp_path / "t.txt")) is None


def test_build_drawtext_skips_when_disabled_or_empty(tmp_path):
    font = tmp_path / "f.ttc"; font.write_bytes(b"F")
    assert build_drawtext("标题", 1080, 1920, OverlayCfg(enabled=False, font_file=str(font)), str(tmp_path / "t.txt")) is None
    assert build_drawtext("   ", 1080, 1920, OverlayCfg(font_file=str(font)), str(tmp_path / "t.txt")) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_overlay_drawtext.py -v`
Expected: FAIL（`overlay` 模块不存在）

- [ ] **Step 3: 实现**

新建 `backend/app/providers/composer/overlay.py`：

```python
from pathlib import Path

from app.logging import get_logger

log = get_logger("composer.overlay")


def _esc(p: str) -> str:
    """drawtext 选项里的路径转义：反斜杠转正斜杠、盘符/路径冒号转义为 \\:。"""
    return p.replace("\\", "/").replace(":", r"\:")


def build_drawtext(title: str, width: int, height: int, overlay, textfile_path: str) -> str | None:
    """拼右上角标题 drawtext filter；写文本到 textfile。

    返回 None（跳过烧录）当：overlay 关闭 / 标题空 / 字体文件缺失。
    box 为直角（FFmpeg 无圆角）。调用方把返回串拼进 vf。
    """
    if not overlay.enabled or not (title and title.strip()):
        return None
    font = overlay.font_file
    if not font or not Path(font).exists():
        log.warning("overlay 字体缺失：%s — 跳过该镜标题烧录", font)
        return None
    Path(textfile_path).write_text(title, encoding="utf-8")
    fontsize = max(12, int(height * overlay.font_size_ratio))
    margin = int(min(width, height) * overlay.margin_ratio)
    return (
        f"drawtext=fontfile={_esc(font)}:textfile={_esc(textfile_path)}:reload=0"
        f":fontcolor={overlay.color}:fontsize={fontsize}"
        f":box=1:boxcolor=black@{overlay.bg_opacity}:boxborderw={max(6, fontsize // 4)}"
        f":x=w-tw-{margin}:y={margin}"
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_overlay_drawtext.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/composer/overlay.py backend/tests/test_overlay_drawtext.py
git commit -m "feat(composer): 新增 overlay.build_drawtext（FFmpeg 标题烧录，字体容错）"
```

---

## Task 6: comfyui 路 — `_mux_segment` 追加 drawtext

**Files:**
- Modify: `backend/app/providers/composer/comfyui_composer.py`
- Test: `backend/tests/test_comfyui_composer.py`

- [ ] **Step 1: 写失败测试**

`test_comfyui_composer.py` 末尾追加（捕获传给 ffmpeg 的命令，断言含 drawtext）：

```python
@pytest.mark.asyncio
async def test_compose_burns_title_via_drawtext(tmp_path, monkeypatch):
    from app.config import OverlayCfg
    font = tmp_path / "f.ttc"; font.write_bytes(b"F")
    (tmp_path / "assets").mkdir()
    timeline = {"total_duration_ms": 2000, "entries": [
        {"scene_id": 1, "image_path": str(tmp_path / "a.png"), "audio_path": "",
         "start_ms": 0, "end_ms": 2000, "subtitle_text": "x", "title": "新闻标题甲"},
    ]}
    open(tmp_path / "a.png", "wb").write(b"P")
    cmds = []

    class VP:
        async def generate(self, image_path, prompt, duration, resolution="704x480", output_path=""):
            open(output_path, "wb").write(b"MP4")
            from app.providers.base import AssetResult
            return AssetResult(file_path=output_path)

    def fake_run(cmd, **kw):
        cmds.append(cmd); open(cmd[-1], "wb").write(b"OUT")
        class R: returncode = 0; stderr = b""
        return R()
    monkeypatch.setattr("app.providers.composer.comfyui_composer.subprocess.run", fake_run)

    comp = ComfyUIVideoComposer(VP(), fps=24, overlay=OverlayCfg(font_file=str(font)))
    await comp.compose(timeline, str(tmp_path / "assets"), str(tmp_path / "out.mp4"), "704x480")
    assert any("drawtext=" in part for cmd in cmds for part in cmd)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_comfyui_composer.py::test_compose_burns_title_via_drawtext -v`
Expected: FAIL（`ComfyUIVideoComposer` 无 `overlay` 参数 / 命令无 drawtext）

- [ ] **Step 3: 实现**

`comfyui_composer.py` 顶部 import 加：

```python
from app.config import OverlayCfg
from app.providers.composer.overlay import build_drawtext
```

`__init__` 改为接收 overlay：

```python
    def __init__(self, video_provider, fps: int = 24, overlay: OverlayCfg | None = None):
        self._video = video_provider
        self._fps = fps
        self._overlay = overlay or OverlayCfg()
```

`compose` 内 `_mux_segment(...)` 调用处，传入该 entry 的 title 与一个临时 txt 路径：
把 `seg = str(clips_dir / f"seg_{sid:02d}.mp4")` 后的调用改为：

```python
            seg = str(clips_dir / f"seg_{sid:02d}.mp4")
            draw = build_drawtext(entry.get("title", ""), w, h, self._overlay,
                                  str(clips_dir / f"title_{sid:02d}.txt"))
            _mux_segment(raw, audio_path, dur, w, h, self._fps, seg, draw)
```

`_mux_segment` 增参并把 drawtext 拼到 `vf` **末尾**（tpad 之后）：

```python
def _mux_segment(clip, audio, dur, w, h, fps, out, draw: str | None = None):
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
          f"setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration={dur}")
    if draw:
        vf = vf + "," + draw
    if audio and Path(audio).exists():
        cmd = ["ffmpeg", "-y", "-i", clip, "-i", audio,
               "-filter_complex", f"[0:v]{vf}[v];[1:a]apad[a]",
               "-map", "[v]", "-map", "[a]", "-t", str(dur),
               "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-ar", "48000", out]
    else:
        cmd = ["ffmpeg", "-y", "-i", clip, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
               "-vf", vf, "-t", str(dur),
               "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac", out]
    _ff(cmd)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_comfyui_composer.py -v`
Expected: PASS（新测试 + 原有 `test_compose_calls_provider_per_scene_and_concats` 不回归）

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/composer/comfyui_composer.py backend/tests/test_comfyui_composer.py
git commit -m "feat(composer/comfyui): _mux_segment 在 tpad 后烧录右上角标题"
```

---

## Task 7: FFmpeg 兜底 — `_ffmpeg_compose` 逐镜 drawtext

**Files:**
- Modify: `backend/app/pipeline/runner.py:1007-1042`（`_ffmpeg_compose` 签名 + 每镜子链）
- Test: `backend/tests/test_ffmpeg_compose_shell.py`

- [ ] **Step 1: 写失败测试**

`test_ffmpeg_compose_shell.py` 末尾追加（断言每镜子链含各自的 drawtext）：

```python
def test_ffmpeg_compose_inserts_per_scene_drawtext(tmp_path, monkeypatch):
    from app.config import OverlayCfg
    from app.pipeline import runner
    font = tmp_path / "f.ttc"; font.write_bytes(b"F")
    captured = {}

    def fake_run_ffmpeg(cmd, service=""):
        captured["fc"] = cmd[cmd.index("-filter_complex") + 1]
        open(cmd[-1], "wb").write(b"OUT")
    monkeypatch.setattr(runner, "_run_ffmpeg", fake_run_ffmpeg)

    timeline = {"entries": [
        {"scene_id": 1, "image_path": "a.png", "audio_path": "x.mp3", "start_ms": 0, "end_ms": 2000, "title": "甲"},
        {"scene_id": 2, "image_path": "b.png", "audio_path": "y.mp3", "start_ms": 2000, "end_ms": 4000, "title": "乙"},
    ]}
    runner._ffmpeg_compose(timeline, tmp_path, "1080x1920", "30", overlay=OverlayCfg(font_file=str(font)))
    assert captured["fc"].count("drawtext=") == 2  # 每镜一个，文本各异
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_ffmpeg_compose_shell.py::test_ffmpeg_compose_inserts_per_scene_drawtext -v`
Expected: FAIL（`_ffmpeg_compose` 无 `overlay` 参数 / filter 无 drawtext）

- [ ] **Step 3: 实现**

`runner.py` 顶部确认已 import（无则加）：

```python
from app.providers.composer.overlay import build_drawtext
```

`_ffmpeg_compose` 签名加 `overlay=None`：

```python
def _ffmpeg_compose(timeline: dict, run_dir: Path, resolution: str, fps: str, overlay=None) -> str:
```

函数体顶部（取 `w, h` 后）加：

```python
    from app.config import OverlayCfg
    overlay = overlay or OverlayCfg()
    wi, hi = int(w), int(h)
```

每镜视频子链改为按需追加 drawtext（替换原 `filter_parts.append(f"[{vi}:v]scale=...[v{idx}]")` 那一句）：

```python
        draw = build_drawtext(entry.get("title", ""), wi, hi, overlay,
                              str(Path(run_dir) / f"title_{idx}.txt"))
        chain = (f"[{vi}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                 f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}")
        if draw:
            chain += "," + draw
        filter_parts.append(chain + f"[v{idx}]")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_ffmpeg_compose_shell.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/runner.py backend/tests/test_ffmpeg_compose_shell.py
git commit -m "feat(runner): _ffmpeg_compose 逐镜烧录标题 drawtext"
```

---

## Task 8: hyperframes 路 — `.group-title` 图层（圆角 pill + GSAP 淡切）

**Files:**
- Modify: `backend/app/providers/composer/hyperframes_composer.py`
- Modify: `backend/app/providers/composer/templates/composition.html.j2`
- Test: `backend/tests/test_hyperframes_template.py`

- [ ] **Step 1: 写失败测试**

`test_hyperframes_template.py` 末尾追加：

```python
def test_render_html_group_title_overlays():
    from app.config import OverlayCfg
    composer = HyperframesComposer(overlay=OverlayCfg())
    timeline = {"entries": [
        {"scene_id": 1, "start_ms": 0, "end_ms": 4000, "image_path": "i1.png", "audio_path": "a1.mp3",
         "audio_duration_ms": 4000, "subtitle_lines": [], "title": "标题甲", "group_id": 1},
        {"scene_id": 2, "start_ms": 4000, "end_ms": 8000, "image_path": "i2.png", "audio_path": "a2.mp3",
         "audio_duration_ms": 4000, "subtitle_lines": [], "title": "标题甲", "group_id": 1},
        {"scene_id": 3, "start_ms": 8000, "end_ms": 12000, "image_path": "i3.png", "audio_path": "a3.mp3",
         "audio_duration_ms": 4000, "subtitle_lines": [], "title": "标题乙", "group_id": 2},
    ], "total_duration_ms": 12000}
    html = composer._render_html(timeline, resolution="1080x1920", run_dir=Path("."))
    assert "group-title" in html
    assert html.count('class="group-title"') == 2     # 2 组 → 2 个标题块（首组跨两镜合并）
    assert "标题甲" in html and "标题乙" in html
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_hyperframes_template.py::test_render_html_group_title_overlays -v`
Expected: FAIL（`HyperframesComposer` 无 `overlay` 参数 / 模板无 group-title）

- [ ] **Step 3: 实现 composer 聚合**

`hyperframes_composer.py`：`__init__`（类目前无显式 `__init__`，新增）：

```python
    def __init__(self, overlay=None):
        from app.config import OverlayCfg
        self._overlay = overlay or OverlayCfg()
```

`_render_html` 在 `entries` 组装完成后、`return template.render(...)` 之前，按 `group_id` 聚合连续段：

```python
        title_overlays = []
        for e in entries:
            gid = e.get("group_id")
            title = e.get("title", "")
            if title and title_overlays and title_overlays[-1]["group_id"] == gid:
                title_overlays[-1]["end_s"] = e["end_s"]       # 同组连续 → 延长
            elif title:
                title_overlays.append({"group_id": gid, "title": title,
                                       "start_s": e["start_s"], "end_s": e["end_s"]})
        title_font_size = max(20, int(height * self._overlay.font_size_ratio))
```

注意：`entries` 里每项需含 `group_id`/`title`/`end_s`（`end_s` 已有；group_id/title 来自
timeline entry，需在该 for 循环组装 `entries.append({...})` 时带上）。在 `entries.append({...})`
字典里补两行：

```python
                "group_id": entry.get("group_id"),
                "title": entry.get("title", ""),
```

`return template.render(...)` 增传：

```python
        return template.render(width=width, height=height, total_duration_s=round(total_s, 3),
                               entries=entries, prev_scene_ids=prev_scene_ids, transition=transition,
                               subtitle_font_size=subtitle_font_size,
                               title_overlays=title_overlays, title_font_size=title_font_size,
                               overlay=self._overlay)
```

（`_render_html` 签名保留默认参数不变即可。）

- [ ] **Step 4: 实现模板**

`composition.html.j2` 的 `<style>` 内 `.subtitle{...}` 之后加：

```css
    .group-title {
      position: absolute; top: {{ (height * overlay.margin_ratio) | int }}px;
      right: {{ (height * overlay.margin_ratio) | int }}px;
      font-size: {{ title_font_size | default(48) }}px; color: {{ overlay.color | default('white') }};
      background: rgba(0,0,0,{{ overlay.bg_opacity | default(0.45) }});
      padding: 8px 16px; border-radius: 12px; max-width: 60%;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif; opacity: 0;
    }
```

在 subtitle 元素 `{% for %}` 块之后，加 group-title 元素块：

```html
    {% for ov in title_overlays %}
    <div class="group-title" id="gt{{ loop.index0 }}">{{ ov.title }}</div>
    {% endfor %}
```

在 `<script>` 内、`window.__timelines = ...` 之前，加 GSAP 组淡切：

```javascript
    {% for ov in title_overlays %}
    tl.to("#gt{{ loop.index0 }}", { opacity: 1, duration: 0.3 }, {{ ov.start_s }});
    tl.to("#gt{{ loop.index0 }}", { opacity: 0, duration: 0.3 }, {{ ov.end_s - 0.3 if ov.end_s > 0.3 else ov.end_s }});
    {% endfor %}
```

**关键**：成片隐藏逻辑只隐藏 `.subtitle`（现有 `document.querySelectorAll('.subtitle')`），
`.group-title` 不在其列 → 成片保留烧录。**不要**把 group-title 加进隐藏选择器。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && pytest tests/test_hyperframes_template.py -v`
Expected: PASS（新测试 + 原 `test_render_html_template` 不回归）

- [ ] **Step 6: Commit**

```bash
git add backend/app/providers/composer/hyperframes_composer.py backend/app/providers/composer/templates/composition.html.j2 backend/tests/test_hyperframes_template.py
git commit -m "feat(composer/hyperframes): .group-title 图层(圆角 pill + 组间淡切)，成片保留"
```

---

## Task 9: runner 接线 — 把 overlay 传给三路 composer

**Files:**
- Modify: `backend/app/pipeline/runner.py`（~742、~812、~821、~825、~835）

- [ ] **Step 1: 改 composer 构造与调用**

`runner.py` 中：
- S4 预览（约 742）`composer = HyperframesComposer()` → `composer = HyperframesComposer(overlay=cfg.overlay)`
- S5 hyperframes（约 825）`composer = HyperframesComposer()` → `composer = HyperframesComposer(overlay=cfg.overlay)`
- S5 comfyui（约 812）`ComfyUIVideoComposer(vp, fps=cfg.pipeline.video_fps)` →
  `ComfyUIVideoComposer(vp, fps=cfg.pipeline.video_fps, overlay=cfg.overlay)`
- 两处兜底（约 821、835）`_ffmpeg_compose(timeline, run_dir, resolution, cfg.hyperframes.fps)` →
  `_ffmpeg_compose(timeline, run_dir, resolution, cfg.hyperframes.fps, overlay=cfg.overlay)`

- [ ] **Step 2: 回归全测**

Run: `cd backend && pytest -q`
Expected: PASS（全绿；重点 `test_runner_*`、`test_stage*`、`test_*composer*`）

- [ ] **Step 3: Commit**

```bash
git add backend/app/pipeline/runner.py
git commit -m "feat(runner): 三路 composer 接入 overlay 标题配置"
```

---

## Task 10: 前端设置页 — 「画面标题」开关 + aihot_top_n

**Files:**
- Modify: `frontend/src/types/index.ts`（Settings 类型）
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: 扩展类型**

`frontend/src/types/index.ts` 的 Settings 类型中，`pipeline` 增 `aihot_top_n: number`；
新增 `overlay` 字段：

```ts
overlay: {
  enabled: boolean;
  font_file: string;
  font_size_ratio: number;
  color: string;
  bg_opacity: number;
  margin_ratio: number;
};
```

- [ ] **Step 2: 加 UI 控件**

`frontend/src/pages/Settings.tsx` 中，参照现有 `hyperframes.subtitle_font_size` 的渲染/保存写法
（grep `subtitle_font_size` 定位那段表单），在合适分组（如「合成/视频」或「ComfyUI/Hyperframes」附近）
新增一组「画面标题」：
- `overlay.enabled` 复选框开关
- `pipeline.aihot_top_n` 数字输入（label：AI HOT 取前 N 条）

保存逻辑沿用该页现有 `saveSettings`/回写 config 的同一通道，无需新接口。

- [ ] **Step 3: 校验**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: 无类型/lint 错误，build 成功

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/pages/Settings.tsx
git commit -m "feat(ui): 设置页新增画面标题开关与 AI HOT 取前N"
```

---

## Task 11: 文档 — CJK 字体系统依赖（仅 FFmpeg 路）

**Files:**
- Modify: `CLAUDE.md`（Dependencies 段）
- Modify: `README`（若有安装说明章节）

- [ ] **Step 1: 更新 CLAUDE.md Dependencies**

在 `CLAUDE.md` 的 `## Dependencies` 列表中，FFmpeg 条目附近新增：

```markdown
- **CJK 字体（标题烧录，仅 FFmpeg 路）**: comfyui / FFmpeg 兜底路用 `drawtext` 把分镜标题烧到画面右上角，需一个可用的中日韩字体文件。Windows 默认 `C:/Windows/Fonts/msyh.ttc`（微软雅黑，系统自带）；其它平台在 `config.yaml` 的 `overlay.font_file` 指定（如 `/usr/share/fonts/.../NotoSansCJK-Regular.ttc`）。缺失时仅跳过烧录、不影响出片。hyperframes(HTML) 路不依赖此项（走 CSS 字体）。
```

并在 `## Configuration` 的分组列表里补一行说明 `overlay` 段（标题烧录样式 + `pipeline.aihot_top_n`）。

- [ ] **Step 2: 更新 README（若存在安装/依赖章节）**

Run: `grep -rln "FFmpeg\|ffmpeg" README* 2>/dev/null`
若有 README 安装章节，加入同样的 CJK 字体依赖说明；无则跳过。

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README*
git commit -m "docs: 新增 CJK 字体系统依赖说明（标题烧录，仅 FFmpeg 路）"
```

---

## 收尾验证

- [ ] 全后端测试：`cd backend && pytest -q` 全绿
- [ ] 前端：`cd frontend && pnpm lint && pnpm build` 通过
- [ ] 手动冒烟（用户自行跑后端）：建一个 AI HOT 日报 run，确认成片右上角逐镜显示 item 标题、旁白读 summary、画面文字随镜切换；分别在 comfyui 与 hyperframes 路线各验证一次。
