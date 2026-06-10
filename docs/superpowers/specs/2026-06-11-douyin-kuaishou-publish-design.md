# 抖音 / 快手 登录与发布 — 设计 Spec

- 日期：2026-06-11
- 路线：**浏览器自动化（social-auto-upload，扫码登录 + Cookie）**，与 B 站逆向 Cookie 路线同性质，免企业开放平台资质
- 前置探索：`docs/douyin-kuaishou-browser-publish-plan.md`
- 本 spec 范围：**一次性交付登录（系统内扫码闭环）+ 发布**两块功能，替换现有「死代码 + 凭推测实现」的抖音/快手适配器

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
- CLI 关键事实（`sau_cli.py`）：
  - 登录：`login_douyin_account()` → `douyin_setup(account_file, handle=True, return_detail=True, headless=...)`；快手 `ks_setup(...)`。
  - 二维码：`--headless` 时终端打 QR，并回退保存 **`qrcode.png` 到当前工作目录**；`--headed` 弹有头浏览器。
  - Cookie 路径：`resolve_runtime_home()/cookies/{platform}_{account}.json`（runtime home 可由我们指定 → 指到仓库根 `publish_cookies/`）。
  - 发布：`sau douyin upload-video --account X --file f.mp4 --title T --desc D --tags a,b`（**无封面参数**）。

---

## 2. 目标与非目标

**目标**
- 抖音、快手各支持：① 系统内扫码登录闭环（产出 cookie 文件）；② 在 pipeline publish 阶段自动发布。
- 接线进 `_build_one`，消除死代码。
- 多账号：一账号一 cookie 文件。
- 全程对 SAU 的耦合收敛到单一 runner 模块；所有子进程调用非 shell、防注入。

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
backend/app/api/
  publishers.py          # 新增 login / login-status 接口
frontend/src/
  types/index.ts         # PLATFORM_FIELDS 抖音/快手字段收敛为 account
  pages/Publishers.tsx   # 账号卡片加「扫码登录」+ 登录态徽标
publish_cookies/         # cookie 落盘根（不入库，.gitignore）
```

### 3.2 `sau_runner.py` 接口契约

```python
# 仓库根 publish_cookies/ 作为 SAU runtime home，cookie 落 cookies/{platform}_{account}.json
def cookie_path(platform: str, account: str) -> Path: ...

# 发布：构造 `sau <platform> upload-video ...` 子进程（非 shell），返回 (ok, message)
async def run_upload(platform: str, account: str, file_path: str,
                     title: str, desc: str, tags: list[str]) -> tuple[bool, str]: ...

# 登录：跑 `sau <platform> login --account X --headless`，cwd=qr_dir；
# 监测 qr_dir/qrcode.png 出现即回调 on_qr(png_bytes)；进程结束后看 cookie 是否生成。
async def run_login(platform: str, account: str, qr_dir: Path,
                    on_qr: Callable[[bytes], None]) -> tuple[bool, str]: ...

# 登录态：默认只查 cookie 文件存在 + mtime（便宜）；deep=True 触发 `sau <platform> check`（权威、慢）
async def check_login(platform: str, account: str, deep: bool = False) -> bool: ...
```

约束：
- 子进程一律 `asyncio.create_subprocess_exec`，**绝不 `shell=True`**（title/desc 含用户文本）。
- 通过环境变量/参数把 SAU runtime home 指向仓库根 `publish_cookies/`（实现期确认 SAU 暴露的具体变量名；`resolve_runtime_home()` 的来源在 spike 中核实）。
- 命令、超时、错误映射集中在此模块。

### 3.3 整合方式（已决策）

- **子进程调 `sau` CLI，装在同一 conda env**（不 in-process import，避开 `conf` 模块 / BASE_DIR 全局耦合）。
- SAU 为**可选依赖**：不入 `requirements.txt` 主区；缺失时 runner 探测到 `sau` 不可用，适配器返回友好错误，不影响其它平台。

---

## 4. 登录流程（系统内扫码闭环）

### 4.1 传输方式

REST「启动 + 轮询」一对接口（**不用 SSE**：现有 API 全 REST，轮询更简单、断线可重连）。登录会话状态存**进程内内存字典**（项目单进程，pipeline 也跑在进程内后台任务，足够）。

### 4.2 接口（加进 `api/publishers.py`）

```
POST /api/publishers/login/start      body {platform, account}
  → 校验 platform ∈ {douyin,kuaishou}；同一 (platform,account) 仅允许一个进行中登录；
    建 session(sid) + 临时 qr_dir，后台任务跑 sau_runner.run_login(...)；返回 {sid}

GET  /api/publishers/login/{sid}/status
  → {state, qr_base64?, error?}
    state: starting → qr_ready → success | failed | timeout

GET  /api/publishers/{slug}/login-status      # 账号卡片徽标用，独立于本次登录
  → {logged_in: bool, checked_at}             # 默认 cookie 文件存在+mtime；?deep=1 触发 sau check
