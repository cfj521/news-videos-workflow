# 抖音 / 快手 登录与发布 — 设计 Spec

- 日期：2026-06-11
- 路线：**浏览器自动化（social-auto-upload，扫码登录 + Cookie）**，与 B 站逆向 Cookie 路线同性质，免企业开放平台资质
- 前置探索：`docs/douyin-kuaishou-browser-publish-plan.md`
- 本 spec 范围：**一次性交付登录（系统内扫码闭环）+ 发布**两块功能，替换现有「死代码 + 凭推测实现」的抖音/快手适配器
- 评审 + Gate：经子 agent 批判性评审修订（§11），并已在 `env_news_videos_wf` 实跑 §9 Gate 把全部待定值落实（§9 为实测结论，非待办）

---

## 1. 背景与现状

### 1.1 现状是「死代码 + 凭记忆的实现」

| 层 | 抖音 | 快手 |
|---|---|---|
| 前端字段 `frontend/src/types/index.ts` `PLATFORM_FIELDS` | ✅ method/client_key/client_secret/access_token | ✅ method/app_id/app_secret/access_token |
| 适配器 | ✅ `backend/app/providers/publisher/douyin.py` | ✅ `backend/app/providers/publisher/kuaishou.py` |
| **接入工厂 `publisher/__init__.py` `_build_one`** | ❌ **未注册** | ❌ **未注册** |

**根因**：`_build_one` 只 wire 了 `bilibili`/`youtube`，抖音/快手命中末尾 `return None` 被跳过——配了也永不构造，是死代码。现有 `_publish_api` 的 URL、鉴权头均与真实接口不符；`_publish_playwright` 的 import 是编造的。本 spec **整体替换**这两个适配器，废弃路线 A 代码。

### 1.2 为什么走路线 B（浏览器自动化）

- 路线 A（官方开放平台 API）需企业营业执照 + 权限审核（1–2 周），且本项目缺 OAuth 授权页与 token 续期，整套未实现。
- 路线 B 与现有 B 站逆向 Cookie 路线同性质，个人/小团队可用。

### 1.3 依赖事实（已核对 social-auto-upload `0.1.0` 源码 + 实跑）

- 仓库：<https://github.com/dreammis/social-auto-upload>，`pyproject.toml` 打包，console_scripts `sau = sau_cli:main`。**Python `>=3.10,<3.13`**；env 为 3.12.13，满足。
- 浏览器驱动 **patchright 1.58.2**；其它依赖 opencv-python、qrcode、segno、loguru、requests。装法 `pip install "git+…@<commit>"`（非 PyPI）。
- **关键：包内 `conf` 模块缺失**，`sau_cli.py:11` 在 import 期 `from conf import BASE_DIR`，开箱即 `ModuleNotFoundError: conf`。**必须自带 `conf.py`**（§3.4）。
- 登录二维码（实测 `uploader/douyin_uploader/main.py`、`ks_uploader/main.py`）：headless 下从创作页 DOM 抠 `img[二维码]` 的 `src`（data URL），存带时间戳 PNG（`utils/login_qrcode.build_login_qrcode_path`，落在 cookie 文件同目录、**非 CWD/非固定名**），并 `qrcode_callback(payload)` 回调；二维码失效自动刷新重存重回调。→ **登录走 callback 最干净**（§3.3）。
- 浏览器启动 `playwright.chromium.launch(channel="chrome")`（或 `executable_path=LOCAL_CHROME_PATH`）：**需系统装 Google Chrome**，或在 conf.py 设 `LOCAL_CHROME_PATH`（§7）。
- CLI 真实子命令（实跑 `--help` 确认）：
  - `sau <p> login --account X [--headed|--headless] [--debug]`（默认 headless）
  - `sau <p> check --account X` → 打印 `valid`/`invalid`，**exit 0/1**
  - `sau <p> upload-video --account X --file F --title T [--desc D] [--tags a,b] [--thumbnail P] [--headed|--headless]`，`<p>` ∈ {douyin, kuaishou}
  - `parse_tags` 按 `,` 分割 + 去首尾空白 + 去前导 `#`；抖音/快手**无 tag 数/标题长度上限**（仅小红书限 10 tag）。

---

## 2. 目标与非目标

**目标**：抖音、快手各支持 ① 系统内扫码登录闭环（产出 cookie）② pipeline publish 阶段自动发布；接线进 `_build_one` 消死代码；多账号（一账号一 cookie）；对 SAU 的耦合收敛到单一 runner，子进程非 shell、入参清洗。

