# 抖音 / 快手 登录与发布 — 设计 Spec

- 日期：2026-06-11
- 路线：**浏览器自动化（social-auto-upload，扫码登录 + Cookie）**，与 B 站逆向 Cookie 路线同性质，免企业开放平台资质
- 前置探索：`docs/douyin-kuaishou-browser-publish-plan.md`
- 本 spec 范围：**一次性交付登录（系统内扫码闭环）+ 发布**两块功能，替换现有「死代码 + 凭推测实现」的抖音/快手适配器
- 评审：经子 agent 批判性评审后修订（A1 session 落 DB、A2 runtime-home 提为前置 Gate、Windows 子进程、进程树 kill、入参清洗等，见 §10 变更记录）

---

## 1. 背景与现状

### 1.1 现状是「死代码 + 凭记忆的实现」

| 层 | 抖音 | 快手 |
|---|---|---|
| 前端字段 `frontend/src/types/index.ts` `PLATFORM_FIELDS` | ✅ method/client_key/client_secret/access_token | ✅ method/app_id/app_secret/access_token |
| 适配器 | ✅ `backend/app/providers/publisher/douyin.py` | ✅ `backend/app/providers/publisher/kuaishou.py` |
| **接入工厂 `publisher/__init__.py` `_build_one`** | ❌ **未注册** | ❌ **未注册** |

**根因**：`_build_one` 只 wire 了 `bilibili`/`youtube`，抖音/快手命中末尾 `return None` 被跳过——配了也永不构造，是死代码。现有 `_publish_api`（官方 API 路线）的 URL、鉴权头均与真实接口不符；`_publish_playwright` 的 `from social_auto_upload.douyin import DouYinUploader` 是编造的 import。本 spec **整体替换**这两个适配器实现，废弃路线 A 代码。

### 1.2 为什么走路线 B（浏览器自动化）

- 路线 A（官方开放平台 API）需企业营业执照 + 权限审核（1–2 周），且本项目缺 OAuth 授权页与 token 续期，整套未实现。
- 路线 B 与现有 B 站逆向 Cookie 路线同性质，个人/小团队可用。

### 1.3 依赖事实（已核对 social-auto-upload 源码）

- 仓库：<https://github.com/dreammis/social-auto-upload>，`pyproject.toml` 打包，console_scripts `sau = sau_cli:main`，包含 `uploader*` / `utils*` / `myUtils*` 与模块 `conf` / `sau_cli` / `cli_main`。
- **Python 要求 `>=3.10,<3.13`**：项目 conda env 为 3.12，满足；但锁死 3.13。
- 浏览器驱动用 **patchright（stealth 版 playwright）1.58.x**，安装命令是 `patchright install chromium`（**不是** `playwright install chromium`）。其它依赖：opencv-python、qrcode、segno、loguru、requests。
- **非 PyPI 包**：用 `pip install "git+https://github.com/dreammis/social-auto-upload@<commit>"` 安装。
- CLI 关键事实（`sau_cli.py`，部分待 §9 Gate 实测固定）：
  - 登录：`login_douyin_account()` → `douyin_setup(account_file, handle=True, return_detail=True, headless=...)`；快手 `ks_setup(...)`。
  - 二维码：`--headless` 时终端打 QR，并回退保存 `qrcode.png` 到当前工作目录；`--headed` 弹有头浏览器。**headless 下 PNG 是否稳定可扫，待 Gate 实测。**
  - Cookie 路径：`resolve_runtime_home()/cookies/{platform}_{account}.json`。**runtime home 能否被环境变量/参数覆盖，待 Gate 实测（见 §3.4 与 §9-G1）。**
  - 发布：`sau douyin upload-video --account X --file f.mp4 --title T --desc D --tags a,b`（**无封面参数**）。

---

## 2. 目标与非目标

**目标**
- 抖音、快手各支持：① 系统内扫码登录闭环（产出 cookie 文件）；② 在 pipeline publish 阶段自动发布。
- 接线进 `_build_one`，消除死代码。
- 多账号：一账号一 cookie 文件。
- 对 SAU 的耦合收敛到单一 runner 模块；所有子进程调用非 shell、入参清洗、防注入。

**非目标**
- 不实现路线 A（官方 OAuth API）。
- 不回传稿件 URL（网页发布不稳定提供）。
- 不上传外挂字幕 / 自定义封面（字幕在合成阶段已烧入；封面由平台自动抽帧）。
- 不做定时发布（仅立即发布）。

