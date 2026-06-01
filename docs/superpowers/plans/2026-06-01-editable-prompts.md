# 可编辑提示词 + 接地气脚本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把流水线在用的 7 个 AI 提示词搬到 Settings 页可编辑（全局默认、空=内置默认、可恢复），并改写默认内容让脚本通俗中文、image/motion prompt 保留英文但强制亚洲/中国面孔与中式场景。

**Architecture:** 新建 `backend/app/prompts.py` 提示词注册表（key→中文标题/说明/默认文本）+ `resolve_prompt(key)` 解析器（用户覆盖 or 内置默认）；`PromptsCfg` 进 `Settings`(YAML)；各调用点改读解析器；前端 Settings 加「提示词」区。

**Tech Stack:** Python(FastAPI/pydantic/pytest)，React+TS(Vite)。

参考 spec：`docs/superpowers/specs/2026-06-01-editable-prompts-design.md`

---

## File Structure

- `backend/app/prompts.py`（新）— `PromptDef`、`PROMPTS`(7条)、`DEFAULTS`、`resolve_prompt`。
- `backend/app/config.py`（改）— `PromptsCfg` + `Settings.prompts`。
- `backend/app/pipeline/stage2_script.py`（改）— 4 处用解析器；删死代码 `run_stage2`/`SCRIPT_SYSTEM_PROMPT`/`DAILY_DIGEST_SYSTEM_PROMPT` 及 4 个 `*_SYSTEM_PROMPT` 常量。
- `backend/app/pipeline/runner.py`（改）— `_summarize_articles` 用解析器 + 拼长度后缀。
- `backend/app/services/scoring.py`（改）— 评分用解析器；`SCORING_SYSTEM_PROMPT` 文本移入注册表。
- `backend/app/api/pipeline.py`（改）— regen-prompt 的 `system` 与 add-scene 的 `ROUNDUP_ARTICLE_SYSTEM_PROMPT` 引用改解析器。
- `backend/app/api/settings.py`（改）— prompts 不脱敏、PUT 不跳过含 `...` 的 prompts、新增 defaults 端点。
- `frontend/src/api/client.ts`（改）— `AppSettings.prompts` + `promptDefaults()`。
- `frontend/src/pages/Settings.tsx`（改）— `EMPTY_SETTINGS.prompts` + 「提示词」区。
- 测试：`backend/tests/test_prompts.py`(新)、`backend/tests/test_api_settings_prompts.py`(新)。

---

## Task 1: `PromptsCfg` 进 Settings

**Files:**
- Modify: `backend/app/config.py`（`Settings` 类附近，约 106-118 行）
- Test: `backend/tests/test_prompts.py`（新建）

- [ ] **Step 1: 写失败测试** — 新建 `backend/tests/test_prompts.py`：

```python
from app.config import Settings


def test_settings_has_empty_prompts_by_default():
    s = Settings()
    assert s.prompts.roundup_article == ""
    assert s.prompts.news_scoring == ""
    # 7 个字段齐全
    for k in ("roundup_article", "daily_batch", "summary_meta", "weekly_digest",
              "image_regen", "article_summary", "news_scoring"):
        assert hasattr(s.prompts, k)


def test_settings_prompts_roundtrip():
    s = Settings(prompts={"roundup_article": "自定义"})
    assert s.prompts.roundup_article == "自定义"
    assert s.model_dump()["prompts"]["roundup_article"] == "自定义"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_prompts.py -v`
Expected: FAIL（`Settings` 无 `prompts` 属性）

- [ ] **Step 3: 实现** — 在 `backend/app/config.py` 的 `class Settings` 之前加 `PromptsCfg`，并在 `Settings` 里加字段：

```python
class PromptsCfg(BaseModel):
    roundup_article: str = ""
    daily_batch: str = ""
    summary_meta: str = ""
    weekly_digest: str = ""
    image_regen: str = ""
    article_summary: str = ""
    news_scoring: str = ""
```

在 `class Settings(BaseModel):` 内（`ltx: LTXCfg = LTXCfg()` 之后）加：