```

### 4.3 后台登录任务生命周期

1. 子进程 `sau <platform> login --account X --headless`，**cwd=qr_dir**、runtime home 指向 `publish_cookies/`。
2. 轮询 qr_dir 等 `qrcode.png` 出现 → 读字节 base64 存进 session → `state=qr_ready`。
3. 子进程阻塞轮询直到用户扫码 → 写 cookie、退出 0 → `state=success`；超时/非零退出 → `failed`（带 stderr 末尾）/`timeout`。
4. 收尾：清理 qr_dir、session 设 TTL；超时 kill 子进程。

### 4.4 前端（`Publishers.tsx`）

- 账号卡片「扫码登录」按钮 → `POST login/start` → 每 ~1.5s 轮询 `login/{sid}/status`：
  - `qr_ready`：渲染二维码 `<img src=data:image/png;base64,...>`。
  - `success`：关弹窗 + 刷新登录态徽标。
  - `failed`/`timeout`：显示错误 + 重试。
- 账号卡片显示「已登录 / 未登录」徽标（调 `login-status`），仿 B 站 Cookie 健康提示。

### 4.5 可行性风险与兜底（headless 下 QR 是否落 PNG）

抖音/快手走创作页 DOM 的二维码，`--headless` 下**是否稳定保存 `qrcode.png` 未经证实**（bilibili 确定会）。
- **实现第一步是 spike**：本机跑一次 `sau douyin login --account test --headless`，确认 CWD 是否出现可扫的 `qrcode.png`。
- **兜底 1（受控）**：若纯 CLI 拿不到 QR，则**仅登录路径**退化为最小 in-process 调用 `douyin_setup(..., qrcode_callback=cb)` 直接拿二维码字节；**发布仍走 CLI 子进程**。
- **兜底 2**：`--headed` 在后端机器（本机桌面环境）弹浏览器扫——不再是「系统内」闭环，作为最后退路。

---

## 5. 发布流程

### 5.1 配置字段

抖音/快手 `PLATFORM_FIELDS` 收敛为单字段（删除路线 A 的 method/client_key/client_secret/app_id/app_secret/access_token）：

| key | label | required | 说明 |
|---|---|---|---|
| `account` | 账号标识 | ✅ | 派生 cookie 路径 `publish_cookies/cookies/{platform}_{account}.json` |

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
            "douyin", self._account, video_path, title[:55], description, (tags or [])[:5])
        return PublishResult(platform="douyin", status="success" if ok else "failed",
                             error_message=None if ok else msg)
```

- `thumbnail_path` / `subtitle_path` 忽略（CLI 无封面参数；字幕已在合成阶段烧入）。
- `url` 留空（网页发布不稳定回传）。
- 标题防御性截断（抖音 ≤55；快手更宽，按 runner 内常量）。

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

| 情形 | 返回信息 |
|---|---|
| `sau` 不存在 / 未安装 | social-auto-upload 未安装（`pip install "git+…@<commit>"` + `patchright install chromium`） |
| CLI 报未登录 / cookie 失效 | 登录态失效，请重新扫码登录 |
| 上传失败（DOM/网络） | 透出 stderr 末尾若干行 |
| 子进程超时 | kill 子进程 +「上传超时」 |

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

- `sau_runner` 单测：mock `asyncio.create_subprocess_exec`，断言命令行参数正确且**非 shell**、ok/fail 解析、错误映射、`cookie_path` 规则。
- 适配器单测：未配账号 / 未登录 / SAU 未安装 / 发布成功 / 发布失败 五条路径返回正确 `PublishResult`。
- 登录接口单测：mock `run_login` 驱动状态机，断言 `starting→qr_ready→success/failed/timeout` 流转、同账号并发登录被拒。

---

## 9. 落地顺序（交 writing-plans 细化）

1. **Spike**：本机验证 `sau` 安装可用 + headless login 是否产出 `qrcode.png` + runtime home 变量名。据结果定登录是纯 CLI 还是兜底 import。
2. `sau_runner.py`：cookie_path / run_upload / check_login（+ 单测）。
3. 重写 `douyin.py` / `kuaishou.py` 薄适配器（+ 单测）；`_build_one` 接线。
4. 前端字段收敛 + 发布管理页登录态徽标。
5. `run_login` + 登录三接口（+ 单测）；前端扫码登录 UI 闭环。
6. 文档（video-publish-guide 改写、依赖安装）、`.gitignore`。
7. 端到端：手动扫码登录 → 跑一条 pipeline 到 publish 阶段，确认能发。

---

## 参考

- social-auto-upload：<https://github.com/dreammis/social-auto-upload>（`docs/CLI.md`、`sau_cli.py`、`uploader/douyin_uploader/`、`uploader/ks_uploader/`）
- 探索文档：`docs/douyin-kuaishou-browser-publish-plan.md`