---

## 3. 架构

### 3.1 模块划分

```
backend/app/providers/publisher/
  sau_runner.py          # 唯一接触 sau CLI 的地方（新增）
  douyin.py              # 重写为薄适配器，调 sau_runner
  kuaishou.py            # 重写为薄适配器，调 sau_runner
  __init__.py _build_one # 注册 douyin / kuaishou（消除死代码）
backend/app/models/
  browser_login_session.py  # 登录临时态落 DB（新增，仿 oauth_credential.OAuthLoginSession）
backend/app/api/
  publishers.py          # 新增 login start/status + login-status 接口
frontend/src/
  types/index.ts         # PLATFORM_FIELDS 抖音/快手字段收敛为 account
  pages/Publishers.tsx   # 账号卡片加「扫码登录」+ 登录态徽标
publish_cookies/         # cookie 落盘根（不入库，.gitignore）
```

### 3.2 `sau_runner.py` 接口契约

```python
# cookie 文件路径（路径根取决于 §3.4 Gate 结论）
def cookie_path(platform: str, account: str) -> Path: ...

# sau 可执行文件定位：shutil.which("sau")，失败再回退 sys.executable 同目录 Scripts/sau(.exe)
def resolve_sau() -> str | None: ...

# 发布：构造 `sau <platform> upload-video ...` 子进程（exec，非 shell），返回 (ok, message)
async def run_upload(platform: str, account: str, file_path: str,
                     title: str, desc: str, tags: list[str]) -> tuple[bool, str]: ...

# 登录：跑 `sau <platform> login --account X ...`，cwd=qr_dir；
# 监测 qr_dir/qrcode.png（或 callback）拿二维码 → on_qr(png_bytes)；进程结束后看 cookie 是否生成。
async def run_login(platform: str, account: str, qr_dir: Path,
                    on_qr: Callable[[bytes], None]) -> tuple[bool, str]: ...

# 登录态：默认只查 cookie 文件存在 + mtime（便宜）；deep=True 触发 `sau <platform> check`（权威、慢）
async def check_login(platform: str, account: str, deep: bool = False) -> bool: ...
```

约束：
- 子进程一律 `asyncio.create_subprocess_exec`，**绝不 `shell=True`**。
- **`sau` 定位**：先 `shutil.which("sau")`；Windows 下是 `sau.exe`，且后端若非在该 conda env 的 PATH 下被拉起会找不到，故回退到 `sys.executable` 同级 `Scripts/sau.exe`（POSIX 为 `bin/sau`）。解析失败 → 映射「未安装」。
- **事件循环**：Windows 子进程依赖默认 ProactorEventLoop（Py3.8+ 默认）；spec 不得改用 SelectorEventLoop。
- 命令、超时、错误映射、入参清洗集中在此模块。

### 3.3 整合方式（已决策）

- **子进程调 `sau` CLI，装在同一 conda env**（不在主进程常驻 import SAU，避开 `conf` / BASE_DIR 全局耦合 + 主进程起 Chromium）。
- **登录例外**：若 §9-G2 实测 headless 下 `qrcode.png` 不可靠、而 `qrcode_callback` 干净，则**登录这一条**改为在**子进程内**跑一个调用 `douyin_setup(..., qrcode_callback=cb)` 的小脚本（`python -m app.providers.publisher.sau_login_worker`），把二维码字节经 stdout/管道回传——**仍是子进程隔离，不在主进程 import SAU**。发布始终走 `sau` CLI。两种登录实现都满足「主进程不 import SAU」，由 Gate 结论二选一。
- SAU 为**可选依赖**：缺失时 `resolve_sau()` 返回 None，适配器/登录接口返回友好错误，不影响其它平台。

### 3.4 Cookie 路径契约（依赖 §9-G1 Gate 结论，含兜底分支）

目标：cookie 落仓库根 `publish_cookies/cookies/{platform}_{account}.json`，与「凭证存仓库根、不入 config.yaml」约定一致。