**非目标**：路线 A（OAuth API）；回传稿件 URL；外挂字幕/自定义封面（字幕已在合成阶段烧入；封面交平台自动抽帧——注：CLI 其实有 `--thumbnail`，但我方成片是 9:16、抖音要 3:4，故不传）；定时发布。

---

## 3. 架构

### 3.1 模块划分

```
backend/app/providers/publisher/
  sau_runner.py            # 唯一接触 sau CLI / 构造子进程环境的地方（新增）
  sau_login_worker.py      # 登录用子进程脚本：import douyin_setup/ks_setup 跑 callback（新增）
  sau_conf/conf.py         # 自带的 conf 模块，注入子进程 PYTHONPATH（新增，§3.4）
  douyin.py / kuaishou.py  # 重写为薄适配器，调 sau_runner
  __init__.py _build_one   # 注册 douyin / kuaishou（消除死代码）
backend/app/models/
  browser_login_session.py # 登录临时态落 DB（新增，仿 oauth_credential.OAuthLoginSession）
backend/app/api/
  publishers.py            # 新增 login start/status + login-status 接口
frontend/src/
  types/index.ts           # PLATFORM_FIELDS 抖音/快手字段收敛为 account
  pages/Publishers.tsx     # 账号卡片加「扫码登录」+ 登录态徽标
publish_cookies/cookies/   # cookie + 临时二维码 PNG 落盘（不入库，.gitignore）
```

### 3.2 `sau_runner.py` 接口契约

```python
def cookie_path(platform: str, account: str) -> Path:   # publish_cookies/cookies/{platform}_{account}.json
def resolve_sau() -> str | None:                        # shutil.which("sau")→Scripts/sau.exe 回退；None=未装
def subprocess_env() -> dict:                           # os.environ + PYTHONPATH 注入 sau_conf 目录 + UTF-8
async def run_upload(platform, account, file_path, title, desc, tags) -> tuple[bool, str]
async def run_login(platform, account, on_qr: Callable[[str], None]) -> tuple[bool, str]  # 跑 worker，on_qr 收 data URL
async def check_login(platform, account, deep=False) -> bool   # 浅=cookie 文件存在；深=`sau <p> check` exit 0
```

约束：
- 子进程一律 `asyncio.create_subprocess_exec`，**绝不 `shell=True`**；env 由 `subprocess_env()` 提供（注入 conf 的 PYTHONPATH + `PYTHONIOENCODING=utf-8`）。
- **`sau` 定位**（实测 `D:\...\Scripts\sau.EXE`）：`shutil.which("sau")`；失败回退 `sys.executable` 同级 `Scripts/sau.exe`（POSIX `bin/sau`）。仍失败 → 「未安装」。
- **事件循环**：Windows 子进程依赖默认 ProactorEventLoop（Py3.8+ 默认），不得改 SelectorEventLoop。
- 命令、超时、错误映射、入参清洗集中在此模块。

### 3.3 登录机制（实测结论：callback worker，**非文件轮询**）

`uploader.douyin_uploader.main.douyin_setup(account_file, handle=True, qrcode_callback=cb, headless=True)`（快手 `ks_setup`）在 headless 下即可拿到二维码 data URL 并经 `cb` 回调，失效自动刷新重回调。故：

- 新增 `sau_login_worker.py`（独立**子进程**脚本，主进程不 import SAU）：`python -m ...sau_login_worker <platform> <account>`，内部 `await douyin_setup(..., qrcode_callback=cb, headless=True)`，`cb` 把 `{"qr": <data_url>}` 按 **JSON 行打到 stdout**；登录结果（success/timeout/failed）也以 JSON 行收尾。
- `run_login` 起该 worker，逐行读 stdout：遇 `qr` → 调 `on_qr(data_url)`（刷新也会再来一行）；遇结果 → 返回 `(ok, msg)`。
- **发布始终走 `sau` CLI 子进程**，主进程零 SAU import。两条都满足「主进程不 import SAU」。

> 子进程 worker 仍 import SAU——但在隔离子进程里，conf/BASE_DIR/patchright/Chromium 都在子进程，主进程干净，符合 §3.3 整合决策。

### 3.4 Cookie 路径与自带 conf（实测结论）

`sau_cli.resolve_account_file` = `Path(conf.BASE_DIR)/"cookies"/f"{platform}_{account}.json"`，`BASE_DIR` 唯一来源是 `conf` 模块，**无环境变量覆盖**。故：

