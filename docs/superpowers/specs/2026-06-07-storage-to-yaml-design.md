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
- **PublishTarget.name 无唯一约束**（不同于 NewsSource.name），中文/同名账号常见 → slug 回退序号分支高频触发。序号规则：在已有 slug 集合内从 1 递增找到首个空位（`youtube_1`、`youtube_2`…）；迁移时按旧表 `id` 升序分配，保证可重复迁移序号稳定。
- **新任务** `run.source_ids`（信息源选择）和 `run.publish_platforms`（发布账号选择）均存 slug 列表（字符串 JSON）。
- **历史任务**：一次性迁移时分别构建信息源 `旧 int_id → slug` 与发布账号 `旧 int_id → slug` 映射，改写已有 run 的 `source_ids` 与 `publish_platforms`；映射不到的条目（源/账号已删）原样保留。
- runner 中 `target_ids` 取数（`json.loads(run.publish_platforms)` + `int(x)`）改为 slug 字符串集合，`build_publishers` 取数改走 `targets_store`。
- **降级语义（重要）**：reroll / 重跑历史任务时，`_sources_for_run` 按 slug 查 `sources_store`，映射不到的条目（旧 int_id 字符串或已删 slug）被跳过。若最终解析到的源为空，**不静默回退 HN**——`_collectors_for_run` 在「该 run 本有 source_ids 但全部失效」时应明确报错/提示「所选信息源已不存在，请重新选择」，区别于「从未选过源」的默认回退。

### OAuth 文件版

`oauth/openai_oauth.py` 中**所有**碰 `OAuthCredential` 的函数都改为读写 `providers_store` 的 oauth，**不再要 `db` 参数**：

- `get_valid_access_token()` — 临期比较改为解析 ISO8601 字符串 `expires_at`，不再依赖 SQLAlchemy `DateTime`。
- `store_tokens(tok)` — 被 `handle_callback` 调用，写 token。
- `get_status()` — 被 `api/openai_oauth.py` 调用。
- `logout()` — 清空 provider 的 oauth 字段。
- `handle_callback(query)` — **跑在 `start_login_listener` 起的回调后台线程**，登录成功写 token。
- `subscription_creds()` 封装内部的 `_open_session` 改读 store。

**三条写 `model_providers.yaml` 的路径并发**：① 设置页保存 providers；② OAuth 回调线程写 token；③ 临期刷新写回。靠 `_io.py` 每文件 `threading.Lock` + 原子写覆盖（已识别回调线程这条路径）。`_refresh_lock` 保留。

调用方去 db 参数：`text/openai_text.py`、`image/openai_image.py`、`services/document_import_pdf.py` 走 `subscription_creds()` 封装，封装内部改读 store 即可，签名不变。

`OAuthLoginSession` 仍走 DB。`api/openai_oauth.py` 顶部 import 改为只 `from app.models.oauth_credential import OAuthLoginSession`。

> 注：publisher（ximalaya/instagram/kuaishou/douyin）里的 `access_token` 是各平台自己的发布凭证（存 target 的 config），与 OpenAI OAuth 无关，**不动**。

### 设置页（Settings.tsx + /api/settings）

> ⚠️ providers/collectors/youtube 移出 config.yaml 后，设置页的「模型配置」「OAuth 订阅登录」「搜索 key」整块是它们唯一的编辑入口，必须重接，否则设置页直接坏。

现状：`Settings.tsx` 编辑 `settings.providers` / `settings.collectors` / `settings.youtube`，经 `PUT /api/settings` 保存；`api/settings.py` 对 `providers` 整体替换写回 config.yaml，并 `Settings(**current)` 全量校验。

迁移后：

- `Settings` 模型移除 `providers` / `collectors` / `youtube` 字段 → `Settings(**current)` 不再认这些 key。`/api/settings` 只处理瘦身后的 config.yaml 设置。
- 新增后端 endpoint 读写 model_providers.yaml：`GET/PUT /api/providers`（或并入既有 sources/publishers 路由的同级），由 `providers_store` 承载；providers 的整体替换逻辑搬到这里。
- 搜索 key 走 `sources_store.search_keys`（`api/sources.py` 加子路由）；youtube client 走 `targets_store.youtube_oauth_client`（`api/publishers.py` 加子路由）。
- `Settings.tsx`：「模型配置」块数据源切到 `/api/providers`；OAuth 订阅登录状态仍走 `api/openai_oauth.py`（其底层已改 store）；搜索 key / youtube client UI 切到对应新 endpoint。

### 一次性 DB→YAML 迁移

- 启动时（`main.py` lifespan）：若某 YAML 文件不存在，用**原生 `sqlite3`** 直接读旧表导出生成（不依赖 ORM，因模型将被删）；表不存在 / 非 sqlite → 写默认空文件。
- **单向一次性迁移**：YAML 文件已存在则跳过（幂等）。声明：迁移后旧表弃用、只读；不再回看 DB 新增行（单用户本地，迁移后所有写入只进 YAML）。
- **删模型与 import 必须同一原子改动**，否则启动即 ImportError：
  - 删 `models/{news_source,publish_target}.py` 与 `oauth_credential.py` 中的 `OAuthCredential`（保留 `OAuthLoginSession`）。
  - 同步删 `models/__init__.py` 对应 import；改 `api/openai_oauth.py` 顶部 import 为只 `OAuthLoginSession`。
  - `main.py` 的 `Base.metadata.create_all` 不再建这三张表；老库里的旧表不会被删，sqlite3 迁移仍能读到（时序成立）。

