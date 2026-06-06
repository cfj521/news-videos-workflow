# OpenAI OAuth 登录（订阅模式）设计

日期：2026-06-06

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
  （`originator` 在生图时可能需要，实现时验证）
- 401 → 用 refresh_token 刷新后重试一次
- 可直接复用 `openai` Python SDK：`AsyncOpenAI(base_url=..., api_key=<access_token>, default_headers={...})`

### 生图（通过订阅）
- 需 `model="gpt-5.5"`（gpt-5.4 已被该端点弃用，会 500）
- 通过 Responses 内置 `image_generation` 工具，返回 `image_generation_call` 输出项（base64）
- 算进 ChatGPT 订阅额度（Plus 可用，Free 不可）
- ⚠️ 精确工具 schema（`{"type":"image_generation"}` vs Codex 自定义函数工具）**实现时**对照 codex
  源码或抓一次真实请求最终确认

### 风险声明
`chatgpt.com/backend-api/codex/responses` 是 OpenAI **未公开接口**，可能随时变动或被封。
本特性属灰色用法（借用 Codex client_id），仅供个人本机使用。

## 关键决策（已与用户确认）

1. 路线：**自写 OAuth 流程**（不依赖本机已装 Codex）。
2. 两种鉴权模式（api_key / subscription）做成可选。
3. 订阅模式覆盖 **文本 + 生图 + 解析**（即上表 1a 方案）。
4. 后端运行方式：**本机 uvicorn**（localhost:1455 回调直达，无需端口映射）。
5. token 存储：**DB**（新表 `oauth_credentials`）。
6. **不做**「导入本机 codex 登录」按钮，只做应用内 OAuth。
7. 文本走 Responses 时**非流式**（`store=False`，取完整结果；若端点强制流式则内部消费流、对外仍返回整段）。

## 架构与组件

### 1. 配置层 `backend/app/config.py`
- `ProviderCreds` 增加字段 `auth_mode: str = "api_key"`（取值 `"api_key" | "subscription"`）。
  仅对 openai 有意义，其它供应商忽略。
- 该字段存进 `config.yaml`（`providers.openai.auth_mode`），设置页保存时写回。
- **token 不进 config.yaml**（存 DB）。
- `config.yaml.example` 的 openai 段补一行 `auth_mode: api_key` 注释说明。

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

- 加入 `backend/app/models/__init__.py`，随现有 create_all（`app/main.py` 启动建表）自动建表。

### 3. OAuth 核心 `backend/app/oauth/openai_oauth.py`
常量集中于此（`CLIENT_ID` / `AUTH_BASE` / `REDIRECT_URI` / `SCOPE` / `ORIGINATOR` / `CODEX_BASE`）。

纯函数（无副作用，易测）：
- `gen_pkce()` → `(code_verifier, code_challenge)`，S256。
- `build_authorize_url(code_challenge, state)` → url（query 手拼，空格 `%20`）。
- `exchange_code(code, code_verifier)` → token dict（POST `/oauth/token`，grant=authorization_code）。
- `refresh_tokens(refresh_token)` → token dict（grant=refresh_token）。
- `parse_claims(jwt_str)` → dict（解 JWT payload base64，不验签）：取 `exp` / `chatgpt_account_id` /
  `chatgpt_plan_type` / `email`。

回调监听（登录时一次性）：
- 临时起 `127.0.0.1:1455` HTTP 监听 `/auth/callback`：
  校验 `state` → `exchange_code` → 存 DB → 回一个「登录成功，可关闭本页」HTML → 关监听。
- 超时 300s 自动关闭并标记失败。
- 端口被占用 → 抛出可读错误（提示可能 codex 正在登录）。
- 实现用 Python 标准库 `http.server`（后台线程），或 asyncio 临时 server；登录态用模块级
  内存变量记录 `pending|success|error` 供轮询查询。

### 4. Token 服务（同包 `openai_oauth.py` 或 `token_service.py`）
- `get_valid_access_token(db)` → `(access_token, account_id)`：
  读 DB openai 记录；若距 `expires_at` < 5 分钟 → `refresh_tokens` → 更新 DB → 返回。
  无记录抛「未登录」错误。
- `subscription_creds()` → `(base_url=CODEX_BASE, access_token, account_id)`：
  用 `get_session_factory()` 自开 session 调上面的函数。供 provider 工厂调用（工厂只有 `cfg`、无 db）。
- `get_status(db)` → `{logged_in, email, plan, expires_at}`。
- `logout(db)`：删除 openai 记录。

### 5. API 路由 `backend/app/api/openai_oauth.py`（前缀 `/api/auth/openai`，全部 `Depends(get_current_user)`）
- `POST /login/start` → 生成 PKCE+state，启动 1455 监听（后台），返回 `{authorize_url}`。
- `GET /login/status` → `{state: pending|success|error, info?}`（轮询；一次性短流程不用 SSE）。
- `GET /status` → 当前登录态（email/plan/expires）。
- `POST /logout` → 调 `logout`。
- 在 `app/api/router.py` 注册该 router。

