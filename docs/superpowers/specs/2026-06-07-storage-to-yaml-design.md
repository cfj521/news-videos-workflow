# 实体存储 DB → YAML 文件 设计

> 状态：已批准，待写实现计划

## 目标

把账号/凭证类实体从数据库迁到版本可控、重建不丢的 YAML 文件，并规范化 `config.yaml` 命名与分组。动机：DB 在 WSL/Docker 卷里，重建会丢；YAML 文件持久、可备份。

## 范围

从 DB / 旧 config.yaml 迁出，落成独立文件：

- **信息源**（`NewsSource` 表）→ `news_sources.yaml`
- **发布账号**（`PublishTarget` 表）→ `publish_targets.yaml`
- **OpenAI 订阅凭证**（`OAuthCredential` 表）→ 并入 `model_providers.yaml`
- **供应商凭证 + 模型列表**（旧 config.yaml `providers` 块）→ `model_providers.yaml`
- **搜索 key**（旧 config.yaml `collectors`）→ `news_sources.yaml`
- **YouTube OAuth client**（旧 config.yaml 顶层 `youtube`）→ `publish_targets.yaml`

**不迁**：`OAuthLoginSession`（登录握手临时态，跨进程共享，留 DB）；其余流水线数据（runs/articles/scripts/...）。

## 关键决策（已与用户确认）

1. **ID 方案**：改用语义 **slug** 作 YAML key（替代 DB 自增整数主键）。
2. **CRUD**：「信息源管理」「发布管理」页面继续读写，改为写 YAML 文件（文件版 CRUD）。
3. **零散 key**：按域归位（搜索 key → news_sources.yaml；YouTube client → publish_targets.yaml）。
4. **存储层架构**：按域 typed store + 共享原子 IO 助手（方案 A）。

## 文件最终结构

### `config.yaml`（瘦身，纯设置，无密钥/账号）

```yaml
infra: {database_url, data_dir}
storage: {work_dir, output_dir}
pipeline: {选型 + 默认值}      # summary/script/image/vision/tts 选型, 时间范围, 图片数...
video: {...}
comfyui: {...}
prompts: {...}
```

移除：`providers`、`collectors`、`youtube`、**废弃的 `claude` 块**。

### `model_providers.yaml`

```yaml
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: ''
    auth_mode: api_key           # api_key | subscription
    max_output_tokens: 65535
    models: {text: [], image: [], vision: [], tts: []}
    oauth:                       # 仅 auth_mode=subscription 时有意义
      access_token: ''
      refresh_token: ''
      id_token: ''
      account_id: ''
      expires_at: ''             # ISO8601
      plan_type: ''
      account_email: ''
      last_refresh: ''
  dashscope: {...}
  edge-tts: {...}
```

OAuth 凭证内嵌到所属 provider（openai）下。

### `news_sources.yaml`

```yaml
search_keys: {tavily: '', brave: '', serper: ''}    # 原 collectors
sources:
  hacker_news:                                       # slug 作 key
    name: Hacker News
    type: ...
    url: ...
    category: general
    language: en
    priority: 5
    enabled: true
    tier: free
    pinned: false
    config: {}                                       # 原 config_json → 内联 dict
```

### `publish_targets.yaml`

```yaml
youtube_oauth_client: {client_id: '', client_secret: ''}   # 原顶层 youtube
targets:
  youtube_main:                                            # slug 作 key
    name: YouTube
    platform: youtube
    enabled: true
    config: {client_id: '', client_secret: '', refresh_token: '', ...}
```

## 架构

### 存储层 `backend/app/store/`

- **`_io.py`**：`load_yaml(path)` / `atomic_write_yaml(path, data)`（临时文件 + `os.replace` 原子写）+ 每文件 `threading.Lock` 防交错。
- **`providers_store.py`**：读写 `model_providers.yaml`；供 `config.resolve()` / `provider_creds()` 取用；OAuth 读写。
- **`sources_store.py`**：`list / get / create / update / delete / batch` + `search_keys` 访问器。
- **`targets_store.py`**：`list / get / create / update / delete` + `youtube_oauth_client` 访问器。
- 全部用 pydantic 模型校验。API 层改调 store，不再碰 DB。

