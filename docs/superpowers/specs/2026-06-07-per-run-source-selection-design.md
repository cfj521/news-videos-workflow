# 按任务选择信息源 + 任务窗口双列布局 设计

日期：2026-06-07

## 背景与目标

当前信息源的「用不用」由**信息源管理页的 `enabled` 开关**决定，`execute_pipeline` 采集时查所有
`enabled` 的源（runner.py:481）。新建任务窗口只读展示 `SourceSummary`，不参与选择。

改为：**信息源管理页只提供「可选项」，具体某次任务用哪些源由新建任务窗口选定**；任务窗口改为
**flex 双列布局**。

## 已确认决策

1. `enabled` 语义保留为「**是否作为可选项**」——只有 enabled 的源出现在任务窗口的可选列表里。
2. 任务窗口里信息源**默认选中**：因 AI HOT 与其他组互斥（见 6），默认规则为——
   **可用源含 AI HOT → 默认仅选 AI HOT**（贴合旧行为「有 AI HOT 即只用 AI HOT」）；
   **否则默认全选**所有可用（常规）源。
3. 所选信息源**存到该任务**（`PipelineRun.source_ids`），供重采集/复现一致。
4. 双列分区：**左** = 信息源 / 执行阶段 / 发布账号；**右** = 运行模式·路线 / 分辨率·语言 /
   最多图片数 / 采集方式 / 时间·文章数。
5. 信息源 tab 改名「**信息源管理**」。
6. 任务窗口的信息源选择做 **AI HOT ↔ 其他组互斥**（交互式）：选中 AI HOT 即清空其他源；
   选中任一常规源即清空 AI HOT。与后端 `build_collectors_from_db` 的互斥兜底一致。
7. 信息源页：**CRUD（增删改）保持不变**；该页不再承担「设定当前生效源」的职责（移到任务窗口），
   `enabled` 仅表示「是否作为可选项」。移除代表旧「当前生效源」的只读组件 `SourceSummary`。
   采集只依据 `run.source_ids`，不再读全局 enabled（除回退）。

## 后端

### 1. 模型 `backend/app/models/pipeline_run.py`
- 新增 `source_ids: Mapped[str | None] = mapped_column(Text, nullable=True)`：JSON 数组（所选
  NewsSource id）。`None`/空 = 未指定（回退）。

### 2. 启动迁移 `backend/app/main.py::_ensure_pipeline_run_columns`
- `needed` 字典加 `"source_ids": "TEXT"`（SQLite 手动 ALTER；`create_all` 不会给已存在表补列）。

### 3. schema `backend/app/schemas/pipeline.py`
- `PipelineRunCreate` 加 `source_ids: list[int] | None = None`。
- `PipelineRunRead` 加 `source_ids: str | None`。

### 4. `backend/app/pipeline/engine.py::create_run`
- 入参加 `source_ids: list[int] | None = None`；存为 `json.dumps(source_ids)`（None 存 None）。

### 5. `backend/app/api/pipeline.py::create_run`
- 透传 `body.source_ids` 给 `engine.create_run`。

### 6. 采集改按任务所选源 `backend/app/pipeline/runner.py`（约 line 481）
新增一个解析函数（runner 内，便于复用与单测）：
```python
def _sources_for_run(db, run):
    """按 run.source_ids 取 NewsSource；为空/无则回退所有 enabled。"""
    from app.models.news_source import NewsSource
    ids = []
    if getattr(run, "source_ids", None):
        try:
            ids = json.loads(run.source_ids) or []
        except Exception:
            ids = []
    if ids:
        rows = db.query(NewsSource).filter(NewsSource.id.in_(ids)).all()
        # 按 ids 给定顺序稳定排序（可选）
        return rows
    return db.query(NewsSource).filter(NewsSource.enabled.is_(True)).all()
```
把 line 481 的 `db_sources = db.query(NewsSource).filter(NewsSource.enabled.is_(True)).all()`
改为 `db_sources = _sources_for_run(db, run)`。其余（build_collectors_from_db 互斥、空则
build_collectors 默认 HN）不变。