```python
    prompts: PromptsCfg = PromptsCfg()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_prompts.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/config.py backend/tests/test_prompts.py
git commit -m "feat(prompts): PromptsCfg 进 Settings"
```
提交信息结尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。分支 `feat/aihot-default-exclusion`，勿 push。

---

## Task 2: 提示词注册表 `prompts.py` + 解析器

**Files:**
- Create: `backend/app/prompts.py`
- Test: `backend/tests/test_prompts.py`（追加）

- [ ] **Step 1: 写失败测试** — 追加到 `backend/tests/test_prompts.py`：

```python
import pytest
from app.prompts import DEFAULTS, PROMPTS, resolve_prompt
from app import config


def test_defaults_have_7_entries():
    assert len(PROMPTS) == 7
    assert set(DEFAULTS) == {"roundup_article", "daily_batch", "summary_meta",
                             "weekly_digest", "image_regen", "article_summary", "news_scoring"}


def test_default_content_enforces_asian_chinese():
    # 守卫：画面类提示词默认必须强制亚洲/中国面孔，防被无意改回欧美默认
    for key in ("roundup_article", "daily_batch", "image_regen"):
        text = DEFAULTS[key]
        assert "Asian" in text or "Chinese" in text


def test_resolve_prefers_override(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"news_scoring": "我的评分"}))
    assert resolve_prompt("news_scoring") == "我的评分"


def test_resolve_falls_back_to_default_on_blank(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"news_scoring": "   "}))
    assert resolve_prompt("news_scoring") == DEFAULTS["news_scoring"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_prompts.py -k "defaults or content or resolve" -v`
Expected: FAIL（`app.prompts` 不存在）

- [ ] **Step 3: 实现** — 新建 `backend/app/prompts.py`。把 `scoring.py` 里 `SCORING_SYSTEM_PROMPT = """..."""` 的**完整文本原样**作为 `news_scoring` 默认（从 `backend/app/services/scoring.py` 复制该多行字符串）；其余默认如下（①②⑤ 已按要求改写）：

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptDef:
    key: str
    label: str
    desc: str
    default: str


_ROUNDUP = """你是新闻短视频的分镜脚本编写者。下面给你一条资讯，为它生成 1~3 个分镜（内容多/重要则多，简短则 1 个）。
输出纯 JSON（无 markdown 标记）：
{"scenes":[{"narration":"口语化中文旁白","image_prompt":"English scene description","motion_prompt":"English camera motion","duration_hint":5}]}
要求：
- narration：像新闻主播口播的通俗中文，简单易懂，少用生僻词和英文。
- image_prompt / motion_prompt：用英文（English only）；画面人物必须是亚洲/中国人面孔（East Asian / Chinese faces），场景与背景为中式真实环境，避免出现欧美面孔。
- 分镜数不超过 3。"""

_DAILY_BATCH = """你是 AI 资讯日报短视频的分镜脚本编写者。下面给你同一类目下的若干条资讯，请每条资讯生成 1 个分镜，顺序与给定一致。
输出纯 JSON（无 markdown 标记）：
{"scenes":[{"narration":"口语化中文旁白","image_prompt":"English scene description","motion_prompt":"English camera motion","duration_hint":5}]}
要求：
- narration：通俗易懂的中文口播，少用英文。
- image_prompt / motion_prompt：用英文（English only）；人物为亚洲/中国人面孔、中式场景背景，避免欧美面孔。
- 分镜数量须等于给定资讯条数。"""

_SUMMARY_META = """你是短视频运营。下面给你一条汇总视频包含的各条资讯标题，生成整条视频的吸睛标题与简介。
输出纯 JSON（无 markdown 标记）：{"title":"中文标题","description":"1-2句中文简介","tags":["标签1","标签2"]}"""

_WEEKLY_DIGEST = """你是 AI 资讯周报编辑。下面给你过去一整周的全部资讯条目（含日期/分类线索）。
请跨天归纳出**本周 3-5 个最重要的热点主题**，每个主题挑 1-3 条最有代表性的资讯，**全部主题的资讯总条数不超过 9 条**。
要求：体现"本周"视角（趋势、归纳），合并跨天对同一事件的重复报道。
输出纯 JSON（无 markdown 标记）：
{"sections":[{"label":"主题名(中文)","items":[{"title":"资讯标题","summary":"一句话摘要"}]}]}"""