- **G1-(a) runtime home 可被环境变量/参数覆盖** → runner 跑子进程时设该变量指向 `publish_cookies/`，`cookie_path()` 直接返回上述路径。**首选**。
- **G1-(b) runtime home 写死在 SAU 包内 BASE_DIR、不可覆盖** → 两条退路任选其一（实现期定）：
  1. `cookie_path()` 直接指向 SAU 默认 cookie 目录（接受它在 site-packages/包目录内），登录与发布都用该真实路径；或
  2. 登录子进程结束后，把 SAU 默认输出的 cookie **复制**到 `publish_cookies/` 约定路径，发布读约定路径。
- **account 文件名安全**：`account` 由用户自由填写，直接拼进文件名前必须做白名单字符校验（仿 `app/store/_slug.slugify`，仅 `[a-z0-9_-]`，拒绝路径分隔符/`..`/Windows 非法字符），否则 `cookie_path` 可能越界。`account` 非法 → 视为未配置，返回可操作错误。

---

## 4. 登录流程（系统内扫码闭环）

### 4.1 会话状态落 DB（**不用内存字典**）

项目已有先例 `app/models/oauth_credential.py::OAuthLoginSession`，注释明确「一次登录流程的临时态：跨进程（`--reload`）共享…故落 DB」，并由 `api/openai_oauth.py` 以 `/login/start` + `/login/status?state=` 范式驱动。本功能**照搬该范式**——因为 pipeline 与 API 都跑在同进程后台任务、且开发常用 `uvicorn --reload`，内存字典在多进程/重载下会丢 session。

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
    qr_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    error:     Mapped[str | None] = mapped_column(Text, nullable=True)
```
- 模型须在 `api/publishers.py` 顶部 import 以注册到 `Base.metadata`（建表），同 `openai_oauth.py:10` 做法。
- **并发判据落 DB**：`login/start` 前查同 `(platform, account)` 是否已有 `status in (starting, qr_ready)` 且未超 TTL 的会话，有则拒绝（或复用）。
- **清理**：`login/start` 先删本账号旧的非进行中会话；进行中会话设 TTL（基于 `updated_at`，超 `login_timeout` 即视为 timeout 可被覆盖）。

### 4.2 接口（加进 `api/publishers.py`）

```
POST /api/publishers/login/start      body {platform, account}
  → 校验 platform ∈ {douyin,kuaishou} 且 account 合法（§3.4）；
    DB 并发判据；建 BrowserLoginSession(sid, status=starting) + 临时 qr_dir；
    后台任务跑 run_login(...)（成功/失败回写 DB）；返回 {sid}

GET  /api/publishers/login/status?sid=...     # 仿 openai_oauth 的 ?state= 风格
  → {status, qr_base64?, error?}   status: starting|qr_ready|success|failed|timeout

GET  /api/publishers/{slug}/login-status      # 账号卡片徽标用，独立于本次登录
  → 链路：get_target(slug)→404 if None；t.platform 必须 ∈ {douyin,kuaishou}（否则 422）；
        account = t.config.get("account")，空 → {logged_in:false}；
        否则 cookie_path(platform, account).exists() (+mtime) → {logged_in, checked_at}
        ?deep=1 → check_login(deep=True)（sau check，权威慢）
```

### 4.3 后台登录任务生命周期

1. 子进程登录（§3.3 两实现之一），**cwd=qr_dir**、runtime home/cookie 路径按 §3.4。
2. 拿到二维码字节 → base64 写入 `BrowserLoginSession.qr_base64`，`status=qr_ready`。
   - **文件轮询路（G2-a）**：等 `qr_dir/qrcode.png`，按「大小连续两次不变」判定写完整（避免读到半截 PNG）；按 **mtime 变化重读并刷新** qr_base64（二维码会过期刷新，不能只读一次）。
   - **callback 路（G2-b）**：worker 子进程经 stdout 推 base64，主进程读管道回写 DB。
3. 子进程阻塞直到扫码成功（写 cookie、退出 0）→ `status=success`；非零退出 → `failed`（error=stderr 末尾）；超 `login_timeout`（默认 **180s**，留足扫码）→ kill 进程树 + `status=timeout`。
4. 收尾：清理 qr_dir；**杀进程树**——SAU 父进程下还有 patchright/Chromium 子进程，仅 `proc.kill()` 会留孤儿，Windows 用 `taskkill /F /T /PID <pid>`，POSIX 用进程组 `killpg`。

### 4.4 前端（`Publishers.tsx`）

- 账号卡片「扫码登录」按钮 → `POST login/start` → 每 ~1.5s 轮询 `login/status?sid=`：
  - `qr_ready`：渲染 `<img src=data:image/png;base64,...>`；qr_base64 变化（过期刷新）时更新。
  - `success`：关弹窗 + 刷新登录态徽标。
  - `failed`/`timeout`：显示错误 + 重试。
- 账号卡片显示「已登录 / 未登录」徽标（调 `login-status`），仿 B 站 Cookie 健康提示。

---

## 5. 发布流程

### 5.1 配置字段

抖音/快手 `PLATFORM_FIELDS` 收敛为单字段（删除路线 A 的 method/client_key/client_secret/app_id/app_secret/access_token）：

| key | label | required | 说明 |
|---|---|---|---|
| `account` | 账号标识 | ✅ | 仅 `[a-z0-9_-]`（§3.4 安全约束），派生 cookie 路径 |

`isTargetUsable`：仅校验 `account` 已填；真正「是否登录」由 `login-status` 徽标体现，不卡表单。

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
        ok, msg = await sau_runner.run_upload(
            "douyin", self._account, video_path, title, description, tags or [])
        return PublishResult(platform="douyin", status="success" if ok else "failed",
                             error_message=None if ok else msg)
```

