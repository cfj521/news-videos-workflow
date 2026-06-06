# OpenAI OAuth 登录（订阅模式）设计

日期：2026-06-06
状态：已含 subagent 评审修订（S1/S2/M1-M5/N1-N5）

## 背景与目标

本项目调用 OpenAI 目前只支持手填 API Key（`providers.openai.api_key`，按量计费）。
本特性新增一种鉴权方式：用 **ChatGPT 账号 OAuth 登录**（即 Codex CLI / ChatGPT 桌面端的
「Sign in with ChatGPT」流程），让本项目调用 OpenAI 时直接吃用户的 ChatGPT 订阅额度，
免去手填 API Key、免按量计费。

两种方式做成**可选开关**，互不影响：

- `api_key`（现状，保留）：填 key，走官方 `api.openai.com`，按量计费。
- `subscription`（新增）：OAuth 登录，走 Codex 后端端点，吃订阅额度。

### 订阅模式覆盖范围

| 用途 | 订阅模式 | 说明 |
|---|---|---|
| script（文案/脚本） | ✅ | Responses API |
| summary（摘要） | ✅ | 纯文本，Responses API |
| vision（PDF/图片解析） | ✅ | Responses API，图片作为 input |
| image（生图） | ✅ | gpt-5.5 + 内置 `image_generation` 工具 |
| tts（语音） | ❌ | Codex 不出音频；继续 edge-tts（免费）或 API Key |

## 调研结论（已核实）

所有参数已对照本机 `~/.codex/auth.json` 与多个开源实现核实。

### OAuth 流程
- client_id：`app_EMoamEEZ73f0CkXaXp7hrann`（借用 Codex 公开 client，因此 **redirect_uri 被锁死**）
- authorize：`https://auth.openai.com/oauth/authorize`
- token：`https://auth.openai.com/oauth/token`（authorization_code 换取、refresh_token 刷新均用此端点 + 同一 client_id）
- redirect_uri：**只能用** `http://localhost:1455/auth/callback`（Codex client 注册过的地址，不可自定义）
- scope：`openid profile email offline_access`
- PKCE：S256；authorize query 需手拼，空格用 `%20`（不能用 `+`）
- originator：`codex_cli_rs`

### 订阅模式调用
- base_url：`https://chatgpt.com/backend-api/codex`（OpenAI SDK 会自动拼 `/responses`）
- 用 `responses.create`（**不是** `chat.completions`），`store=False`
- 必需头：`Authorization: Bearer <access_token>` + `ChatGPT-Account-ID: <account_id>`
  （`originator` 在生图时可能需要，spike 时验证）
- 401 → 用 refresh_token 刷新后重试一次（重试须用带新 token 的新 client，见 M4）
- 可直接复用 `openai` Python SDK：`AsyncOpenAI(base_url=..., api_key=<access_token>, default_headers={...})`

### 生图（通过订阅）
- 需 `model="gpt-5.5"`（gpt-5.4 已被该端点弃用，会 500）
- 通过 Responses 内置 `image_generation` 工具，返回 `image_generation_call` 输出项（base64）
- 算进 ChatGPT 订阅额度（Plus 可用，Free 不可）
- ⚠️ 精确工具 schema（`{"type":"image_generation"}` vs Codex 自定义函数工具）**由阶段二 spike 抓真实请求确认**

### 风险声明
`chatgpt.com/backend-api/codex/responses` 是 OpenAI **未公开接口**，可能随时变动或被封。
本特性属灰色用法（借用 Codex client_id），仅供个人本机使用。

## 关键决策（已与用户确认）

1. 路线：**自写 OAuth 流程**（不依赖本机已装 Codex）。
2. 两种鉴权模式（api_key / subscription）做成可选。
3. 订阅模式覆盖 **文本 + 生图 + 解析**（即 1a 方案）。
4. 后端运行方式：**本机 uvicorn**（localhost:1455 回调直达，无需端口映射）。
5. token 存储：**DB**（新表 `oauth_credentials`）。
6. **不做**「导入本机 codex 登录」按钮，只做应用内 OAuth。
7. 文本走 Responses 时**非流式**（`store=False`，取完整结果；若端点强制流式则内部消费流、对外仍返回整段——由 spike 先确认）。

## 实施阶段（评审建议拆分）