_IMAGE_REGEN = """你是视频图片提示词专家。根据旁白文本生成一段详细的 AI 图片生成提示词，描述一张能配合旁白内容的画面。
要求：用英文输出（English only）；画面人物必须是亚洲/中国人面孔（East Asian / Chinese），场景与背景为中式真实环境，避免欧美面孔。只输出提示词本身，不要其他内容。"""

_ARTICLE_SUMMARY = """用中文为新闻文章生成简洁摘要。只输出摘要文本。"""

_NEWS_SCORING = """<<从 backend/app/services/scoring.py 的 SCORING_SYSTEM_PROMPT 三引号字符串原样复制粘贴到这里>>"""

PROMPTS: list[PromptDef] = [
    PromptDef("roundup_article", "资讯分镜（单条）", "每条资讯→1~3 个分镜（旁白+画面提示词）", _ROUNDUP),
    PromptDef("daily_batch", "日报/周报分镜（成组）", "同类目若干条→每条 1 个分镜", _DAILY_BATCH),
    PromptDef("summary_meta", "汇总标题/简介", "整片标题、简介、标签", _SUMMARY_META),
    PromptDef("weekly_digest", "周报主题提炼", "一周条目→3~5 个主题", _WEEKLY_DIGEST),
    PromptDef("image_regen", "旁白→图片提示词", "单分镜重生成图片提示词", _IMAGE_REGEN),
    PromptDef("article_summary", "文章摘要（普通源）", "采集后对文章做摘要（字数上限自动追加）", _ARTICLE_SUMMARY),
    PromptDef("news_scoring", "新闻评分（普通源）", "评分排序用", _NEWS_SCORING),
]

DEFAULTS: dict[str, str] = {p.key: p.default for p in PROMPTS}


def resolve_prompt(key: str) -> str:
    """用户在 Settings 里填了就用用户的，否则用内置默认。"""
    from app.config import get_settings
    override = (getattr(get_settings().prompts, key, "") or "").strip()
    return override or DEFAULTS[key]
```

> 注意：把 `_NEWS_SCORING` 占位行替换为 `scoring.py` 中 `SCORING_SYSTEM_PROMPT` 的完整原文（含全部评分标准文字），不要遗漏。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_prompts.py -v`
Expected: PASS（含 Task1 的 2 个 + 本任务 4 个）

- [ ] **Step 5: 提交**

```bash
git add backend/app/prompts.py backend/tests/test_prompts.py
git commit -m "feat(prompts): 提示词注册表 + resolve_prompt（默认强制亚洲中国面孔）"
```
结尾加 Co-Authored-By 行。

---

## Task 3: stage2_script 接入解析器 + 删死代码

**Files:**
- Modify: `backend/app/pipeline/stage2_script.py`
- Test: `backend/tests/test_stage2_multi.py`（追加 1 个覆盖断言）

- [ ] **Step 1: 写失败测试** — 追加到 `backend/tests/test_stage2_multi.py`（顶部已有 `import json`/`AsyncMock`/`pytest`/`RawArticleData`）：

```python
from app import config
from app.pipeline.stage2_script import _gen_article_scenes


@pytest.mark.asyncio
async def test_gen_article_scenes_uses_prompt_override(monkeypatch):
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"roundup_article": "MY_OVERRIDE_PROMPT"}))
    tp = AsyncMock()
    tp.generate.return_value = json.dumps({"scenes": [{"narration": "x", "image_prompt": "p", "motion_prompt": "m", "duration_hint": 5}]})
    art = RawArticleData(title="t", content="c", source_url="u", source_name="s")
    await _gen_article_scenes(art, tp)
    assert tp.generate.call_args.kwargs["system_prompt"] == "MY_OVERRIDE_PROMPT"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_stage2_multi.py::test_gen_article_scenes_uses_prompt_override -v`
Expected: FAIL（仍用模块常量，不等于 override）