- 仓库自带 `backend/app/providers/publisher/sau_conf/conf.py`，镜像上游 `conf.example.py` 全部名字，关键是 `BASE_DIR` 指向仓库根 `publish_cookies/`：
  ```python
  from pathlib import Path
  BASE_DIR = Path(__file__).resolve().parents[5] / "publish_cookies"  # 仓库根/publish_cookies
  XHS_SERVER = "http://127.0.0.1:11901"   # 不用小红书，占位（sau_cli 启动会 import 其模块）
  LOCAL_CHROME_PATH = ""                   # 空→channel="chrome"（需系统 Chrome）；或填 chrome.exe 路径
  LOCAL_CHROME_HEADLESS = True
  DEBUG_MODE = False
  ```
- runner `subprocess_env()` 把该 `sau_conf/` 目录加进子进程 `PYTHONPATH`；`cookie_path()` 与之一致返回 `publish_cookies/cookies/{platform}_{account}.json`。**实测此法 `sau` 可正常启动。**
- 临时二维码 PNG 也落 `publish_cookies/cookies/`（`build_login_qrcode_path`），由 SAU 在 finally 自清；`.gitignore` 覆盖整个 `publish_cookies/`。
- **account 文件名安全**：`account` 用户自填，拼进文件名前做白名单（仿 `app/store/_slug.slugify`，仅 `[a-z0-9_-]`，拒路径分隔/`..`/非法字符），非法→视为未配置返回可操作错误。

---

## 4. 登录流程（系统内扫码闭环）

### 4.1 会话状态落 DB（**不用内存字典**）

照搬既有先例 `app/models/oauth_credential.py::OAuthLoginSession`（注释明确「跨进程 `--reload` 共享…故落 DB」）+ `api/openai_oauth.py` 的 start/status 范式——pipeline 与 API 同进程跑后台任务、开发常用 `--reload`，内存字典在多进程/重载下丢 session。

新增模型 `browser_login_session.py`：

```python
class BrowserLoginSession(Base, TimestampMixin):
    """抖音/快手扫码登录临时态，跨进程共享，故落 DB（仿 OAuthLoginSession）。"""
    __tablename__ = "browser_login_sessions"
    id:        Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sid:       Mapped[str] = mapped_column(String(64), unique=True, index=True)
    platform:  Mapped[str] = mapped_column(String(16))   # douyin|kuaishou
    account:   Mapped[str] = mapped_column(String(64))
    status:    Mapped[str] = mapped_column(String(16), default="starting")  # starting|qr_ready|success|failed|timeout
    qr_base64: Mapped[str | None] = mapped_column(Text, nullable=True)       # data URL 或 base64
    error:     Mapped[str | None] = mapped_column(Text, nullable=True)
```
- 模型须在 `api/publishers.py` 顶部 import 以注册到 `Base.metadata`（同 `openai_oauth.py:10`）。
- 并发判据与清理落 DB：`login/start` 先删本账号旧的非进行中会话；进行中会话超 `login_timeout` 视为可覆盖。

### 4.2 接口（加进 `api/publishers.py`）

```
POST /api/publishers/login/start    body {platform, account}
  → 校验 platform ∈ {douyin,kuaishou} 且 account 合法；DB 并发判据；
    建 BrowserLoginSession(sid, starting)；后台跑 run_login(on_qr=写 qr_base64+status=qr_ready)；返回 {sid}

GET  /api/publishers/login/status?sid=...        # 仿 openai_oauth ?state= 风格
  → {status, qr_base64?, error?}

GET  /api/publishers/{slug}/login-status         # 账号卡片徽标
  → get_target(slug)→404 if None；t.platform ∈ {douyin,kuaishou} 否则 422；
    account=t.config.get("account") 空→{logged_in:false}；
    否则 check_login(platform,account)（浅查 cookie 文件）→{logged_in, checked_at}；?deep=1→sau check
```

### 4.3 后台登录任务生命周期

1. `run_login` 起 `sau_login_worker` 子进程（headless），逐行读 stdout。
2. 收到 `qr` 行 → `BrowserLoginSession.qr_base64 = data_url`、`status=qr_ready`；失效刷新会再来一行，覆盖即可（天然解决过期，无文件竞态）。
3. worker 收尾 JSON：success（写 cookie、exit 0）→ `status=success`；timeout → `timeout`；异常 → `failed`（error=末行/ stderr）。
4. 收尾：超 `login_timeout`（默认 **180s**，留足扫码）→ **杀进程树**（SAU 下有 patchright/Chromium 子进程，Windows `taskkill /F /T /PID`，POSIX `killpg`），`status=timeout`。

### 4.4 前端（`Publishers.tsx`）