为先验证"灰色端点是否真能用"，拆两阶段：

- **阶段一**（可独立验收）：OAuth 流程 + 回调监听 + DB 模型 + token 服务 + API 路由 + 前端登录 UI。
  验收：能登录、状态卡显示 email/plan/过期时间、能 logout、token 刷新可测。
  本阶段解决 S1（建表链路）、S2（回调并发模型）。
- **阶段二**：provider 三路集成，按风险递增顺序 **文本 → 生图 → 解析**；每路集成前先 spike
  抓一次本机 codex 真实请求，确认：
  - 文本：`stream=False` 是否被端点接受（N2）；
  - 生图：`image_generation` 工具的精确 schema 与返回结构（N3）；
  - 解析：图片 input 在 responses 端点的格式。

---

## 架构与组件

### 1. 配置层 `backend/app/config.py`
- `ProviderCreds`（`config.py:41`）增加字段 `auth_mode: str = "api_key"`（取值 `"api_key" | "subscription"`）。
  仅对 openai 有意义，其它供应商忽略。存进 `config.yaml`（`providers.openai.auth_mode`），设置页保存时写回。
- **token 不进 config.yaml**（存 DB）。
- `resolve()`（`config.py:327`）**保持返回四元组不变**；工厂另外取一次
  `cfg.provider_creds("openai").auth_mode` 判分支（见 M3）。
- `config.yaml.example` 的 `providers.openai` 段补一行 `auth_mode: api_key`（带注释说明）。

### 2. DB 模型 `backend/app/models/oauth_credential.py`
新表 `oauth_credentials`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| provider | String(30) unique | 固定 `"openai"`（预留多供应商） |
| access_token | Text | |
| refresh_token | Text | |
| id_token | Text nullable | |
| account_id | String(64) | ChatGPT account id |
| expires_at | DateTime(tz) | 从 access_token 的 `exp` claim 解出 |
| plan_type | String(32) | 如 `plus` |
| account_email | String(255) | 展示用 |
| last_refresh | DateTime(tz) | |
| created_at / updated_at | TimestampMixin | |

登录会话临时态也落库（解决 S2 跨进程问题），用同表或独立小表 `oauth_login_sessions`：
`state`(unique) / `code_verifier` / `status`(pending|success|error) / `error`(nullable) / `created_at`。
（实现可二选一；推荐独立小表，语义清晰、登录完即可清。）

**建表链路（S1，关键）**：`main.py` 的 `create_all`（`main.py:62`）只建**启动时已注册到
`Base.metadata`** 的模型；模型靠各处 import 注册，`models/__init__.py` 仅测试导入。
因此**必须保证新模型模块在启动路径被 import**：在新 router 文件
`api/openai_oauth.py` 顶部 `from app.models.oauth_credential import OAuthCredential, OAuthLoginSession`，
该 router 在 `api/router.py` 顶层 import（`router.py` 在 `main.py:11` 顶层加载），即可在 create_all
前完成注册。同时也加进 `models/__init__.py` 保持一致。

### 3. OAuth 核心 `backend/app/oauth/openai_oauth.py`
常量集中于此（`CLIENT_ID` / `AUTH_BASE` / `REDIRECT_URI` / `SCOPE` / `ORIGINATOR` / `CODEX_BASE`）。

纯函数（无副作用，易测）：
- `gen_pkce()` → `(code_verifier, code_challenge)`，S256。
- `build_authorize_url(code_challenge, state)` → url（query 手拼，空格 `%20`）。
- `exchange_code(code, code_verifier)` → token dict（POST `/oauth/token`，grant=authorization_code）。
- `refresh_tokens(refresh_token)` → token dict（grant=refresh_token）。
- `parse_claims(jwt_str)` → dict（解 JWT payload base64，不验签）：取 `exp` /
  `chatgpt_account_id` / `chatgpt_plan_type` / `email`。

**回调监听（S2，关键）**——登录态全程落 DB，不用模块级内存：
- `/login/start` 时：`gen_pkce` + 随机 `state` → 写一条 `oauth_login_sessions`(status=pending) →
  在 `127.0.0.1:1455` 起临时 HTTP 监听 `/auth/callback`（标准库 `http.server` 后台线程）。