- [ ] **Step 3: 实现** — 在 `backend/app/pipeline/stage2_script.py`：

(a) 顶部 import 加：`from app.prompts import resolve_prompt`

(b) 删除这些**死代码/已迁移常量**及函数：
- `SCRIPT_SYSTEM_PROMPT = """..."""`（约 9-33 行）
- `DAILY_DIGEST_SYSTEM_PROMPT = """..."""`（约 35-60 行）
- `async def run_stage2(...)` 整个函数（约 63-103 行）
- `ROUNDUP_ARTICLE_SYSTEM_PROMPT`、`DAILY_BATCH_SYSTEM_PROMPT`、`SUMMARY_META_SYSTEM_PROMPT`、`WEEKLY_DIGEST_SYSTEM_PROMPT` 四个常量定义（约 106-123 行）

(c) 4 处调用改用解析器：

`_gen_article_scenes` 内：
```python
    resp = await tp.generate(prompt=prompt, system_prompt=resolve_prompt("roundup_article"))
```
`_gen_daily_batch_scenes` 内：
```python
    resp = await tp.generate(prompt="本组资讯：\n" + "\n".join(lines), system_prompt=resolve_prompt("daily_batch"))
```
`_gen_summary_meta` 内：
```python
    resp = await tp.generate(prompt="各条资讯标题：\n" + "\n".join(f"- {t}" for t in titles), system_prompt=resolve_prompt("summary_meta"))
```
`distill_weekly_sections` 内（原 `system_prompt=WEEKLY_DIGEST_SYSTEM_PROMPT`）：
```python
        resp = await text_provider.generate(
            prompt="本周资讯条目：\n" + text, system_prompt=resolve_prompt("weekly_digest"))
```

- [ ] **Step 4: 跑测试确认通过 + 无回归**

Run: `cd backend && pytest tests/test_stage2_multi.py -v`
Expected: PASS（含原有用例 + 新 override 用例）

- [ ] **Step 5: 提交**

```bash
git add backend/app/pipeline/stage2_script.py backend/tests/test_stage2_multi.py
git commit -m "refactor(prompts): stage2 接入 resolve_prompt 并删死代码 run_stage2"
```
结尾加 Co-Authored-By 行。

---

## Task 4: runner 摘要 / scoring / api 接入解析器

**Files:**
- Modify: `backend/app/pipeline/runner.py`（`_summarize_articles`，约 168-171 行）
- Modify: `backend/app/services/scoring.py`（删 `SCORING_SYSTEM_PROMPT`，第 217 行用法改解析器）
- Modify: `backend/app/api/pipeline.py`（regen-prompt 第 515 行；add-scene 第 552/555 行的 `ROUNDUP_ARTICLE_SYSTEM_PROMPT`）
- Test: `backend/tests/test_prompts.py`（追加）

- [ ] **Step 1: 写失败测试** — 追加到 `backend/tests/test_prompts.py`：

```python
def test_scoring_uses_resolver(monkeypatch):
    import app.services.scoring as scoring
    monkeypatch.setattr(config, "_settings", config.Settings(prompts={"news_scoring": "SCORE_OVERRIDE"}))
    from app.prompts import resolve_prompt
    assert resolve_prompt("news_scoring") == "SCORE_OVERRIDE"
    # scoring 模块不应再有硬编码常量
    assert not hasattr(scoring, "SCORING_SYSTEM_PROMPT")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_prompts.py::test_scoring_uses_resolver -v`
Expected: FAIL（`scoring.SCORING_SYSTEM_PROMPT` 仍存在）

- [ ] **Step 3: 实现**

`backend/app/services/scoring.py`：删除整个 `SCORING_SYSTEM_PROMPT = """..."""` 定义（其文本已搬入 `prompts.py`）；第 217 行
```python
            system_prompt=SCORING_SYSTEM_PROMPT,
```
改为：
```python
            system_prompt=resolve_prompt("news_scoring"),
```
文件顶部 import 加 `from app.prompts import resolve_prompt`。

