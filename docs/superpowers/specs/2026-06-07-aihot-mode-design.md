# AI HOT 硬编码 + 任务窗口信息源 2 选 1（AI HOT / 其他源）设计

日期：2026-06-07

## 背景与目标

上一特性把「用哪些信息源」移到了新建任务窗口（per-run `source_ids`）。现进一步：

- **AI HOT 实际是硬编码的 API + 规则**（collector 内已硬编码 URL），不需要作为可配置的信息源记录。
- 任务窗口的信息源选择改为 **AI HOT / 其他源 二选一**（互斥规则落实在创建窗口）。
- AI HOT 的配置项（method 动态/日报/周报 + 动态分类 / 日报日期 / 周报周）**从信息源页搬入任务窗口**。
- 信息源页**移除 AI HOT 卡片**，其他源保留 per-source enable + 顶部 master enable，**不再做互斥**。
- 「其他源」选择用**增强版折叠下拉**（全选/全不选 + 搜索 + 平铺 chip 布局）。

## 已确认决策

1. **run 编码**：新增 `PipelineRun.aihot_config`（JSON|None）。非空 = AI HOT 模式（含
   method/category/report_date/week_start）；为空 = 其他源模式（用 `source_ids`）。
2. **AI HOT 配置项**：全套搬入任务窗口（method + 动态分类 + 日报日期 + 周报周）。
3. **信息源页**：完全移除 AI HOT 卡片；后端停止 seed；前后端一律过滤 aihot 行（残留 seed 行不显示、
   不计入其他组、不参与采集）。AI HOT 完全硬编码、不在信息源页出现。
4. **任务窗口默认**：默认 AI HOT 模式、method=动态(items)。
5. **互斥落实在创建窗口**：信息源区为模式单选（AI HOT / 其他源），任意时刻只一个模式生效；提交时
   只带当前模式的数据（AI HOT → `aihot_config`；其他源 → `source_ids`）。后端按 `aihot_config`
   有无二分模式。信息源页彻底去互斥。
6. **其他源选择 UI**：增强版折叠下拉 —— 收起占一行（「已选 N/M」）；展开顶部「全选/全不选 + 计数」
   + 选项多时（>8）出现搜索框；选项区用 **flex-wrap chip 平铺**（点选切换、选中高亮）、可滚动。
   作为共享 `MultiSelect` 的 opt-in 变体，默认行为不变（发布账号沿用原列表样式）。

## AI HOT collector 现状（已核实）

`backend/app/providers/collector/aihot.py`：URL 全硬编码（`API=https://aihot.virxact.com/api/public`
等）；`collect()` 仅从 `source_config` 读 `method`（items/daily/weekly）、`category`（items）、
`report_date`（daily）、`week_start`（weekly）。即只需把这几个键 + name 喂给 collector 即可，
无需任何 DB 源记录。

## 后端

### 1. 模型 / 迁移 / schema
- `backend/app/models/pipeline_run.py`：加 `aihot_config: Mapped[str | None] = mapped_column(Text, nullable=True)`
  （JSON：`{method, category?, report_date?, week_start?}`；None = 其他源模式）。
- `backend/app/main.py::_ensure_pipeline_run_columns`：`needed` 加 `"aihot_config": "TEXT"`。
- `backend/app/schemas/pipeline.py`：`PipelineRunCreate` 加 `aihot_config: dict | None = None`；
  `PipelineRunRead` 加 `aihot_config: str | None`。

### 2. engine / api
- `engine.create_run`：加参数 `aihot_config: dict | None = None`；构造 `PipelineRun(...)` 加
  `aihot_config=json.dumps(aihot_config) if aihot_config else None`。
- `api/pipeline.py::create_run`：透传 `aihot_config=body.aihot_config`。

### 3. 采集：`_collectors_for_run(db, run)`（runner.py，替代采集点现有两步）
```python
def _aihot_source_config(aihot: dict) -> dict:
    """由 run.aihot_config 构造 AI HOT collector 的 source_config（URL 在 collector 内硬编码）。"""
    cfg = {"name": "AI HOT", "type": "aihot", "provider": "aihot"}
    for k in ("method", "category", "report_date", "week_start"):
        if aihot.get(k):
            cfg[k] = aihot[k]
    cfg.setdefault("method", "items")
    return cfg


def _collectors_for_run(db, run, settings) -> tuple[list[dict], dict]:
    """按 run 选模式返回 (source_configs, collectors)。
    - aihot_config 非空 → AI HOT 单源（硬编码）。
    - 否则 → run.source_ids 选中的非 aihot 源；空则 enabled 非 aihot；再空 → 默认 HN。
    """
    _ensure_collector_registry()
    raw = getattr(run, "aihot_config", None)
    if raw:
        try:
            aihot = json.loads(raw) or {}
        except Exception:
            aihot = {}
        if aihot:
            # 复用采集器注册表，避免直接依赖类名（与 build_collectors_from_db 一致）
            return [_aihot_source_config(aihot)], {"aihot": TYPE_TO_COLLECTOR["aihot"]()}
    db_sources = [s for s in _sources_for_run(db, run) if _resolve_collector_type(s) != "aihot"]
    if db_sources:
        return build_collectors_from_db(db_sources)
    return build_collectors(settings)
```
- `execute_pipeline` 采集点（约 line 481-488）：用 `source_configs, collectors = _collectors_for_run(db, run, cfg)`
  替换现有 `_sources_for_run` + `build_collectors_from_db` / `build_collectors` 分支。`digest_method`
  仍从 `source_configs` 推。