- 回调线程拿到 `?code&state`：用 `get_session_factory()` 自建 session（`check_same_thread=False`
  已在 `database.py:23` 配好，WAL + busy_timeout 已配，跨线程写安全）→ 按 state 查 pending
  session 校验 `code_verifier` → `exchange_code` → `parse_claims` → 写/更新 `oauth_credentials`
  → 把 session 标 success → 回「登录成功，可关闭本页」HTML → 关监听。
- `/login/status` **查 DB**（session.status / 或直接查 oauth_credentials 是否更新），与 `/login/start`
  不在同一 worker 也能拿到结果（解决 `--reload` 多进程）。
- 端口 1455 被占用 → 抛可读错误（提示可能 codex 正在登录）；超时 300s 标 error 并关监听。
- 注：绑定 1455 的进程是处理 `/login/start` 的那个 worker；OAuth 重定向只会连到绑定该端口的进程，
  天然固定，无需跨进程传 socket。

### 4. Token 服务（同包 `openai_oauth.py` 或 `token_service.py`）
- `get_valid_access_token(db)` → `(access_token, account_id)`：
  读 DB openai 记录；若距 `expires_at` < 5 分钟 → `refresh_tokens` → 更新 DB → 返回。
  无记录抛「未登录」错误。**刷新加进程内 `asyncio.Lock`/线程锁**，避免两个 stage 同时
  临期双重刷新导致 refresh_token 轮换后失效（N1）。
- `subscription_creds()` → `(base_url=CODEX_BASE, access_token, account_id)`：
  用 `get_session_factory()` 自开 session 调上面的函数。供 provider 工厂调用（工厂无 db）。
- `get_status(db)` → `{logged_in, email, plan, expires_at}`。
- `logout(db)`：删除 openai 记录。

### 5. API 路由 `backend/app/api/openai_oauth.py`（前缀 `/api/auth/openai`）
- `POST /login/start` → 生成 PKCE+state，写 pending session，启动 1455 监听（后台），返回 `{authorize_url}`。
- `GET /login/status` → 查 DB 返回 `{status: pending|success|error, info?}`（轮询；一次性短流程不用 SSE）。
- `GET /status` → 当前登录态（email/plan/expires）。
- `POST /logout` → 调 `logout`。
- 顶部 import 新模型（S1）。**鉴权守卫沿用 `router.py` 现有统一模式**（`router.py:20-24` 的
  `dependencies=_guard`），router 内部不再逐个加 `Depends(get_current_user)`（M5，避免重复）。

### 6. Provider 集成（订阅分支，阶段二）
共享构造器（放 `openai_oauth.py`）：
```python
def build_codex_client(access_token, account_id):
    return AsyncOpenAI(
        base_url="https://chatgpt.com/backend-api/codex",
        api_key=access_token,
        default_headers={"ChatGPT-Account-ID": account_id, "originator": "codex_cli_rs"},
    )
```

**M4（防 token 中途过期）**：订阅模式 provider **不在 __init__ 固化 client**，而是每次
`generate()/synthesize` 调用前 `subscription_creds()` 取新 token 并 `build_codex_client`；
401 时刷新后用新 client 重试一次。

各改动点（均在 `provider == "openai"` 且 `auth_mode == "subscription"` 时走订阅分支）：

- **文本** `providers/text/openai_text.py`：`OpenAITextProvider` 加 `subscription: bool`。
  subscription → `responses.create(model, instructions=system_prompt, input=prompt, store=False)`，
  取 `output_text`（非流式，待 spike 确认）；否则维持现有 `chat.completions`。
- **摘要**：`runner.py::_build_text_provider`（line 30，**无参**，自取 settings）与
  `runner.py::_build_summary_provider(cfg)`（line 159，**独立函数**，非重复）**都要**加订阅分支
  （summary_provider 默认也是 openai）。`regen_script`（`api/pipeline.py:355`）走 `_build_text_provider`，
  改工厂即覆盖（M1）。