`backend/app/pipeline/runner.py` 的 `_summarize_articles`（168-171 行）：
```python
async def _summarize_articles(articles, cfg, run, db, log):
    tp = _build_summary_provider(cfg)
    max_len = cfg.summary.max_length
    sys_prompt = f"用中文为新闻文章生成简洁摘要，不超过{max_len}字。只输出摘要文本。"
```
改为：
```python
async def _summarize_articles(articles, cfg, run, db, log):
    from app.prompts import resolve_prompt
    tp = _build_summary_provider(cfg)
    max_len = cfg.summary.max_length
    sys_prompt = resolve_prompt("article_summary") + f"（摘要不超过{max_len}字）"
```

`backend/app/api/pipeline.py` regen-prompt（515 行）：
```python
    system = "你是一个视频图片提示词专家。根据旁白文本生成一段详细的AI图片生成提示词（英文），描述一张能够配合旁白内容的画面。只输出提示词本身，不要其他内容。"
```
改为：
```python
    from app.prompts import resolve_prompt
    system = resolve_prompt("image_regen")
```

`backend/app/api/pipeline.py` add-scene（552/555 行）：
```python
    from app.pipeline.stage2_script import ROUNDUP_ARTICLE_SYSTEM_PROMPT, _parse_json
    ...
    resp = await tp.generate(prompt=prompt, system_prompt=ROUNDUP_ARTICLE_SYSTEM_PROMPT)
```
改为：
```python
    from app.pipeline.stage2_script import _parse_json
    from app.prompts import resolve_prompt
    ...
    resp = await tp.generate(prompt=prompt, system_prompt=resolve_prompt("roundup_article"))
```

- [ ] **Step 4: 跑测试确认通过 + import 健全**

Run: `cd backend && python -c "import app.services.scoring, app.api.pipeline, app.pipeline.runner" && pytest tests/test_prompts.py -v`
Expected: 导入无错；测试 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/scoring.py backend/app/pipeline/runner.py backend/app/api/pipeline.py backend/tests/test_prompts.py
git commit -m "refactor(prompts): runner摘要/scoring/api图片提示词 接入 resolve_prompt"
```
结尾加 Co-Authored-By 行。

---

## Task 5: settings API — prompts 不脱敏 + defaults 端点

**Files:**
- Modify: `backend/app/api/settings.py`
- Test: `backend/tests/test_api_settings_prompts.py`（新建）

- [ ] **Step 1: 写失败测试** — 新建 `backend/tests/test_api_settings_prompts.py`：

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.main import create_app
from app.models import Base  # noqa: F401
from app import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 用临时 config.yaml，且清空缓存让 get_settings 重新加载
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config, "_settings", None)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sf = sessionmaker(bind=engine)
    app = create_app()
    Base.metadata.create_all(engine)

    def override_get_db():
        s = sf()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_prompt_defaults_endpoint(client):
    r = client.get("/api/settings/prompts/defaults")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 7
    assert "label" in data["roundup_article"] and "default" in data["roundup_article"]


def test_put_prompts_roundtrip_keeps_ellipsis(client):
    # 提示词里允许含 "..."（不能被脱敏跳过逻辑误伤）
    r = client.put("/api/settings/", json={"prompts": {"summary_meta": "标题...简介"}})
    assert r.status_code == 200
    got = client.get("/api/settings/").json()
    assert got["prompts"]["summary_meta"] == "标题...简介"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_api_settings_prompts.py -v`
Expected: FAIL（无 defaults 端点；且 PUT 的 `...` 值被跳过）

- [ ] **Step 3: 实现** — 在 `backend/app/api/settings.py`：

顶部 import 加：`from app.prompts import PROMPTS`

在 `update_settings` 里把跳过 `...` 的逻辑限定为**仅密钥组**。当前：
```python
        if isinstance(group_val, dict) and group_key in current:
            for k, v in group_val.items():
                if isinstance(v, str) and "..." in v:
                    continue
                current[group_key][k] = v
```
改为：
```python
        if isinstance(group_val, dict) and group_key in current:
            secret_group = group_key in ("text", "image", "tts", "collectors", "youtube")
            for k, v in group_val.items():
                if secret_group and isinstance(v, str) and "..." in v:
                    continue  # 跳过未改动的脱敏密钥
                current[group_key][k] = v
```