### 7. 重采集 `backend/app/api/pipeline.py::_reroll_articles_async`（约 line 608）
- 把 `db.query(NewsSource).filter(NewsSource.enabled == True).all()` 改为复用
  `runner._sources_for_run(db, run)`，保证与首次采集同一组源。同时去掉 ruff E712（用
  `_sources_for_run` 后该行消失）。

### AI HOT 互斥
`build_collectors_from_db` 已对传入列表做「有 AI HOT 即只用 AI HOT」。改传「所选源」后该逻辑
自动作用于所选集，无需改动。

## 前端

### 1. `frontend/src/api/client.ts`
- `api.runs.create` 入参类型加 `source_ids?: number[]`。
- `PipelineRun` 类型加 `source_ids?: string | null`（如其它字段需要）。

### 2. `frontend/src/components/CreateRunDialog.tsx`
- **信息源选择**：可勾选列表（复用现有 checkbox 列表样式）列出**可用源**
  （`sources.filter(s => s.enabled)`），每项显示名称 + 类型/AI HOT method 提示。
- 状态 `sourceIds: Set<number> | null`，`null = 用默认规则`。`effectiveSourceIds` 解析：
  - `null` 时：可用源含 AI HOT → 仅 AI HOT 的 id；否则全部可用 id（决策 2）。
  - 非 null 时：用户的显式选择（与可用集求交，过滤已失效 id）。
- **AI HOT ↔ 其他组互斥**（决策 6）`toggleSource(id)`：以 `effectiveSourceIds` 为基准 toggle 后，
  若新选中的是 AI HOT → 结果只保留 AI HOT；若新选中的是常规源 → 结果剔除所有 AI HOT。
  （即任一时刻 selected 要么全是 AI HOT、要么全是常规。）
- AI HOT 相关推导（`aihotSource` / `aihotMethod` / `isAihotDigest`，决定是否隐藏时间/文章数）
  改为基于 `effectiveSourceIds` 对应的源，而非全部 enabled。
- 移除只读 `SourceSummary` 的使用（组件文件可留作他用或删除——本任务仅从弹窗移除引用）。
- 提交 `handleSubmit` 带 `source_ids: Array.from(effectiveSourceIds)`。
- **双列 flex 布局**：弹窗宽度约 `720px`；外层 `flex gap-5`，左右两 `flex-1` 列：
  - 左列：信息源选择 → 执行阶段 → 发布账号（stage6 时）。
  - 右列：运行模式·路线（grid-2）→ 分辨率·语言（grid-2）→ 最多图片数 → 采集方式 → 时间·文章数。
  - 底部「取消/创建」按钮横跨整宽。
- 空可用源时：左列信息源区显示提示「请先到『信息源管理』启用信息源」；创建仍允许（后端回退默认 HN）。

### 3. 信息源页 `frontend/src/pages/Sources.tsx`
- 保留 `enabled` 开关；其文案/说明微调为「是否作为新建任务的可选信息源」。

### 4. 导航改名
- 「信息源」tab → 「信息源管理」（改 `frontend/src/App.tsx` 或导航定义处的 label；功能/路由不变）。

## 边界与回退
- 旧任务（无 `source_ids` 列值）：`_sources_for_run` 回退到 enabled 源 → 行为不变。
- 任务选了源但这些源后来被删：`NewsSource.id.in_(ids)` 只返回仍存在的；全没了则该次采集可能 0 篇
  （沿用现有「0 篇」提示逻辑）。
- AI HOT digest（daily/weekly）模式仍隐藏时间/文章数字段，基于所选源判断。

## 测试
- 后端单测 `_sources_for_run`：给定 run.source_ids → 只返回这些；空 → 回退 enabled。
- 后端：`create_run` 存 source_ids（API 测试 patch `_run_pipeline_bg` 已有，扩展断言 source_ids 落库）。
- 前端：`pnpm build` 通过（无强制单测）。

## 不做（YAGNI）
- 不做「记住上次所选源」（默认按决策 2 规则即可）。
- 不改信息源的增删改（CRUD）逻辑（仅语义/文案 + 移除只读 SourceSummary）。
