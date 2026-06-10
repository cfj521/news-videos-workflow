# 抖音 / 快手 发布改造方案（浏览器自动化路线）

> 状态：**方案文档（未改代码）**。
> 决策：走**路线 B — 浏览器自动化**（基于 [social-auto-upload](https://github.com/dreammis/social-auto-upload)，扫码登录 + Cookie），与 B 站现有逆向 Cookie 路线一致；不依赖企业开放平台资质与 OAuth 审核。
> 目标读者：实现者。本文给出现状、根因、接口契约、改造点与分阶段落地清单。

---

## 1. 背景与现状

### 1.1 抖音 / 快手目前是「死代码 + 凭推测的实现」

| 层 | 抖音 | 快手 |
|---|---|---|
| 前端字段 `frontend/src/types/index.ts` `PLATFORM_FIELDS` | ✅ method / client_key / client_secret / access_token | ✅ method / app_id / app_secret / access_token |
| 适配器文件 | ✅ `backend/app/providers/publisher/douyin.py` | ✅ `backend/app/providers/publisher/kuaishou.py` |
| **接入工厂 `publisher/__init__.py` `_build_one`** | ❌ **未注册** | ❌ **未注册** |

**根因：`_build_one` 只 wire 了 `bilibili` 和 `youtube`**，抖音/快手命中末尾 `return None`，被 `build_publishers` 当成「暂不支持」`log.warning` 后跳过。即便用户在「发布管理」页配好账号，运行期也永远不会被构造 —— 这两个适配器是**死代码**。

### 1.2 现有适配器实现与真实接口对不上（凭记忆写的，勿沿用）

**`douyin.py` `_publish_api`：**
- 误用 `Authorization: Bearer {token}` —— 抖音实际用请求头 `access-token`（无 Bearer）。
- URL `…/api/douyin/v1/video/upload_video/` —— 实际是 `https://open.douyin.com/video/upload/`。
- 缺 `open_id`（OAuth 授权后与 access_token 同时下发，调接口需带）。
- 未处理分片上传（抖音 >128MB 必须分片，成片常 50–200MB 会踩线）。

**`kuaishou.py` `_publish_api`：**
- URL `open.kuaishou.com/rest/ks/open/photo/...` —— 实际是 `https://open.kuaishou.com/openapi/photo/start_upload`、`/openapi/photo/publish`。
- 同样误用 `Authorization: Bearer` —— 实际 `access_token` / `app_id` 作为 query 参数传，scope 为 `user_video_publish`。

**两个 `_publish_playwright`：** `from social_auto_upload.douyin import DouYinUploader` 的 import 路径与类名是**编造的**，真实库里不存在（真实接口见下）。

> 结论：路线 A（官方 API）整套 OAuth 授权页 + token 续期在本项目**完全未实现**，且需企业资质 + 1–2 周审核。故采用路线 B。下文 `_publish_api` 代码可整体废弃或保留为「未实现」占位。

---

## 2. 依赖：social-auto-upload 的真实编程接口

social-auto-upload 的上传器是**原生 async**，可直接 `import` 进本项目的 async 流水线，**无需 subprocess**。关键模块：

### 2.1 抖音 `uploader/douyin_uploader/main.py`

```python
class DouYinVideo:
    def __init__(self, title, file_path, tags, publish_date, account_file,
                 thumbnail_landscape_path=None, productLink="", productTitle="",
                 thumbnail_portrait_path=None, desc: str | None = None,
                 publish_strategy=DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
                 debug=DEBUG_MODE, headless=LOCAL_CHROME_HEADLESS): ...
    async def main(self): ...                 # 执行上传发布

async def cookie_auth(account_file) -> bool   # 校验 cookie 是否仍有效
async def douyin_setup(account_file, handle=False, return_detail=False,
                       qrcode_callback=None, headless=...) -> ...   # 登录态准备
async def douyin_cookie_gen(account_file, qrcode_callback=None,
                            poll_interval=3, max_checks=100, headless=...)  # 扫码生成 cookie
```

### 2.2 快手 `uploader/ks_uploader/main.py`

```python
class KSVideo:
    def __init__(self, title, file_path, tags, publish_date, account_file,
                 publish_strategy=None, debug=DEBUG_MODE, headless=LOCAL_CHROME_HEADLESS,
                 thumbnail_path=None, desc: str | None = None): ...
    async def main(self) -> None: ...

async def cookie_auth(account_file) -> bool
async def ks_setup(account_file, handle=False, return_detail=False,
                   qrcode_callback=None, headless=...) -> dict | bool
async def get_ks_cookie(account_file, qrcode_callback=None, headless=...,
                        poll_interval=3, max_checks=100) -> dict
```

### 2.3 关键概念

- **`account_file`**：一个 JSON 文件路径，保存该账号的浏览器 Cookie/登录态。**登录 = 扫码后把 cookie 写进这个文件；发布 = 读这个文件还原登录态**。一账号一文件，天然支持同平台多账号（与 `PublishResult.target_name` 对齐）。
- **`qrcode_callback`**：登录时拿到二维码的回调（图片字节/路径）。有它就能把二维码透出到前端让用户扫，没它则走库自带的弹窗/终端显示。
- **`publish_date`**：`datetime` 表示定时发布，传 `0`/立即策略表示马上发。本项目发布即时触发，用立即策略。
- **`headless` / `LOCAL_CHROME_PATH`**：来自其 `conf.py`（拷自 `conf.example.py`）。发布阶段用 `headless=True`；**登录阶段必须 `headless=False` 或走 `qrcode_callback`**，否则没法扫码。
- 依赖 **playwright + Chromium**：`pip install playwright && playwright install chromium`。属可选依赖，**不进根 `requirements.txt` 主区**（与 biliup 同类，按需装）。

---

## 3. 改造设计

### 3.1 配置字段（前端 `PLATFORM_FIELDS` + 后端 `_build_one`）

抛弃 client_key/app_secret/access_token（那是路线 A 的），改为浏览器路线所需的最小字段：

**抖音 / 快手统一字段：**

| key | label | required | 说明 |
|---|---|---|---|
| `account` | 账号标识 | ✅ | 一个名字，对应一个 cookie 文件（如 `myacct`）。用于多账号区分。 |
| `account_file` | Cookie 文件路径 | （可选/自动） | 缺省由 `account` 在固定 cookies 目录下派生（见 3.4），高级用户可显式指定。 |

> 登录态不像 B 站那样手填一堆 Cookie 值，而是**扫码后由系统写文件**。所以表单里不放 SESSDATA 之类，只放「账号名」，外加一个「登录」动作（见 3.3）。`method` 字段可保留但固定为 `playwright`/`browser`，或直接删掉（路线 A 已废）。

### 3.2 适配器改造（以抖音为例，快手同构）

`douyin.py` 重写为只走浏览器路线，调用 social-auto-upload 的 `DouYinVideo`：

```python
class DouyinPublisher(PublisherAdapter):
    def __init__(self, account_file: str = "", headless: bool = True):
        self._account_file = account_file
        self._headless = headless

    async def publish(self, video_path, thumbnail_path, title, description,
                      tags, subtitle_path=None) -> PublishResult:
        if not self._account_file or not Path(self._account_file).exists():
            return PublishResult(platform="douyin", status="failed",
                                 error_message="未登录：缺少 cookie 文件，请先在发布管理页扫码登录")
        try:
            from uploader.douyin_uploader.main import DouYinVideo, cookie_auth
        except ImportError:
            return PublishResult(platform="douyin", status="failed",
                                 error_message="social-auto-upload 未安装（pip install + playwright install chromium）")

        if not await cookie_auth(self._account_file):
            return PublishResult(platform="douyin", status="failed",
                                 error_message="登录态已失效，请重新扫码登录")

        try:
            video = DouYinVideo(
                title=title[:55], file_path=video_path, tags=(tags or [])[:5],
                publish_date=0,                       # 立即发布
                account_file=self._account_file,
                desc=description, thumbnail_portrait_path=thumbnail_path,
                headless=self._headless,
            )
            await video.main()
            return PublishResult(platform="douyin", status="success")
        except Exception as e:
            log.exception("Douyin browser publish failed")
            return PublishResult(platform="douyin", status="failed", error_message=str(e))
```

要点：
- **`subtitle_path` 忽略**（抖音网页发布不挂外挂字幕，字幕应在合成阶段烧进画面）。
- **`thumbnail_path` → `thumbnail_portrait_path`**（竖屏封面）。快手用 `thumbnail_path`。
- **标题长度**：抖音标题建议 ≤55 字，描述/话题进 `desc`；快手 caption 上限更宽。具体以库内实现为准。
- **`url` 难以稳定回传**：网页发布后不一定能立即拿到稿件 URL，`PublishResult.url` 可留空（B 站也有「无 bvid 返回」的容错先例）。
- **运行隔离**：`DouYinVideo.main()` 是 async，但内部会起 Chromium。流水线里**串行 await** 即可；若担心阻塞，可像 biliup 那样 `asyncio.to_thread` 包一层（视库实现是否真异步而定）。

快手 `kuaishou.py` 同样重写，调 `KSVideo(...).main()` + `cookie_auth`。

### 3.3 登录（扫码）流程 —— 本方案的核心

「登录」是一次性人工动作，产物是 `account_file`。两种落地深度：

**MVP（手动登录，先打通发布）**
1. 用户本机装好 social-auto-upload + playwright chromium。
2. 跑一次官方 CLI 或脚本完成扫码：
   `sau douyin login --account myacct` / `sau kuaishou login --account myacct`
   （或脚本里 `await douyin_setup(account_file, handle=True)`，弹窗扫码）。
3. 把生成的 cookie 文件路径填进发布管理页的 `account_file`（或按约定目录自动发现）。
4. 发布时适配器读该文件，`cookie_auth` 校验 → `DouYinVideo.main()`。

**集成版（系统内扫码，体验闭环，阶段二）**
- 新增后端接口：`POST /api/publishers/{slug}/login` → 调 `douyin_setup(account_file, handle=True, qrcode_callback=cb)`，`cb` 把二维码图片(base64)经 SSE/轮询透出前端；后台 `douyin_cookie_gen` 轮询直到登录成功写盘。
- 新增「登录态检查」：`GET /api/publishers/{slug}/health` → `cookie_auth(account_file)`，前端像 B 站那样显示「有效 / 已失效，请重登」。
- 前端发布管理页：账号卡片加「扫码登录」「检查登录态」两个按钮。

> 建议先交付 MVP 打通「能发」，集成版扫码 UI 作为阶段二。

### 3.4 Cookie 文件目录约定

- 统一放仓库根 `publish_cookies/<platform>/<account>.json`（不入库，加 `.gitignore`）。
- `account_file` 缺省 = `publish_cookies/douyin/<account>.json`，与 `publish_targets.yaml` 的账号解耦但可关联。
- 与现有「凭证存仓库根 yaml、不入 config.yaml」的约定一致。

### 3.5 `_build_one` 注册（消除死代码）

```python
if platform == "douyin":
    from app.providers.publisher.douyin import DouyinPublisher
    return DouyinPublisher(account_file=cfg.get("account_file") or _derive_path("douyin", cfg.get("account")),
                           headless=True)
if platform == "kuaishou":
    from app.providers.publisher.kuaishou import KuaishouPublisher
    return KuaishouPublisher(account_file=cfg.get("account_file") or _derive_path("kuaishou", cfg.get("account")),
                             headless=True)
```

---

## 4. 依赖与安装（文档/部署需补充）

- `pip install social-auto-upload`（或 `git submodule` / vendored，视其发布形态；该库以仓库形式为主，可能需 `pip install -e` 或加入 `PYTHONPATH`）。
- `playwright install chromium`（首次）。
- 拷 `conf.example.py` → `conf.py`，按需设 `LOCAL_CHROME_PATH` / `LOCAL_CHROME_HEADLESS`。
- 列为**可选依赖**，缺失时适配器返回友好错误（已在 3.2 体现），不阻断其它平台。
- 更新 `docs/video-publish-guide.md` 第 4/5 节（抖音/快手）：把「企业资质 + 开放平台」改写为「扫码登录浏览器自动化」为主推路径。

---

## 5. 风险与限制

- **稳定性**：网页 DOM 变更会导致 playwright 选择器失效，需跟随上游库更新（上游正计划从 playwright 切到 patchright 提升隐蔽性）。
- **风控**：高频发布有封号/验证码风险，建议限频（参考 B 站每日 5–10 条的口径）。
- **登录态过期**：Cookie 会失效，需重新扫码；`cookie_auth` 提供主动探测。
- **无官方授权**：与 B 站逆向路线同性质，存在合规与可用性波动风险，需在文档中告知用户。
- **服务器无头环境**：扫码登录需要能显示二维码（前端透出可解决）；发布可 headless，但 Chromium 需在后端机器可运行。
- **URL 回传**：发布结果 URL 可能拿不到，下游展示需容忍空 URL。

---

## 6. 落地清单（实现阶段用）

**阶段一 · 打通发布（MVP）**
- [ ] 重写 `douyin.py` / `kuaishou.py`：删 `_publish_api` 假实现，改调 `DouYinVideo`/`KSVideo` + `cookie_auth`。
- [ ] `_build_one` 注册 `douyin` / `kuaishou`，加 `_derive_path` 派生 cookie 路径。
- [ ] 前端 `PLATFORM_FIELDS` 抖音/快手字段改为 `account`(+可选 `account_file`)，去掉路线 A 字段。
- [ ] `.gitignore` 加 `publish_cookies/`。
- [ ] 文档：`video-publish-guide.md` 抖音/快手章节改写；新增「装 social-auto-upload + playwright + 扫码登录」步骤。
- [ ] 校验：手动扫码生成 cookie → 跑一条 pipeline 到 publish stage，确认能发。

**阶段二 · 系统内扫码闭环**
- [ ] 后端 `POST /api/publishers/{slug}/login`（SSE 透二维码）+ `GET .../health`（`cookie_auth`）。
- [ ] 前端账号卡片加「扫码登录」「检查登录态」。

**测试**
- [ ] `tests/` 加适配器单测：未登录/cookie 失效/库未安装三种失败路径返回正确 `PublishResult`（mock 掉 `DouYinVideo.main`，不真连网）。

---

## 参考

- social-auto-upload：<https://github.com/dreammis/social-auto-upload>（CLI 用法 `docs/CLI.md`；上传器 `uploader/douyin_uploader/`、`uploader/ks_uploader/`）
- 抖音开放平台·上传视频（路线 A，备查）：<https://open.douyin.com/platform/resource/docs/openapi/video-management/douyin/create/upload/>
- 快手开放平台·发起上传/发布（路线 A，备查）：<https://open.kuaishou.com/platform/openApi?menu=20>