并发：后端当前单进程（uvicorn + 单 worker 串行执行器），`threading.Lock` + 原子写足够，无需跨进程锁。

### slug 与历史兼容

- slug 作 YAML key；create 时可显式传，缺省按 name 生成（英文 slugify：小写、非字母数字转 `_`；中文名生成空 → 回退 `{platform|type}_{序号}`），并查重保证唯一。
- **新任务** `run.source_ids`（信息源选择）和 `run.publish_platforms`（发布账号选择）均存 slug 列表（字符串 JSON）。
- **历史任务**：一次性迁移时分别构建信息源 `旧 int_id → slug` 与发布账号 `旧 int_id → slug` 映射，改写已有 run 的 `source_ids` 与 `publish_platforms`；映射不到的条目原样保留（仅影响旧任务展示）。
- runner 中 `target_ids` 取数（`json.loads(run.publish_platforms)` + `int(x)`）改为 slug 字符串集合，`build_publishers` 取数改走 `targets_store`。

### OAuth 文件版

- `openai_oauth.py` 的 `get_valid_access_token()` 等改为读写 `providers_store` 的 oauth，**不再要 `db` 参数**；`_refresh_lock` 保留，刷新后写回文件。
- 调用方（providers、api）去掉 db 传参。
- `OAuthLoginSession` 仍走 DB。

### 一次性 DB→YAML 迁移

- 启动时（`main.py` lifespan）：若某 YAML 文件不存在，用**原生 `sqlite3`** 直接读旧表导出生成（不依赖 ORM，因模型将被删）；表不存在 / 非 sqlite → 写默认空文件。
- 迁移完成后删除三个 ORM 模型（`NewsSource` / `PublishTarget` / `OAuthCredential`）及其 DB 用法。
- 幂等：YAML 文件已存在则跳过迁移。

## 前端

- `NewsSource.id` / `PublishTarget.id` 改 `string`（slug）。
- `CreateRunDialog`：去掉 `Number()`，id 用字符串；`effectiveSourceIds` / `effectiveTargetIds` 用 `Set<string>`。
- `Sources.tsx` / `Publishers.tsx`：CRUD、batch 改 slug。
- `api/client.ts`：sources / publishers CRUD 参数类型同步为 string id。

## 错误处理

- YAML 损坏/解析失败：加载抛明确错误（含文件路径），不静默吞。
- 原子写失败：保留原文件（temp 未 replace），抛错。
- slug 冲突：create/update 报 409 风格错误。
- OAuth 刷新失败：沿用现有 `NotLoggedInError` / 明确报错路径。

## 测试

- store 单测：round-trip load/save、原子写、slug 生成与查重、CRUD、batch。
- 迁移单测：临时 sqlite 种子 → 断言生成的 YAML 内容 + run.source_ids / run.publish_platforms 改写。
- API 测试：sources / publishers 改 slug id。
- OAuth 文件版测试：读写/刷新写回。
- 现有 304 测试中受影响处一并改。

## 受影响文件（概览）

**新增**：`backend/app/store/{_io,providers_store,sources_store,targets_store}.py`、三个 YAML（运行时生成）、对应测试。

**修改**：`config.py`（providers 移出、resolve 改读 store）、`api/sources.py`、`api/publishers.py`、`api/openai_oauth.py`、`oauth/openai_oauth.py`、`pipeline/runner.py`（_collectors_for_run、build_publishers 取数改 store）、`pipeline/engine.py`、`main.py`（lifespan 迁移 + 去除三模型建表）、`schemas/{source,publish_target}.py`、前端 `types/index.ts`、`api/client.ts`、`components/CreateRunDialog.tsx`、`pages/{Sources,Publishers}.tsx`。

**删除**：`models/{news_source,publish_target,oauth_credential}.py` 中的迁出表（保留 `OAuthLoginSession`）。