- `thumbnail_path` / `subtitle_path` 忽略（CLI 无封面参数；字幕已在合成阶段烧入）。
- `url` 留空（网页发布不稳定回传）。
- **入参清洗在 runner 内统一做**（不散落适配器）：
  - 标题截断：抖音、快手各自上限为 runner 常量，**具体值待 §9-G4 实测**（先以抖音 ≤55 占位，Gate 后回填）。
  - **tag 规范化**：逐个剥离逗号与首尾空白、丢弃空 tag 与以 `-` 开头的 tag（`--tags a,b` 以逗号分隔，tag 内含逗号会被 SAU 拆成多个；`-foo` 会被 argparse 当选项），最多取 5 个。
  - title/desc 去掉首尾空白与前导 `-`，防 argparse 误判。

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

## 6. 错误处理（runner 统一映射成可操作中文）

| 情形 | 判定方式 | 返回信息 |
|---|---|---|
| `sau` 未安装 | `resolve_sau()` 返回 None 或 exec 抛 `FileNotFoundError` | social-auto-upload 未安装（`pip install "git+…@<commit>"` + `patchright install chromium`） |
| 未登录 / cookie 失效 | **退出码 + stderr 关键字**，关键字样本待 §9-G3 实测固定（仿 `bilibili.py:79` 匹配 `-101`/`未登录`） | 登录态失效，请重新扫码登录 |
| 上传失败（DOM/网络） | 非零退出且非上述 | 透出 stderr 末尾若干行 |
| 上传超时 | 超 `upload_timeout`（默认 **600s**，浏览器自动化 + 大文件慢） | kill 进程树 +「上传超时」 |

---

## 7. 依赖与部署

- SAU **可选依赖**，不进 `requirements.txt` 主区。安装：
  - `pip install "git+https://github.com/dreammis/social-auto-upload@<锁定commit>"`
  - `patchright install chromium`
- 锁定 commit：SAU 靠 DOM 选择器，易随平台改版失效，固定版本降低意外。
- `.gitignore` 增加 `publish_cookies/`。
- 文档：改写 `docs/video-publish-guide.md` 第 4/5 节（抖音/快手）为「扫码登录浏览器自动化」；补依赖安装与扫码步骤。
- 已知代价（写进文档）：patchright + opencv 进后端 env、SAU 锁 Python<3.13。

---

## 8. 测试（全程 mock，不真连网/起浏览器）

- `sau_runner` 单测：mock `asyncio.create_subprocess_exec`，断言：
  - 命令行参数正确且**非 shell**；`resolve_sau()` 解析失败 → 「未安装」映射；
  - **tag 含逗号/`-` 前缀/空值被正确规范化**；title 前导 `-` 被剥离；
  - 退出码 + stderr 关键字 → 各错误分类映射正确；
  - `cookie_path` 规则（含 §3.4 选定分支）与 account 非法字符拒绝。
- 适配器单测：未配账号 / account 非法 / 未登录 / SAU 未安装 / 发布成功 / 发布失败 六条路径返回正确 `PublishResult`。
- 登录接口单测：mock `run_login` 驱动 DB 会话状态机，断言 `starting→qr_ready→success/failed/timeout` 落 DB、`login/status?sid=` 读 DB、同账号并发登录被拒、sid 不存在返回 error。
- `login-status` 单测：slug 不存在(404)、非抖音/快手平台(422)、account 空(false)、cookie 存在/不存在边界。