账号卡片「扫码登录」→ `POST login/start` → 每 ~1.5s 轮询 `login/status?sid=`：`qr_ready` 渲染 `<img src=<data_url>>`（变化即刷新）；`success` 关弹窗+刷新徽标；`failed/timeout` 报错+重试。卡片显示「已登录/未登录」徽标（`login-status`），仿 B 站 Cookie 健康。

---

## 5. 发布流程

### 5.1 配置字段

抖音/快手 `PLATFORM_FIELDS` 收敛为单字段（删路线 A 的 method/client_key/client_secret/app_id/app_secret/access_token）：

| key | label | required | 说明 |
|---|---|---|---|
| `account` | 账号标识 | ✅ | 仅 `[a-z0-9_-]`（§3.4），派生 cookie 路径 |

`isTargetUsable` 仅校验 `account` 已填；是否登录由 `login-status` 徽标体现。

### 5.2 适配器（`douyin.py`，快手同构）

```python
class DouyinPublisher(PublisherAdapter):
    def __init__(self, account: str = ""):
        self._account = account
    async def publish(self, video_path, thumbnail_path, title, description, tags, subtitle_path=None):
        if not self._account:
            return PublishResult(platform="douyin", status="failed", error_message="未配置账号")
        if not sau_runner.cookie_path("douyin", self._account).exists():
            return PublishResult(platform="douyin", status="failed",
                                 error_message="未登录：请先在发布管理页扫码登录")
        ok, msg = await sau_runner.run_upload("douyin", self._account, video_path, title, description, tags or [])
        return PublishResult(platform="douyin", status="success" if ok else "failed",
                             error_message=None if ok else msg)
```

- `thumbnail_path`/`subtitle_path` 忽略；`url` 留空（网页发布不稳定回传）。
- **入参清洗集中在 runner**：tag 逐个剥逗号/首尾空白、丢空与以 `-` 开头者（`--tags a,b` 按逗号分割，tag 含逗号会被 `parse_tags` 拆成多个——实测确认），最多 5 个；title/desc 去首尾空白与前导 `-`（防 argparse 误判）。抖音/快手 SAU 不限标题长度，**不强制截断**（仅防御性留一个较大上限常量，避免异常长标题）。

### 5.3 接线 `_build_one`

```python
if platform == "douyin":
    from app.providers.publisher.douyin import DouyinPublisher
    return DouyinPublisher(account=cfg.get("account", ""))
if platform == "kuaishou":
    from app.providers.publisher.kuaishou import KuaishouPublisher
    return KuaishouPublisher(account=cfg.get("account", ""))
```

---

## 6. 错误处理（runner 统一映射成可操作中文，判定方式已实测）

| 情形 | 判定方式（实测） | 返回信息 |
|---|---|---|
| `sau` 未安装 | `resolve_sau()` None 或 exec 抛 `FileNotFoundError` | social-auto-upload 未安装（`pip install "git+…@<commit>"` + 系统装 Chrome） |
| 登录态校验 | `sau <p> check` 打印 valid/invalid，**exit 0/1** | （用于 `login-status?deep=1`） |
| 未登录/cookie 失效（发布时）| upload 子进程 **exit 1** 且 stderr 含 `cookie is missing or expired` | 登录态失效，请重新扫码登录 |
| 上传失败（DOM/网络）| exit 1 且非上述 | 透出 stderr 末尾若干行 |
| 上传超时 | 超 `upload_timeout`（默认 **600s**）| 杀进程树 +「上传超时」 |

---

## 7. 依赖与部署

- SAU **可选依赖**，不进 `requirements.txt` 主区：`pip install "git+https://github.com/dreammis/social-auto-upload@<锁定commit>"`。
- **系统需装 Google Chrome**（uploader 用 `channel="chrome"`）；或在 `sau_conf/conf.py` 设 `LOCAL_CHROME_PATH` 指向 chrome/chromium 可执行。`patchright install chromium` 单独不满足 `channel="chrome"`。
- **自带 `conf.py`**（§3.4）随仓库走，无需用户手工拷 `conf.example.py`。
- 锁定 commit（SAU 靠 DOM 选择器，易随平台改版失效）。
- `.gitignore` 增加 `publish_cookies/`。
- 文档：改写 `docs/video-publish-guide.md` 第 4/5 节为「扫码登录浏览器自动化」；补依赖安装（含 Chrome）与扫码步骤。
- 已知代价：patchright + opencv 进后端 env、SAU 锁 Python<3.13。

---

## 8. 测试（全程 mock，不真连网/起浏览器）

