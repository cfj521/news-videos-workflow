# 可编辑提示词 + 接地气脚本 — 设计文档

## 背景与目标

流水线里的 AI 提示词目前全是 Python 模块常量，无法在页面查看/调整。本设计：

1. 把流水线实际使用的提示词**显性放到 Settings 页，可编辑**（全局默认，改一次对所有任务生效，可恢复默认）。
2. 改写默认内容，让生成的脚本**通俗易懂、减少英文、用亚洲/中国人面孔与中式场景**。

## 现状勘察结论

- 提示词为模块常量，分布在 `stage2_script.py`、`api/pipeline.py`（图片提示词 regen）、`runner.py`（摘要）、`services/scoring.py`（评分）。
- 设置体系现成：`Settings`(pydantic) → YAML 配置（`get_settings`/`save_settings`），前端 Settings 页经 `/api/settings`（GET 脱敏 / PUT 部分合并）读写。
- **`run_stage2`（单篇）在主流程无人调用** → `SCRIPT_SYSTEM_PROMPT`、`DAILY_DIGEST_SYSTEM_PROMPT` 是死代码（主路径只用 `run_stage2_multi`）。

## 关键决策

- **D1 放置/范围**：Settings 页新增「提示词」区，**全局默认**（不做 per-run 覆盖，YAGNI）。
- **D2 暴露范围**：暴露流水线**实际在用**的全部提示词（7 个，见下）；不暴露死代码提示词。
- **D3 存储**：`PromptsCfg`，每提示词一个 `str = ""` 字段；**空 = 用内置默认**；用户填了即覆盖；「恢复默认」= 清空。YAML 只存覆盖项，内置默认留在代码里（升级可自动生效）。
- **D4 画面描述语言**：`image_prompt` / `motion_prompt`（喂图片/视频模型）**保留英文**（模型顺从性更好），但强制 `Asian / Chinese` 人物与中式场景；其余（旁白、标题、简介、提炼、摘要、评分及提示词内的指令）尽量中文、通俗。
- **D5 清理**：删除死代码 `run_stage2` 及 `SCRIPT_SYSTEM_PROMPT`、`DAILY_DIGEST_SYSTEM_PROMPT`（避免注册表混入用不上的提示词）。

## 暴露的 7 个提示词

| key | 中文标题 | 用途 | 出处（现） |
|---|---|---|---|
| `roundup_article` | 资讯分镜（单条） | 多篇/每条资讯 → 1~3 分镜（旁白+画面） | `ROUNDUP_ARTICLE_SYSTEM_PROMPT` |
| `daily_batch` | 日报/周报分镜（成组） | 同类目若干条 → 每条 1 分镜 | `DAILY_BATCH_SYSTEM_PROMPT` |
| `summary_meta` | 汇总标题/简介 | 整片标题、简介、标签 | `SUMMARY_META_SYSTEM_PROMPT` |
| `weekly_digest` | 周报主题提炼 | 一周条目 → 3~5 主题 | `WEEKLY_DIGEST_SYSTEM_PROMPT` |
| `image_regen` | 旁白→图片提示词 | 单分镜重生成图片提示词 | `api/pipeline.py` regen-prompt 的 `system` |
| `article_summary` | 文章摘要（普通源） | 采集后摘要 | `runner._summarize_articles` 内联 |
| `news_scoring` | 新闻评分（普通源） | 评分排序 | `scoring.py` `SCORING_SYSTEM_PROMPT` |

> 内容改写主要落在 `roundup_article` / `daily_batch` / `image_regen`（它们产出 narration + image_prompt + motion_prompt）。

## 详细设计

### 1. 提示词注册表 — 新建 `backend/app/prompts.py`

```python
@dataclass(frozen=True)
class PromptDef:
    key: str
    label: str        # 中文标题
    desc: str         # 中文说明
    default: str      # 内置默认（已按 D4 改写）

PROMPTS: list[PromptDef] = [ ... 7 条 ... ]
DEFAULTS: dict[str, str] = {p.key: p.default for p in PROMPTS}
```

默认文本从现有常量迁来并改写：
- `roundup_article` / `daily_batch`：旁白要求"口语化、通俗易懂的中文，避免生僻词与不必要英文"；`image_prompt`/`motion_prompt`要求"English；必须是 Asian / Chinese 人物、东亚面孔、中式真实场景/背景；避免欧美面孔"。
- `image_regen`：英文图片提示词，同样强制 Asian/Chinese 人物与中式场景。
- `summary_meta`/`weekly_digest`/`article_summary`/`news_scoring`：中文、简洁（沿用原意，措辞中文化）。