在文件末尾加 defaults 端点：
```python
@router.get("/prompts/defaults")
async def prompt_defaults():
    return {p.key: {"label": p.label, "desc": p.desc, "default": p.default} for p in PROMPTS}
```

> `_redact` 不涉及 prompts，无需改（prompts 非密钥，原样返回）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_api_settings_prompts.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/settings.py backend/tests/test_api_settings_prompts.py
git commit -m "feat(prompts): settings prompts 不脱敏 + GET prompts/defaults 端点"
```
结尾加 Co-Authored-By 行。

---

## Task 6: 前端「提示词」区

**Files:**
- Modify: `frontend/src/api/client.ts`（`AppSettings` 约 16-25 行；`settings` 对象约 165-170 行）
- Modify: `frontend/src/pages/Settings.tsx`（`EMPTY_SETTINGS` 242 行；新增 Section）

- [ ] **Step 1: client.ts — 类型与 API**

`AppSettings` 接口加一行（在 `ltx: {...}` 后）：
```ts
  prompts: Record<string, string>;
```
`api.settings` 对象里加 `promptDefaults`（在 `save` 后）：
```ts
    promptDefaults: () => fetchJSON<Record<string, { label: string; desc: string; default: string }>>("/settings/prompts/defaults"),
```

- [ ] **Step 2: Settings.tsx — EMPTY_SETTINGS**

`EMPTY_SETTINGS` 对象末尾（`ltx: {...}` 后）加：
```ts
  prompts: {},
```

- [ ] **Step 3: Settings.tsx — 「提示词」Section**

在 `SettingsPage` 组件内、`return (` 之前加载默认：
```tsx
  const { data: promptDefs } = useSWR("prompt-defaults", api.settings.promptDefaults);
```
在 return 的 JSX 里（如「LTX-2.3 视频生成」Section 之后）加一段：
```tsx
      <Section title="提示词" desc="流水线各步骤的 AI 提示词；留空使用内置默认。改后点上方「保存」。">
        {promptDefs && Object.entries(promptDefs).map(([key, def]) => (
          <div key={key} className="mb-4">
            <div className="flex items-center justify-between mb-1">
              <label className="text-sm text-white/70">{def.label}<span className="text-white/30 text-xs ml-2">{def.desc}</span></label>
              <button
                onClick={() => patch("prompts", { [key]: "" })}
                className="text-xs text-white/30 hover:text-white/60 transition"
              >恢复默认</button>
            </div>
            <textarea
              value={settings.prompts?.[key] ?? ""}
              placeholder={def.default}
              onChange={(e) => patch("prompts", { [key]: e.target.value })}
              rows={6}
              className="w-full bg-white/[0.03] border border-white/[0.08] rounded-lg px-3 py-2 text-xs text-white/80 font-mono leading-relaxed resize-y focus:outline-none focus:border-blue-400/40"
            />
          </div>
        ))}
      </Section>
```
> `patch` 已是 `<G extends keyof AppSettings>(group, partial)`；`patch("prompts", {[key]: value})` 成立（`prompts` 是 `Record<string,string>`）。空值即「用默认」，placeholder 显示内置默认全文。

- [ ] **Step 4: 构建校验**

Run: `cd frontend && pnpm build`
Expected: 构建成功，无 TS 错误。（若 `patch("prompts", ...)` 类型报错，确认 `AppSettings.prompts` 已声明为 `Record<string,string>`。）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/client.ts frontend/src/pages/Settings.tsx
git commit -m "feat(prompts): 前端 Settings 新增可编辑「提示词」区"
```
结尾加 Co-Authored-By 行。

---

## 收尾验证

- [ ] **全量后端测试**：`cd backend && pytest -q`（除既有 2 个预存失败外全绿）
- [ ] **前端构建**：`cd frontend && pnpm build`
- [ ] **手动冒烟（用户自行，勿代启后端）**：Settings 页「提示词」区可见 7 个提示词、能编辑/恢复默认/保存；跑一条普通源任务确认旁白通俗中文、image_prompt 为英文且画面为亚洲/中国人与中式场景。
