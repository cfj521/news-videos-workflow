# OpenAI 订阅模式（ChatGPT OAuth 登录）技术文档

> 综合 [`docs/superpowers/specs/2026-06-06-openai-oauth-design.md`](superpowers/specs/2026-06-06-openai-oauth-design.md)（设计）
> 与当前代码实现。设计取舍以 spec 为准，本文档侧重**实现现状、调用链路与运维排障**。

## 1. 这是什么 / 为什么有它

本项目调用 OpenAI 原本只支持手填 API Key（`providers.openai.api_key`，按量计费）。
订阅模式新增第二种鉴权：用 **ChatGPT 账号 OAuth 登录**（即 Codex CLI / ChatGPT 桌面端的
「Sign in with ChatGPT」流程），调用时直接吃 ChatGPT 订阅额度，免按量计费。

两种模式由 `providers.openai.auth_mode` 开关切换，互不影响：

| `auth_mode` | 端点 | 计费 | 说明 |
|---|---|---|---|
| `api_key`（默认） | `api.openai.com/v1` | 按量 | 现状，保留 |
| `subscription`（新增） | `chatgpt.com/backend-api/codex` | 吃订阅额度 | OAuth 登录 |

**背景**：据 Simon Willison《[GPT-5.5](https://simonwillison.net/2026/Apr/23/gpt-5-5/)》（2026-04-23），
GPT-5.5 初期**只通过 ChatGPT 与 Codex 提供、没有公开 API**。其后端
`/backend-api/codex/responses` 被 OpenAI 的 Romain Huet 确认为**对订阅用户官方支持**的端点。
因此订阅模式既是"免按量计费"的手段，也是早期使用 GPT-5.5 的主要途径。代价：借用 Codex 的
公开 `client_id`，且该端点为对话场景设计（见 §6 的超时坑）。

## 2. 能力覆盖

| 用途 | 订阅模式 | 实现 |
|---|---|---|
| script（文案/脚本） | ✅ | Responses API，`providers/text/openai_text.py` |
| summary（摘要） | ✅ | Responses API（纯文本） |
| vision（PDF/图片解析） | ✅ | Responses API，图片作 input |
| **image（生图）** | ✅ | gpt-5.5 + 内置 `image_generation` 工具，`providers/image/openai_image.py` |
| tts（语音） | ❌ | Codex 不出音频；继续用 edge-tts（免费）或 API Key |

## 3. 鉴权与 Token 生命周期

核心在 `backend/app/oauth/openai_oauth.py`，token 存 DB 表 `oauth_credentials`（单条 openai 记录）。

### OAuth 登录（一次性）
- 借用 Codex 公开 client：`client_id = app_EMoamEEZ73f0CkXaXp7hrann`，
  **redirect_uri 被锁死**为 `http://localhost:1455/auth/callback`（不可自定义）。
- 流程：`/api/auth/openai/login/start` → 生成 PKCE(S256)+state、写 pending session、
  在 `127.0.0.1:1455` 起临时回调监听 → 浏览器授权 → 回调线程换 token → 写 DB。
- 登录态全程**落 DB**（不用模块级内存），解决 `--reload` 多 worker 下 `/login/status` 跨进程查询。

### Token 刷新（每次调用前）
- `subscription_creds()` → `(base_url, access_token, account_id)`，供 provider 工厂取用。
- 距 `expires_at` < 5 分钟则用 `refresh_token` 刷新并回写 DB；刷新加锁，避免并发双刷导致
  refresh_token 轮换失效。
- 订阅 provider **不在 `__init__` 固化 client**，而是每次 `generate()` 前重新取 token、
  `build_codex_client()`，401 时刷新后用**新 client** 重试一次（防 token 中途过期）。

## 4. 调用链路

共享客户端构造器（`openai_oauth.py:306`）：

```python
def build_codex_client(access_token, account_id):
    return openai.AsyncOpenAI(
        base_url="https://chatgpt.com/backend-api/codex",   # SDK 自动拼 /responses
        api_key=access_token,
        default_headers={"ChatGPT-Account-ID": account_id, "originator": "codex_cli_rs"},
    )
```

> ⚠️ 注意：这里**没有传 `timeout`**，沿用 SDK 默认（总超时 600s）。这与 §6 的 180s 超时直接相关。

## 5. 订阅生图实现（`_generate_subscription`）

`providers/image/openai_image.py:77`，与 api_key 模式（`images.generate`）分流：

- **强制 `model="gpt-5.5"`**（gpt-5.4 已被该端点弃用，会 500）。
- 走 **Responses 流式**：`client.responses.stream(model="gpt-5.5", tools=[{"type":"image_generation", "size": ...}], store=False)`。
- size 经 `_SUB_SIZE_MAP` 映射：`1080x1920→1024x1536`、`1920x1080→1536x1024`、`1024x1024→1024x1024`。
- 边收边取 base64：监听 `response.output_item.done`（`image_generation_call.result`）
  与 `response.image_generation_call.partial_image`，取到 `img_b64` 后落盘。
- 失败统一包成 `ProviderError(service="图片生成", provider="openai", cause=e)`，并 `log.exception` 记完整 traceback。

### 重试与进度（runner / stage3）
- `stage3_assets.py:11` 的 `_with_retry`：每张图最多 **3 次**、指数退避（base 5s + jitter），吃掉瞬时错误。
- `runner.py:645` 的 `TrackedImageProvider` 包一层，记 `Image X/N` 日志并向前端推送 `asset` 事件。

## 6. 已知限制与坑

### 6.1 ⚠️ 订阅生图有 ~180s 服务端网关超时（重点）

**现象**：单张图生成耗时贴近或超过 ~180s 时，连接被对端掐断，报
`httpx.RemoteProtocolError: peer closed connection without sending complete message body
(incomplete chunked read)`，日志显示 `generate(sub) image failed after 180.3s`。

**根因**（run #12 完整 traceback 确认）：

- 异常发生在 `_receive_response_body` —— 即**已收到 200、正在读 chunked 流式响应体的途中**被断流。
- **不是限流**：限流是 HTTP 429 / `RateLimitError`，另一类异常。
- **不是客户端超时**：`build_codex_client` 未设 timeout（默认 600s），且客户端超时会抛 `ReadTimeout`。
- **是服务端/网关掐的**：`chatgpt.com/backend-api/codex` 链路上的网关对单次（流式）响应有
  ~180s（典型 `proxy_read_timeout` 量级）硬上限。codex 端点本为对话设计，gpt-image-2 出图
  耗时 100~180s 正贴着上限，超了即断流。**这个超时改不了，它在 OpenAI 服务端。**

**该端点物理上不回报具体原因**：已回 200 并开始 chunked 传输，中途断 TCP，没有 4xx/5xx 也没有
error JSON body。能拿到的只有 httpx 的 `RemoteProtocolError`，代码已完整记录、未吞信息。

**当前缓解**：靠 `_with_retry` 重试。重试常常更快（< 180s）而成功，但每次失败要白等满 180s。

**可优化方向**（见 spec「运行时发现」章节，未实施）：
1. 客户端主动设 ~150s read timeout + 早重试，省掉干等被掐的时间，日志也更明确。
2. `except` 里补记"断连前收到过几个 `partial_image`"，区分"没开始生成"还是"中途被掐"。
3. 降出图尺寸 / 精简 prompt，把单张压到 180s 以下。
4. 或彻底走 api_key 模式的 `images.generate`（不经 codex 网关，无此限制；代价是按量计费）。

### 6.2 进度计数 `7/6` `8/6` `9/6` 溢出（显示问题，产物正确）

`runner.py:650` 的 `img_count` 是 nonlocal **累计调用次数**（含每次重试），分母却是场景总数。
重试一次分子就 +1，于是溢出成 `7/6`、`8/6`、`9/6`。**失败尝试不会被记成成功**——每张图存哪由
`output_path`（`scene_0N_image.png`）决定，与计数器无关，最终仍是真实的 6/6。应改为按"完成场景数"
计或拆成"场景 i / 第 n 次尝试"。

### 6.3 灰色用法风险

借用 Codex 的 `client_id`、调用 ChatGPT 后端端点，属个人本机用法。端点本身对订阅用户官方支持，
但 client_id 借用与长任务超时不在其设计目标内，行为可能随时变动。token 明文存 SQLite（与项目
现状一致）。

## 7. 排障指南

### 日志在哪（关键：logger 分流）
- per-run `data/runs/<id>/pipeline.log` —— 只收 `nv.run.<id>` logger（`[S3] Image X/N` 这类）。
- `data/logs/app.log` —— 收 `nv.stage3` / `nv.provider.image.openai` 等，**真实失败原因与 traceback 在这里**。
- 排查出图失败务必看 `app.log`，pipeline.log 里只看到"开始没结束"会误判。

### 如何区分失败类型

| 日志特征 | 含义 | 处理 |
|---|---|---|
| `peer closed connection ... incomplete chunked read`，`failed after ~180s` | 服务端网关超时（§6.1） | 重试/降耗时；非限流 |
| `rate limit exceeded (429)` / `RateLimitError` | 真限流 | 退避重试 / 降并发 |
| `401` → refresh → 仍失败 / `refresh_token_expired` | token 过期 | 去设置页重新登录 |
| `订阅生图无图片返回` | 流读完但没拿到 base64 | 查 prompt 是否被内容策略拦、或端点行为变动 |
| `Image 7/6` 这类计数 | 正常重试导致的显示溢出（§6.2） | 无需处理，看最终 `N/N ok` |

## 8. 参考资料

- 设计 spec：[`2026-06-06-openai-oauth-design.md`](superpowers/specs/2026-06-06-openai-oauth-design.md)
- Simon Willison, *GPT-5.5*（2026-04-23）：https://simonwillison.net/2026/Apr/23/gpt-5-5/
  （GPT-5.5 初期无 API、codex 端点官方支持订阅用户、定价 $5/$30 per 1M tokens）
- 代码：`backend/app/oauth/openai_oauth.py`、`backend/app/providers/image/openai_image.py`、
  `backend/app/pipeline/stage3_assets.py`、`backend/app/pipeline/runner.py`