### 6. Provider 集成（订阅分支）
共享构造器（放 `openai_oauth.py` 或 providers 公共处）：
```python
def build_codex_client(access_token, account_id):
    return AsyncOpenAI(
        base_url="https://chatgpt.com/backend-api/codex",
        api_key=access_token,
        default_headers={"ChatGPT-Account-ID": account_id, "originator": "codex_cli_rs"},
    )
```

- **文本** `providers/text/openai_text.py`：`OpenAITextProvider` 增加 `subscription: bool` 标志。
  - subscription：`responses.create(model, instructions=system_prompt, input=prompt, store=False)`，
    从结果取 `output_text`（非流式）。
  - 否则维持现有 `chat.completions`。
- **生图** `providers/image/openai_image.py`：增加 subscription 分支：
  `responses.create(model="gpt-5.5", input=prompt, tools=[{"type":"image_generation"}], …)`，
  从 `image_generation_call` 输出项取 base64 → 落盘。⚠️ 工具 schema 实现时核实。
- **解析** `services/document_import_pdf.py::_vision_extract`：当前裸 httpx 打 `/chat/completions`。
  subscription 时改走 codex responses（input 含 image_url 项）。
- **工厂改动**：
  - `pipeline/runner.py::_build_text_provider`（及第二处重复实现，约 line 164-170）
  - `providers/image/__init__.py::build_image_provider`
  - vision 调用处（`api/pipeline.py:312` 一带 / `_vision_extract` 入参）
  在 `provider == "openai"` 时检查 `cfg.provider_creds("openai").auth_mode`；
  若 `== "subscription"` 调 `subscription_creds()` 注入 token+base_url+account_id 并置 subscription 标志；
  否则照旧用 api_key + base_url。

### 7. 前端 `frontend/src/pages/Settings.tsx`（「模型配置」→ openai tab）
- openai 凭证区加模式单选 **API Key / 订阅登录**（对应 `auth_mode`）：
  - API Key：照旧显示 api_key 输入框。
  - 订阅登录：隐藏 key 输入，显示：
    - 未登录：「登录 ChatGPT」按钮。点击 → `POST /login/start` → `window.open(authorize_url)`
      → 轮询 `GET /login/status` → success 后刷新状态。
    - 已登录：状态卡（邮箱 / 套餐 `plus` / 过期时间）+「退出登录」按钮（`POST /logout`）。
  - 文案提示：订阅模式仅支持 文本/生图/解析（不支持 TTS）；生图需选 gpt-5.5。
- 保存设置时把 `auth_mode` 随 providers.openai 写回 config.yaml。

### 8. 错误处理
- 401 → 自动 refresh 一次重试；refresh 失败（`refresh_token_expired`）→ 删/标记 DB 记录失效，
  抛 `ProviderError` 引导「去设置页重新登录」。
- 选了 subscription 但未登录 → 明确报错引导登录。
- 选了 subscription 用 TTS → 报错说明 TTS 不支持订阅。
- 1455 端口被占用 → 可读提示。

### 9. 测试
- `parse_claims` JWT payload 解码（用 auth.json 样本，脱敏）。
- `refresh` near-expiry 触发逻辑（mock token 端点）。
- `gen_pkce` / `build_authorize_url`（含 `%20` 与 state）。
- provider 订阅分支：mock `responses.create` 验证走对端点与参数（文本 + 生图）。
- API 路由：login/start 返回 authorize_url；status / logout。

### 10. 依赖与安全
- **无新依赖**：`openai` SDK、`httpx` 已在用；PKCE 用标准库 `secrets` / `hashlib` / `base64`。
- token 明文存 SQLite，与项目现状一致（config.yaml 明文 key、publish_target 明文凭证），文档注明。
- 借用 Codex client_id、调用未公开端点属灰色用法，仅个人本机使用。

## 数据流（订阅模式一次文本调用）

```
设置页选 openai + auth_mode=subscription，点登录
  → POST /login/start → 起 1455 监听 + 返回 authorize_url
  → 浏览器 OAuth 授权 → 重定向 localhost:1455/auth/callback?code
  → 后端换 token → 存 oauth_credentials
任务运行 Stage2（script, provider=openai）
  → _build_text_provider 见 auth_mode=subscription
  → subscription_creds() 读 DB（必要时 refresh）→ (codex_base, token, account_id)
  → OpenAITextProvider(subscription=True) → responses.create(...) → 文本
```

## 不做（YAGNI / 范围外）
- 不做「导入本机 codex auth.json」按钮。
- 不做 Docker/WSL 下的 1455 端口映射（本特性按本机 uvicorn 运行设计）。
- 不做订阅模式的 TTS。
- 不做多 ChatGPT 账号切换（单条 openai 记录）。