- `sau_runner`：mock `create_subprocess_exec`，断言命令行参数正确且**非 shell**、`subprocess_env` 注入 conf PYTHONPATH、`resolve_sau` 失败→「未安装」、**tag 含逗号/`-`/空被规范化**、title 前导 `-` 剥离、退出码+stderr 关键字→错误映射、`cookie_path` 规则与 account 非法拒绝。
- 适配器：未配账号 / account 非法 / 未登录 / 未安装 / 成功 / 失败 六路径。
- 登录接口：mock `run_login` 驱动 DB 状态机，断言 `starting→qr_ready→success/failed/timeout` 落 DB、`login/status?sid=` 读 DB、同账号并发被拒、sid 不存在 error。
- `login-status`：slug 不存在(404) / 非抖音快手平台(422) / account 空(false) / cookie 存在与否。

---

## 9. Gate 实测结论（已在 env_news_videos_wf 执行，回填上文）

| Gate | 结论 | 落点 |
|---|---|---|
| G1 runtime home | `conf.BASE_DIR`，无 env 覆盖；`conf` 模块缺失须自带 → 自带 `sau_conf/conf.py` 指 `publish_cookies/`，实测 `sau` 正常启动 | §3.4 |
| G2 headless 二维码 | headless 可得；DOM data URL + `qrcode_callback`，失效自动刷新；PNG 落 cookie 同目录（非 CWD）。**改走 callback worker** | §3.3 |
| G2′ 浏览器 | `channel="chrome"` 需系统 Google Chrome（或设 LOCAL_CHROME_PATH） | §7 |
| G3 失效/错误 | `sau check` exit 0/1；发布未登录→exit 1 + stderr `cookie is missing or expired` | §6 |
| G4 标题/标签上限 | 抖音/快手 SAU 不限；`parse_tags` 按逗号拆（须清洗 tag 内逗号）；不强制截断标题 | §5.2 |
| G5 真实子命令 | `login/check/upload-video`，参数 `--account/--file/--title/--desc/--tags/--thumbnail/--headed|--headless` | §1.3 |

---

## 10. 落地顺序（交 writing-plans 细化）

1. `sau_conf/conf.py`（BASE_DIR→publish_cookies）+ `browser_login_session.py` 模型。
2. `sau_runner.py`：`resolve_sau`/`subprocess_env`/`cookie_path`/入参清洗/`run_upload`/`check_login`（+ 单测）。
3. `sau_login_worker.py` + `run_login`（含进程树 kill）（+ 单测）。
4. 重写 `douyin.py`/`kuaishou.py` 薄适配器（+ 单测）；`_build_one` 接线。
5. 登录 start/status + login-status 接口（DB 状态机，+ 单测）；前端字段收敛 + 扫码登录 UI + 登录态徽标。
6. 文档（video-publish-guide 改写、依赖含 Chrome）、`.gitignore`。
7. 端到端：手动扫码登录 → 跑一条 pipeline 到 publish 阶段确认能发。

---

## 11. 评审变更记录（相对初稿）

- **A1**：登录 session 由内存字典改为**落 DB**（`BrowserLoginSession`，仿 `OAuthLoginSession`），抗 `--reload`/多进程。
- **A2**：runtime-home 经 Gate 实测 = `conf.BASE_DIR` 且 `conf` 缺失 → 定为**自带 `sau_conf/conf.py`** 控制 cookie 目录（§3.4），原 (a)/(b) 分支作废。
- **B1**：二维码捕获经 Gate 定为 **callback worker**（data URL，自动刷新），废弃脆弱的「轮询 CWD/qrcode.png」；主进程仍不 import SAU。
- **B2**：tag/title 入参规范化（逗号、前导 `-`、空值），实测 `parse_tags` 确会按逗号拆。
- **B3**：`sau.exe` 定位（`shutil.which`+Scripts 回退，实测路径）、事件循环约束、未安装判定。
- **B4**：进程树 kill（taskkill /T、killpg）、登录超时 180s、并发判据落 DB。
- **B5**：`login-status` slug→target→平台白名单→account→cookie 完整链路与边界码。
- **C 系列**：上传超时 600s、`check` 退出码/`cookie is missing or expired` 关键字、标题不强制截断、account 文件名安全、真实子命令；**新增** 系统 Chrome 依赖、自带 conf.py。

---

## 参考

- social-auto-upload `0.1.0`：`sau_cli.py`、`uploader/douyin_uploader/main.py`、`uploader/ks_uploader/main.py`、`utils/login_qrcode.py`
- 既有范式：`app/models/oauth_credential.py`、`app/api/openai_oauth.py`、`app/providers/publisher/bilibili.py`、`app/store/targets_store.py`
- 探索文档：`docs/douyin-kuaishou-browser-publish-plan.md`