- `_reroll_articles_async`（api/pipeline.py）：同样改用 `_collectors_for_run(db, run, get_settings())`，
  保证重采集与首采一致。

### 4. seed 移除
- `backend/app/main.py`：移除 `_seed_aihot_source` 的调用（lifespan）与函数本体。残留 aihot 行靠
  过滤，不主动删（无害）。

## 前端

### 1. `frontend/src/api/client.ts`
- `runs.create` body 加：`aihot_config?: { method: string; category?: string; report_date?: string; week_start?: string };`

### 2. 增强 `frontend/src/components/MultiSelect.tsx`（opt-in，向后兼容）
新增可选 props（不传则行为完全不变）：
- `searchable?: boolean`（或内部当 `options.length > 8` 自动启用搜索框）。
- `selectAll?: boolean` + `allSelected?: boolean` + `onSelectAll?: (next: boolean) => void`：展开顶部
  渲染「全选/全不选 (N/M)」行。
- `variant?: "list" | "chips"`（默认 "list"）：`"chips"` 时下拉选项区用 `flex flex-wrap gap-2` 平铺
  chip，每项可点选切换；选中 = 蓝色填充，未选 = 灰描边。容器 `max-h` 可滚动。
- 收起摘要：选项多时显示「已选 N/M 个」（用 `selectAll`/`allSelected` 时带 M）。
说明：发布账号继续用默认（list、无 search/selectAll），不受影响。

### 3. `frontend/src/components/CreateRunDialog.tsx`
- 信息源区改为**模式单选**（seg/radio）：`sourceMode: "aihot" | "custom"`，默认 `"aihot"`。
- **AI HOT 模式**（`aihotCfg = { method, category, report_date, week_start }`，默认 `{method:"items"}`）：
  - method 段：动态/日报/周报。
  - 动态 → 分类下拉（`AIHOT_CATEGORIES`，从 Sources.tsx 迁来）；
    日报 → 日期下拉（`api.sources.aihotDays`）；周报 → 周下拉（`api.sources.aihotWeeks`）。
  - `isAihotDigest = sourceMode==="aihot" && aihotCfg.method ∈ {daily, weekly}` → 隐藏时间/文章数（沿用）。
- **其他源模式**：增强版 `MultiSelect`（`variant="chips"` + `searchable` + `selectAll`）列出可用
  （`enabled && !isAihotSource`）源；状态 `sourceIds: Set<number> | null`，`null = 全选可用`；
  无 AI HOT 互斥（模式单选已隔离）。移除原 `toggleSource` 的 AI HOT 互斥分支。
- 提交：`sourceMode==="aihot"` → `aihot_config: aihotCfg`（不带 source_ids）；
  `"custom"` → `source_ids: Array.from(effectiveSourceIds)`（不带 aihot_config）。
- 移除只读 `SourceSummary` 残留（若仍在）。

### 4. `frontend/src/pages/Sources.tsx`
- 移除 `AIHotGroupCard` 组件定义与渲染；移除 `AIHOT_CATEGORIES`（迁到 dialog）。
- 移除所有 AI HOT 互斥逻辑：`toggleSource` 不再联动关 AI HOT；`toggleAllCustom` 不再取反 AI HOT
  （纯批量开关）；清理 `aihotSource` 相关互斥代码。master enable 顶部开关保留为普通批量开关。
- 仍 `customSources = sorted.filter(s => !isAihotSource(s))`，残留 aihot 行不显示。
- master 开关 title/说明去掉「与 AI HOT 互斥」字样。

## 边界 / 迁移 / 测试
- 旧 run：仅 `source_ids` → custom 模式；两者皆无 → enabled 非 aihot → HN。
- 残留 seed 的 aihot NewsSource 行：前端过滤、后端 `_collectors_for_run` custom 分支过滤，不显示/不采集。
- 后端测试：
  - `_aihot_source_config`：method/category/report_date/week_start 透传，缺省 method=items。
  - `_collectors_for_run`：aihot_config 非空 → 返回 aihot 单源 + collector；为空 → custom 过滤 aihot；
    custom 空 → 默认 HN。
  - `create_run` 存 `aihot_config`（API 测试）。
- 前端：`pnpm build` 通过。

## 不做（YAGNI）
- 不主动删除残留 aihot DB 行（过滤即可）。
- 不给发布账号启用 chips/search/全选（保持现状，opt-in 不影响它）。
- 其他源组内不做互斥（仅 AI HOT↔其他源在窗口层面二选一）。