---

## 9. 前置 Gate：进入 writing-plans 前必须先跑的 spike

> 评审结论：当前 spec 多处值押在未核实假设上，直接进 plan 会写出大量「待 spike 定」占位逻辑。**先跑下列 spike，把结论回填 spec 对应章节，再进 writing-plans。** 本机执行（win32，conda env_news_videos_wf）。

- **G1（地基）runtime home 可覆盖性** → 决定 §3.4 走 (a) 还是 (b)。查 SAU `resolve_runtime_home()` 是否读环境变量/参数。
- **G2（地基）headless 二维码可得性** → 决定 §3.3 登录走「文件轮询」还是「callback worker」。实跑 `sau douyin login --account test --headless`，看 CWD 是否出现可扫 `qrcode.png`；并验证 `douyin_setup(qrcode_callback=...)` 能否拿到字节。
- **G3 失效/错误样本** → 固定 §6 的退出码与 stderr 关键字：制造一次 cookie 失效、一次未安装，记录真实输出。
- **G4 平台标题/标签上限** → 回填 §5.2 常量：抖音、快手标题字数与 tag 数上限。
- **G5 真实 CLI 子命令** → `sau --help` / `sau douyin --help` / `sau kuaishou --help`，固定 login/upload-video 的真实子命令名与参数（`--account/--file/--title/--desc/--tags/--headless` 拼写以输出为准）。

---

## 10. 落地顺序（交 writing-plans 细化）

0. **跑 §9 Gate**，回填 §3.3/§3.4/§5.2/§6 的待定值与分支选择。
1. `browser_login_session.py` 模型（仿 OAuthLoginSession）。
2. `sau_runner.py`：`resolve_sau` / `cookie_path` / 入参清洗 / `run_upload` / `check_login`（+ 单测）。
3. 重写 `douyin.py` / `kuaishou.py` 薄适配器（+ 单测）；`_build_one` 接线。
4. 前端字段收敛 + 发布管理页登录态徽标。
5. `run_login`（含进程树 kill）+ 登录 start/status 接口（DB 状态机，+ 单测）；前端扫码登录 UI 闭环。
6. 文档（video-publish-guide 改写、依赖安装）、`.gitignore`。
7. 端到端：手动扫码登录 → 跑一条 pipeline 到 publish 阶段，确认能发。

---

## 11. 评审变更记录（相对初稿）

- **A1**：登录 session 由「进程内内存字典」改为**落 DB**（新增 `BrowserLoginSession`，仿 `oauth_credential.OAuthLoginSession`），抗 `--reload`/多进程。并发判据、清理一并落 DB。
- **A2**：runtime-home 可覆盖性由「实现期 spike」提升为**进 plan 前置 Gate（§9-G1）**，并补 §3.4 不可覆盖时的兜底分支。
- **B1**：二维码捕获补「原子写检测 + mtime 过期重读」；消除「兜底用 in-process import」与「不 import」决策的矛盾——改为**子进程 worker 跑 callback**，主进程始终不 import SAU。
- **B2**：新增 tag/title 入参规范化（逗号、前导 `-`、空值），堵 CLI 参数语义注入。
- **B3**：补 Windows 下 `sau.exe` 定位（`shutil.which` + Scripts 回退）、事件循环约束、「未安装」判定方式。
- **B4**：补进程树 kill（taskkill /T、killpg）、登录超时 180s、并发判据落 DB。
- **B5**：补 `login-status` 的 slug→target→平台白名单→account→cookie 完整链路与边界码。
- **C1–C6**：上传超时 600s、失效识别样本（G3）、标题上限（G4）、测试补项、真实子命令（G5）、account 文件名安全。

---

## 参考

- social-auto-upload：<https://github.com/dreammis/social-auto-upload>（`docs/CLI.md`、`sau_cli.py`、`uploader/douyin_uploader/`、`uploader/ks_uploader/`）
- 既有范式：`backend/app/models/oauth_credential.py`、`backend/app/api/openai_oauth.py`、`backend/app/providers/publisher/bilibili.py`、`backend/app/store/targets_store.py`
- 探索文档：`docs/douyin-kuaishou-browser-publish-plan.md`