## 前端

- `NewsSource.id` / `PublishTarget.id` 改 `string`（slug）。
- `CreateRunDialog`：source 侧 state 从 `Set<number>` 改 `Set<string>`，删 `toggleSource(Number(v))` / `availableSourceIdSet` 等所有 source 的 `Number()`（**勿误删 `:118` 的 stage 依赖 `Number(dep)`，与 source 无关**）；target 侧已是 `Set<string>`，无需改。
- **`SourceSummary.tsx`（spec 原漏）**：`:18-21` 把 `source_ids` 解析为 `number[]` 并 `ids.includes(s.id)` 比对，`s.id` 变 string 后必坏 → 改为字符串解析与比对。
- `Sources.tsx` / `Publishers.tsx`：CRUD、batch 改 slug。
- `Dashboard.tsx`：经 `SourceSummary` 间接受影响，随上一条一并验证。
- `api/client.ts`：sources / publishers CRUD 参数类型同步为 string id。

## 已知未接通项（迁移只搬家、不改行为）

- `config.yaml.collectors`（tavily/serper/brave）当前是**死配置**：运行时 `build_collectors_from_db` 无参实例化 collector，能注入 key 的 `create_collector_registry` 全代码库无人调用；只有 per-source `config_json` 里的 key 真正生效。搬到 `news_sources.yaml.search_keys` 是合理归位，但**不接通运行时**。
- `config.yaml.youtube` 顶层块同理：youtube publisher 只读 target 的 config，顶层无运行时消费者。搬到 `publish_targets.yaml.youtube_oauth_client` 同为搬家不接通。
- 实现时不要误以为搬完即生效；接通与否不在本次范围。

## 错误处理

- YAML 损坏/解析失败：加载抛明确错误（含文件路径），不静默吞。
- 原子写失败：保留原文件（temp 未 replace），抛错。
- slug 冲突：create/update 报 409 风格错误。
- OAuth 刷新失败：沿用现有 `NotLoggedInError` / 明确报错路径。

## 测试

- store 单测：round-trip load/save、原子写、slug 生成与查重、回退序号稳定性、CRUD、batch。
- 迁移单测：临时 sqlite 种子 → 断言生成的 YAML 内容 + run.source_ids / run.publish_platforms 改写。
- API 测试：sources / publishers 改 slug id；新 providers / search_keys / youtube_client endpoint。
- OAuth 文件版测试：读写 / 刷新写回；**字符串 `expires_at` 临期刷新**；回调线程写并发（与设置页写不交错）。
- 降级语义测试：历史 run 的 source_ids 全失效时报错而非回退 HN。
- 现有受影响测试点名重写：
  - `test_collectors_for_run.py` / `test_sources_for_run.py`（`_Run` mock + 真 `db.query(NewsSource)` → 改 store）
  - `test_api_pipeline.py`（`source_ids: [2,5]` 整数 → slug）
  - `test_openai_oauth.py`（整套基于 `db` / `store_tokens(db, ...)` → store）
  - `test_oauth_credential_model.py`（测的就是要删的 `OAuthCredential` → 删除或改为 `OAuthLoginSession` only）

## 受影响文件（概览）

**新增**：`backend/app/store/{_io,providers_store,sources_store,targets_store}.py`、三个 YAML（运行时生成）、新 providers / search_keys / youtube_client 读写 endpoint、对应测试。

**修改**：`config.py`（providers/collectors/youtube 移出、`resolve` 改读 store、`Settings` 去三字段）、`api/settings.py`（去 providers 整体替换）、`api/sources.py`（+ search_keys 子路由）、`api/publishers.py`（+ youtube_client 子路由）、`api/openai_oauth.py`、`oauth/openai_oauth.py`（全函数去 db）、`pipeline/runner.py`（`_collectors_for_run`/`_sources_for_run`/`build_publishers` 取数改 store + 降级语义）、`pipeline/engine.py`、`main.py`（lifespan 迁移 + 去三模型建表）、`schemas/{source,publish_target}.py`、前端 `types/index.ts`、`api/client.ts`、`components/CreateRunDialog.tsx`、`components/SourceSummary.tsx`、`pages/{Sources,Publishers,Settings}.tsx`、`pages/Dashboard.tsx`（验证）。

**删除**：`models/{news_source,publish_target}.py`、`oauth_credential.py` 中的 `OAuthCredential`（保留 `OAuthLoginSession`）；`models/__init__.py` 对应 import；`test_oauth_credential_model.py`（或改写）。删模型 + 删 import + 改 `api/openai_oauth.py` import 为**同一原子改动**。