- **生图** `providers/image/openai_image.py`：`OpenAIImageProvider.__init__` 扩签名增加
  `subscription`/`account_id`（带 `ChatGPT-Account-ID` 头，N4）；subscription 分支
  `responses.create(model="gpt-5.5", input=prompt, tools=[{"type":"image_generation"}], …)`，
  从 `image_generation_call` 取 base64 落盘。`build_image_provider`（`image/__init__.py`）在
  openai+subscription 时**忽略 resolve 的 base_url**、改用 `subscription_creds()` 的 codex_base，
  并**强制 model=gpt-5.5**（用户选了别的 image_model 时覆盖并记日志）。⚠️ 工具 schema 待 spike。
- **解析** `services/document_import_pdf.py::_vision_extract`：当前裸 httpx 打 `/chat/completions`。
  **透传载体需扩展**（M2）：`ProviderCfg`（`config.py:26`）加 `auth_mode` + `account_id` 字段，
  `api/pipeline.py:314` 构造时填入；`_vision_extract` 按 `auth_mode` 分支——subscription 时
  改走 codex responses（input 含 image_url 项 + ChatGPT-Account-ID 头），且 vision model
  覆盖为端点支持的（如 gpt-5.5）。

### 7. 前端 `frontend/src/pages/Settings.tsx`（「模型配置」→ openai tab）
- openai 凭证区加模式单选 **API Key / 订阅登录**（对应 `auth_mode`）：
  - API Key：照旧显示 api_key 输入框。
  - 订阅登录：隐藏 key 输入，显示：
    - 未登录：「登录 ChatGPT」按钮。点击 → `POST /login/start` → `window.open(authorize_url)`
      → 轮询 `GET /login/status` → success 后刷新状态。
    - 已登录：状态卡（邮箱 / 套餐 `plus` / 过期时间）+「退出登录」按钮（`POST /logout`）。
  - 文案提示：订阅仅支持 文本/生图/解析（不支持 TTS）；生图固定用 gpt-5.5。
- 保存设置时把 `auth_mode` 随 providers.openai 写回 config.yaml。

### 8. 错误处理
- 401 → 自动 refresh 一次并**用新 client** 重试（M4）；refresh 失败（`refresh_token_expired`）→
  删/标记 DB 记录失效，抛 `ProviderError` 引导「去设置页重新登录」。
- 选了 subscription 但未登录 → 明确报错引导登录。
- 选了 subscription 用 TTS → 报错说明 TTS 不支持订阅。
- 1455 端口被占用 → 可读提示。

### 9. 测试
- `parse_claims` JWT payload 解码（脱敏样本）。
- `refresh` near-expiry 触发逻辑 + 刷新锁（mock token 端点）。
- `gen_pkce` / `build_authorize_url`（含 `%20` 与 state）。
- 回调流程：mock 1455 回调写库 → `/login/status` 查库返回 success。
- provider 订阅分支：mock `responses.create` 验证走对端点/参数/每次取新 token（文本 + 生图）。
- API 路由：login/start 返回 authorize_url；status / logout。
- 建表：启动 import 链能让 `oauth_credentials` 出现在 `Base.metadata`。

### 10. 依赖与安全
- **无新依赖**：`openai` SDK、`httpx` 已在用；PKCE 用标准库 `secrets` / `hashlib` / `base64`。
- token 明文存 SQLite，与项目现状一致（config.yaml 明文 key、publish_target 明文凭证），文档注明。
- 借用 Codex client_id、调用未公开端点属灰色用法，仅个人本机使用。

## 数据流（订阅模式一次文本调用）

```
设置页选 openai + auth_mode=subscription，点登录
  → POST /login/start → 写 pending session + 起 1455 监听 + 返回 authorize_url
  → 浏览器 OAuth 授权 → 重定向 localhost:1455/auth/callback?code&state
  → 回调线程换 token → 写 oauth_credentials + session=success
  → 前端轮询 /login/status 查库 = success
任务运行 Stage2（script, provider=openai, auth_mode=subscription）
  → _build_text_provider 见 auth_mode=subscription，置 subscription=True
  → generate() 前 subscription_creds() 读 DB（必要时加锁 refresh）→ (codex_base, token, account_id)
  → build_codex_client → responses.create(store=False) → output_text
```

## 不做（YAGNI / 范围外）
- 不做「导入本机 codex auth.json」按钮。
- 不做 Docker/WSL 下的 1455 端口映射（本特性按本机 uvicorn 运行设计）。
- 不做订阅模式的 TTS。
- 不做多 ChatGPT 账号切换（单条 openai 记录）。