### 2. 配置 — `backend/app/config.py`

```python
class PromptsCfg(BaseModel):
    roundup_article: str = ""
    daily_batch: str = ""
    summary_meta: str = ""
    weekly_digest: str = ""
    image_regen: str = ""
    article_summary: str = ""
    news_scoring: str = ""

class Settings(BaseModel):
    ...
    prompts: PromptsCfg = PromptsCfg()
```

解析器（放 `prompts.py` 或 `config.py`）：

```python
def resolve_prompt(key: str) -> str:
    cfg = get_settings()
    return (getattr(cfg.prompts, key, "") or "").strip() or DEFAULTS[key]
```

### 3. 调用点改造

- `stage2_script.py`：`_gen_article_scenes` 用 `resolve_prompt("roundup_article")`；`_gen_daily_batch_scenes` 用 `daily_batch`；`_gen_summary_meta` 用 `summary_meta`；`distill_weekly_sections` 用 `weekly_digest`。删除 `run_stage2` + `SCRIPT/DAILY_DIGEST` 常量。
- `api/pipeline.py` regen-prompt：`system = resolve_prompt("image_regen")`。
- `runner._summarize_articles`：`sys_prompt = resolve_prompt("article_summary")`（注意原 prompt 含 `max_length` 变量——把长度要求作为可替换占位或在默认里写死/拼接，见 §边界）。
- `scoring.py`：`SCORING_SYSTEM_PROMPT` → `resolve_prompt("news_scoring")`。

### 4. API — `backend/app/api/settings.py`

- `prompts` 组随现有 GET/PUT 流转；`_redact` **不**脱敏 prompts（非密钥）。
- 新增只读端点 `GET /api/settings/prompts/defaults` → 返回 `{key: {label, desc, default}}`，供前端展示说明 + 「恢复默认」回填。

### 5. 前端 — `frontend/src/pages/Settings.tsx` + `api/client.ts`

- `AppSettings` 增加 `prompts: Record<string,string>`；`api.settings.promptDefaults()` 拉默认。
- 新增可折叠「提示词」区：遍历默认表，每项渲染 中文标题 + 说明 + `<textarea>`（值=覆盖值；为空时以默认文本作 placeholder 或灰显）+ 「恢复默认」按钮（把该字段清空/回填默认文本）。随现有「保存」走 PUT。

## 数据流

```
页面编辑 prompts → PUT /api/settings → PromptsCfg 存 YAML
流水线运行 → resolve_prompt(key) → 覆盖值 or 内置默认 → 传给 text provider
```

## 边界与错误处理

- **空白/空格**：`resolve_prompt` 对纯空白也回退默认。
- **`article_summary` 的长度变量**：原 prompt 内嵌 `cfg.summary.max_length`。改造保留该约束——默认文本里写"不超过约定字数"，运行时把 `max_length` 以固定后缀拼到系统提示（不依赖用户在自定义里保留占位符），避免用户改坏。
- **升级安全**：用户没覆盖的提示词随版本升级自动拿到新默认（因为存的是 ""）。
- **死代码删除**：确认 `run_stage2` 无引用后再删（已核实 grep 无调用）。

## 测试计划

- `resolve_prompt`：覆盖值优先；空/空白 → 默认；未知 key 行为（KeyError 或默认空，明确其一）。
- 默认内容守卫：断言 `roundup_article`/`daily_batch`/`image_regen` 默认文本含 "Asian"/"Chinese" 关键字（防止以后被无意改回欧美默认）。
- 设置 PUT 往返：写入 prompts 后 GET 能取回；空字段 GET 返回空（前端据此显示默认）。
- `GET /api/settings/prompts/defaults` 返回 7 条、含 label/desc/default。
- 回归：stage2_multi / weekly distill / scoring / summary 在默认（未覆盖）下行为与改造前一致（除措辞）。

## 影响文件

- 新增 `backend/app/prompts.py`（注册表 + DEFAULTS + resolve_prompt）
- `backend/app/config.py`（`PromptsCfg` + 接入 `Settings`）
- `backend/app/pipeline/stage2_script.py`（4 处改 resolver；删死代码）
- `backend/app/api/pipeline.py`（image_regen 改 resolver）
- `backend/app/pipeline/runner.py`（article_summary 改 resolver）
- `backend/app/services/scoring.py`（news_scoring 改 resolver）
- `backend/app/api/settings.py`（不脱敏 prompts + defaults 端点）
- `frontend/src/api/client.ts`（AppSettings.prompts + promptDefaults）
- `frontend/src/pages/Settings.tsx`（「提示词」区）
- 测试：`backend/tests/` 新增 resolver/defaults/settings 用例
