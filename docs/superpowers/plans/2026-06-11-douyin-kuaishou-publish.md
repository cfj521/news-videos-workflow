# 抖音 / 快手 浏览器自动化登录与发布 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让抖音、快手通过 social-auto-upload（`sau` CLI / 子进程）实现「系统内扫码登录闭环 + pipeline 自动发布」，并接进 `_build_one` 消除现有死代码。

**Architecture:** 主进程不 import SAU；所有对 SAU 的子进程调用收敛到 `sau_runner.py`。发布走 `sau <p> upload-video` CLI；登录走独立 worker 子进程 `sau_login_worker.py`（内部 import `douyin_setup`/`ks_setup` 跑 `qrcode_callback`，二维码 data URL 经 stdout JSON 行回传）。登录临时态落 DB（`BrowserLoginSession`，仿既有 `OAuthLoginSession`）抗 `--reload`/多进程。cookie 目录由仓库自带 `sau_conf/conf.py` 的 `BASE_DIR` 控制，指向仓库根 `publish_cookies/`。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / pytest（后端）；React + Vite + TypeScript（前端）；social-auto-upload 0.1.0 + patchright + 系统 Google Chrome（可选运行依赖）。

**Spec:** `docs/superpowers/specs/2026-06-11-douyin-kuaishou-publish-design.md`

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/app/providers/publisher/sau_conf/conf.py` | 自带 conf 模块：`BASE_DIR→publish_cookies` 等，注入子进程 PYTHONPATH |
| `backend/app/models/browser_login_session.py` | 登录临时态 DB 模型 |
| `backend/app/providers/publisher/sau_runner.py` | 唯一接触 SAU 子进程的层：路径/清洗/定位/run_upload/check_login/run_login |
| `backend/app/providers/publisher/sau_login_worker.py` | 登录子进程脚本：import SAU 跑 callback，stdout JSON 行 |
| `backend/app/providers/publisher/douyin.py` / `kuaishou.py` | 重写为薄适配器，调 sau_runner |
| `backend/app/providers/publisher/__init__.py` | `_build_one` 注册 douyin/kuaishou |
| `backend/app/api/publishers.py` | 新增 login/start、login/status、{slug}/login-status |
| `frontend/src/types/index.ts` | 抖音/快手 `PLATFORM_FIELDS` 收敛为 `account` |
| `frontend/src/pages/Publishers.tsx` | 账号卡片「扫码登录」+ 登录态徽标 |
| `.gitignore` / `docs/video-publish-guide.md` | 忽略 `publish_cookies/`；改写抖音/快手发布指南 |

**测试命令前置：** 后端测试一律在 conda 环境跑：`conda run -n env_news_videos_wf pytest <args>`（在 `backend/` 目录下）。所有 `git commit` 末尾保留：
```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

## Task 1: 自带 conf 模块（控制 cookie 目录）

**Files:**
- Create: `backend/app/providers/publisher/sau_conf/__init__.py`（空文件）
- Create: `backend/app/providers/publisher/sau_conf/conf.py`
- Test: `backend/tests/test_sau_conf.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_sau_conf.py
from pathlib import Path


def test_base_dir_points_to_repo_publish_cookies():
    from app.providers.publisher.sau_conf import conf
    # BASE_DIR 必须是 仓库根/publish_cookies
    assert isinstance(conf.BASE_DIR, Path)
    assert conf.BASE_DIR.name == "publish_cookies"
    # 仓库根下应能看到 backend 目录，确认 parents 层级正确
    assert (conf.BASE_DIR.parent / "backend").is_dir()


def test_conf_has_all_names_sau_imports():
    from app.providers.publisher.sau_conf import conf
    for name in ("BASE_DIR", "XHS_SERVER", "LOCAL_CHROME_PATH", "LOCAL_CHROME_HEADLESS", "DEBUG_MODE"):
        assert hasattr(conf, name), f"conf 缺少 {name}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_conf.py -v`
Expected: FAIL（`ModuleNotFoundError: app.providers.publisher.sau_conf`）

- [ ] **Step 3: 建包与 conf 模块**

```python
# backend/app/providers/publisher/sau_conf/__init__.py
```
（空文件）

```python
# backend/app/providers/publisher/sau_conf/conf.py
"""自带的 social-auto-upload `conf` 模块。

SAU 的 sau_cli/uploader 在 import 期 `from conf import BASE_DIR, ...`，但其包未附带可用 conf。
本文件随仓库走，由 sau_runner 注入子进程 PYTHONPATH，使 SAU 把 cookie/二维码落到仓库根
publish_cookies/ 下（cookies/{platform}_{account}.json）。
"""
from pathlib import Path

# 本文件: backend/app/providers/publisher/sau_conf/conf.py
# parents[5] = 仓库根
BASE_DIR = Path(__file__).resolve().parents[5] / "publish_cookies"

# 不使用小红书，但 sau_cli 启动会 import 其模块，提供占位避免 ImportError
XHS_SERVER = "http://127.0.0.1:11901"

# 空字符串 → uploader 走 channel="chrome"（需系统 Google Chrome）；
# 也可填 chrome/chromium 可执行路径覆盖
LOCAL_CHROME_PATH = ""
LOCAL_CHROME_HEADLESS = True
DEBUG_MODE = False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_conf.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/publisher/sau_conf backend/tests/test_sau_conf.py
git commit -m "feat(publish): 自带 SAU conf 模块，cookie 目录指向 publish_cookies"
```

---

## Task 2: 登录临时态 DB 模型

**Files:**
- Create: `backend/app/models/browser_login_session.py`
- Modify: `backend/app/models/__init__.py`（新增一行 import 注册）
- Test: `backend/tests/test_browser_login_session.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_browser_login_session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.browser_login_session import BrowserLoginSession


def test_insert_and_query_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(BrowserLoginSession(sid="abc", platform="douyin", account="acct1", status="starting"))
    s.commit()
    row = s.query(BrowserLoginSession).filter_by(sid="abc").first()
    assert row.platform == "douyin"
    assert row.status == "starting"
    assert row.qr_base64 is None


def test_registered_in_metadata():
    # 必须注册到 Base.metadata，否则 create_all 不建表
    assert "browser_login_sessions" in Base.metadata.tables
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_browser_login_session.py -v`
Expected: FAIL（`ModuleNotFoundError: ...browser_login_session`）

- [ ] **Step 3: 建模型并注册**

```python
# backend/app/models/browser_login_session.py
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class BrowserLoginSession(Base, TimestampMixin):
    """抖音/快手扫码登录临时态：跨进程（--reload）共享二维码与结果，故落 DB（仿 OAuthLoginSession）。"""
    __tablename__ = "browser_login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(16))   # douyin|kuaishou
    account: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="starting")  # starting|qr_ready|success|failed|timeout
    qr_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

在 `backend/app/models/__init__.py` 的 import 区（`OAuthLoginSession` 那行之后）加：

```python
from .browser_login_session import BrowserLoginSession as BrowserLoginSession
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_browser_login_session.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/browser_login_session.py backend/app/models/__init__.py backend/tests/test_browser_login_session.py
git commit -m "feat(publish): BrowserLoginSession 模型，登录临时态落 DB"
```

---

## Task 3: sau_runner 纯函数（路径与入参清洗）

**Files:**
- Create: `backend/app/providers/publisher/sau_runner.py`
- Test: `backend/tests/test_sau_runner_helpers.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_sau_runner_helpers.py
from pathlib import Path

from app.providers.publisher import sau_runner as r


def test_safe_account_accepts_valid():
    assert r.safe_account("acct_1-x") == "acct_1-x"


def test_safe_account_rejects_invalid():
    assert r.safe_account("../etc") == ""
    assert r.safe_account("大号") == ""
    assert r.safe_account("Has Space") == ""
    assert r.safe_account("") == ""


def test_cookie_path_under_publish_cookies():
    p = r.cookie_path("douyin", "acct1")
    assert p.name == "douyin_acct1.json"
    assert p.parent.name == "cookies"
    assert p.parent.parent.name == "publish_cookies"


def test_sanitize_tags_splits_and_filters():
    # 含逗号被拆/去掉、前导 - 丢弃、空值丢弃、最多 5 个、去 # 与首尾空白
    out = r.sanitize_tags(["a,b", " c ", "-bad", "", "#tag", "d", "e", "f", "g"])
    assert out == ["a", "b", "c", "tag", "d"]


def test_sanitize_text_strips_leading_dash_and_space():
    assert r.sanitize_text("  -hello ") == "hello"
    assert r.sanitize_text("normal") == "normal"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_helpers.py -v`
Expected: FAIL（`ModuleNotFoundError: ...sau_runner`）

- [ ] **Step 3: 写实现（仅纯函数部分）**

```python
# backend/app/providers/publisher/sau_runner.py
"""唯一接触 social-auto-upload（sau CLI / 登录 worker 子进程）的层。

主进程绝不 import SAU；所有 SAU 交互都在子进程，cookie 目录由 sau_conf.conf.BASE_DIR 控制。
"""
from __future__ import annotations

import re
from pathlib import Path

# 抖音/快手 SAU 不限标题长度，仅防御性上限避免异常长标题
TITLE_MAX = 100
MAX_TAGS = 5

# sau_runner.py 位于 backend/app/providers/publisher/
_REPO_ROOT = Path(__file__).resolve().parents[4]
_COOKIES_DIR = _REPO_ROOT / "publish_cookies" / "cookies"
_SAU_CONF_DIR = Path(__file__).resolve().parent / "sau_conf"

_ACCOUNT_RE = re.compile(r"[a-z0-9_-]+")


def safe_account(account: str | None) -> str:
    """账号标识白名单：仅 [a-z0-9_-]，否则返回空串（视为未配置）。防止拼进文件名时越界。"""
    account = (account or "").strip()
    return account if _ACCOUNT_RE.fullmatch(account) else ""


def cookie_path(platform: str, account: str) -> Path:
    """cookie 文件路径：publish_cookies/cookies/{platform}_{account}.json。"""
    return _COOKIES_DIR / f"{platform}_{account}.json"


def sanitize_text(text: str | None) -> str:
    """去首尾空白与前导 '-'（防 argparse 把它当选项）。"""
    return (text or "").strip().lstrip("-").strip()


def sanitize_tags(tags: list[str] | None) -> list[str]:
    """规范化 tag：按逗号拆、去 '#' 与首尾空白、丢空与以 '-' 开头者，最多 MAX_TAGS 个。

    SAU 的 parse_tags 按逗号分割，故 tag 内含逗号必须先拆开，否则会被算成多个 tag。
    """
    out: list[str] = []
    for raw in tags or []:
        for piece in str(raw).split(","):
            t = piece.strip().lstrip("#").strip()
            if not t or t.startswith("-"):
                continue
            out.append(t)
            if len(out) >= MAX_TAGS:
                return out
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_helpers.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/publisher/sau_runner.py backend/tests/test_sau_runner_helpers.py
git commit -m "feat(publish): sau_runner 路径与入参清洗纯函数"
```

---

## Task 4: sau_runner — `resolve_sau` 与 `subprocess_env`

**Files:**
- Modify: `backend/app/providers/publisher/sau_runner.py`
- Test: `backend/tests/test_sau_runner_env.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_sau_runner_env.py
from app.providers.publisher import sau_runner as r


def test_resolve_sau_uses_which(monkeypatch):
    monkeypatch.setattr(r.shutil, "which", lambda name: "/fake/bin/sau" if name == "sau" else None)
    assert r.resolve_sau() == "/fake/bin/sau"


def test_resolve_sau_none_when_missing(monkeypatch):
    monkeypatch.setattr(r.shutil, "which", lambda name: None)
    # 回退路径（Scripts/sau.exe 或 bin/sau）也不存在时返回 None
    monkeypatch.setattr(r.Path, "exists", lambda self: False)
    assert r.resolve_sau() is None


def test_subprocess_env_injects_conf_pythonpath():
    env = r.subprocess_env()
    assert str(r._SAU_CONF_DIR) in env["PYTHONPATH"]
    assert env["PYTHONIOENCODING"] == "utf-8"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_env.py -v`
Expected: FAIL（`AttributeError: module ... has no attribute 'resolve_sau'`）

- [ ] **Step 3: 写实现（追加到 sau_runner.py）**

在文件顶部 import 区补：

```python
import os
import shutil
import sys
```

追加函数：

```python
def resolve_sau() -> str | None:
    """定位 sau 可执行：先 PATH（shutil.which），失败回退到当前解释器同级 Scripts/bin。"""
    found = shutil.which("sau")
    if found:
        return found
    base = Path(sys.executable).parent
    for cand in (base / "Scripts" / "sau.exe", base / "sau.exe", base / "bin" / "sau", base / "sau"):
        if cand.exists():
            return str(cand)
    return None


def subprocess_env() -> dict:
    """子进程环境：注入 sau_conf 目录到 PYTHONPATH（使 SAU 的 `import conf` 命中），并强制 UTF-8。"""
    env = dict(os.environ)
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_SAU_CONF_DIR) + (os.pathsep + prev if prev else "")
    env["PYTHONIOENCODING"] = "utf-8"
    return env
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_env.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/publisher/sau_runner.py backend/tests/test_sau_runner_env.py
git commit -m "feat(publish): sau_runner 的 sau 定位与子进程环境注入"
```

---

## Task 5: sau_runner — 错误分类

**Files:**
- Modify: `backend/app/providers/publisher/sau_runner.py`
- Test: `backend/tests/test_sau_runner_errors.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_sau_runner_errors.py
from app.providers.publisher import sau_runner as r


def test_classify_cookie_expired():
    msg = r.classify_upload_error("Douyin cookie is missing or expired: /x. Run `sau douyin login`...")
    assert "登录态失效" in msg


def test_classify_generic_passes_stderr_tail():
    msg = r.classify_upload_error("line1\nline2\nboom: selector not found")
    assert "boom: selector not found" in msg


def test_classify_empty_fallback():
    assert r.classify_upload_error("") == "发布失败"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_errors.py -v`
Expected: FAIL（无 `classify_upload_error`）

- [ ] **Step 3: 写实现（追加到 sau_runner.py）**

```python
def classify_upload_error(stderr: str) -> str:
    """把 sau 子进程 stderr 映射成可操作中文。未登录关键字来自 SAU 源码英文消息。"""
    s = (stderr or "")
    if "missing or expired" in s.lower():
        return "登录态失效，请重新扫码登录"
    tail = "\n".join(line for line in s.strip().splitlines() if line.strip())[-500:]
    return tail or "发布失败"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_errors.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/publisher/sau_runner.py backend/tests/test_sau_runner_errors.py
git commit -m "feat(publish): sau_runner 上传错误分类映射"
```

---

## Task 6: sau_runner — `run_upload`

**Files:**
- Modify: `backend/app/providers/publisher/sau_runner.py`
- Test: `backend/tests/test_sau_runner_upload.py`

测试用一个假子进程替换 `asyncio.create_subprocess_exec`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_sau_runner_upload.py
import asyncio

import pytest

from app.providers.publisher import sau_runner as r


class FakeProc:
    def __init__(self, returncode=0, out=b"ok", err=b""):
        self.returncode = returncode
        self._out = out
        self._err = err
        self.pid = 4321
        self.killed = False

    async def communicate(self):
        return self._out, self._err

    def kill(self):
        self.killed = True


def _patch_exec(monkeypatch, proc, capture):
    async def fake_exec(*args, **kwargs):
        capture["args"] = args
        capture["env"] = kwargs.get("env")
        return proc
    monkeypatch.setattr(r.asyncio, "create_subprocess_exec", fake_exec)


@pytest.mark.asyncio
async def test_run_upload_success_builds_correct_argv(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")
    cap = {}
    _patch_exec(monkeypatch, FakeProc(returncode=0), cap)
    ok, msg = await r.run_upload("douyin", "acct1", "v.mp4", "标题", "简介", ["a,b", "c"])
    assert ok is True
    argv = cap["args"]
    assert argv[:5] == ("/bin/sau", "douyin", "upload-video", "--account", "acct1")
    assert "--file" in argv and "v.mp4" in argv
    assert "--tags" in argv and "a,b,c" in argv          # 清洗后逗号 join
    assert "--headless" in argv
    # 绝不走 shell
    assert cap["env"]["PYTHONIOENCODING"] == "utf-8"


@pytest.mark.asyncio
async def test_run_upload_not_installed(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: None)
    ok, msg = await r.run_upload("douyin", "acct1", "v.mp4", "t", "d", [])
    assert ok is False
    assert "未安装" in msg


@pytest.mark.asyncio
async def test_run_upload_invalid_account(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")
    ok, msg = await r.run_upload("douyin", "../bad", "v.mp4", "t", "d", [])
    assert ok is False
    assert "账号" in msg


@pytest.mark.asyncio
async def test_run_upload_failure_maps_error(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")
    cap = {}
    _patch_exec(monkeypatch, FakeProc(returncode=1, err=b"cookie is missing or expired"), cap)
    ok, msg = await r.run_upload("douyin", "acct1", "v.mp4", "t", "d", [])
    assert ok is False
    assert "登录态失效" in msg


@pytest.mark.asyncio
async def test_run_upload_timeout_kills(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")
    proc = FakeProc()

    async def fake_exec(*a, **k):
        return proc
    monkeypatch.setattr(r.asyncio, "create_subprocess_exec", fake_exec)

    async def fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError
    monkeypatch.setattr(r.asyncio, "wait_for", fake_wait_for)
    killed = {}
    monkeypatch.setattr(r, "kill_process_tree", lambda p: killed.setdefault("k", True))

    ok, msg = await r.run_upload("douyin", "acct1", "v.mp4", "t", "d", [])
    assert ok is False
    assert "超时" in msg
    assert killed.get("k") is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_upload.py -v`
Expected: FAIL（无 `run_upload` / `kill_process_tree`）

- [ ] **Step 3: 写实现（追加到 sau_runner.py）**

在 import 区补：

```python
import asyncio
import subprocess
```

追加常量与函数：

```python
UPLOAD_TIMEOUT = 600  # 浏览器自动化 + 大文件，给足 10 分钟
LOGIN_TIMEOUT = 180   # 留足扫码时间


def kill_process_tree(proc) -> None:
    """杀子进程及其后代（SAU 下还有 patchright/Chromium）。Windows 用 taskkill /T，POSIX 用进程组。"""
    pid = getattr(proc, "pid", None)
    if not pid:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, check=False)
        else:
            os.killpg(os.getpgid(pid), 9)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _spawn_kwargs() -> dict:
    """POSIX 下 start_new_session 让子进程自成进程组，便于整组 kill；Windows 不需要。"""
    return {} if sys.platform == "win32" else {"start_new_session": True}


async def run_upload(platform: str, account: str, file_path: str,
                     title: str, desc: str, tags: list[str]) -> tuple[bool, str]:
    sau = resolve_sau()
    if not sau:
        return False, "social-auto-upload 未安装（pip install git+… 并安装 Google Chrome）"
    acct = safe_account(account)
    if not acct:
        return False, "账号标识非法（仅允许 a-z 0-9 _ -）"

    argv = [sau, platform, "upload-video", "--account", acct,
            "--file", file_path, "--title", sanitize_text(title)[:TITLE_MAX],
            "--desc", sanitize_text(desc)]
    clean_tags = sanitize_tags(tags)
    if clean_tags:
        argv += ["--tags", ",".join(clean_tags)]
    argv.append("--headless")

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=subprocess_env(), **_spawn_kwargs())
    except FileNotFoundError:
        return False, "social-auto-upload 未安装（找不到 sau 可执行）"

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=UPLOAD_TIMEOUT)
    except asyncio.TimeoutError:
        kill_process_tree(proc)
        return False, "上传超时"

    if proc.returncode == 0:
        return True, (out or b"").decode("utf-8", "ignore").strip()
    return False, classify_upload_error((err or b"").decode("utf-8", "ignore"))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_upload.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/publisher/sau_runner.py backend/tests/test_sau_runner_upload.py
git commit -m "feat(publish): sau_runner.run_upload（子进程发布 + 超时杀进程树）"
```

---

## Task 7: sau_runner — `check_login`

**Files:**
- Modify: `backend/app/providers/publisher/sau_runner.py`
- Test: `backend/tests/test_sau_runner_check.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_sau_runner_check.py
import pytest

from app.providers.publisher import sau_runner as r


@pytest.mark.asyncio
async def test_check_shallow_uses_cookie_file(monkeypatch, tmp_path):
    f = tmp_path / "douyin_acct1.json"
    monkeypatch.setattr(r, "cookie_path", lambda p, a: f)
    assert await r.check_login("douyin", "acct1") is False
    f.write_text("{}")
    assert await r.check_login("douyin", "acct1") is True


@pytest.mark.asyncio
async def test_check_invalid_account_false(monkeypatch):
    assert await r.check_login("douyin", "../bad") is False


@pytest.mark.asyncio
async def test_check_deep_uses_exit_code(monkeypatch):
    monkeypatch.setattr(r, "resolve_sau", lambda: "/bin/sau")

    class P:
        returncode = 0
        pid = 1

        async def communicate(self):
            return b"valid", b""

    async def fake_exec(*a, **k):
        return P()
    monkeypatch.setattr(r.asyncio, "create_subprocess_exec", fake_exec)
    assert await r.check_login("douyin", "acct1", deep=True) is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_check.py -v`
Expected: FAIL（无 `check_login`）

- [ ] **Step 3: 写实现（追加到 sau_runner.py）**

```python
async def check_login(platform: str, account: str, deep: bool = False) -> bool:
    """登录态：浅查 cookie 文件存在；deep=True 跑 `sau <p> check`（exit 0=valid）。"""
    acct = safe_account(account)
    if not acct:
        return False
    if not deep:
        return cookie_path(platform, acct).exists()
    sau = resolve_sau()
    if not sau:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            sau, platform, "check", "--account", acct,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=subprocess_env(), **_spawn_kwargs())
    except FileNotFoundError:
        return False
    try:
        await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        kill_process_tree(proc)
        return False
    return proc.returncode == 0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_check.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/publisher/sau_runner.py backend/tests/test_sau_runner_check.py
git commit -m "feat(publish): sau_runner.check_login（浅查文件 / 深查 sau check 退出码）"
```

---

## Task 8: 登录 worker 脚本

**Files:**
- Create: `backend/app/providers/publisher/sau_login_worker.py`
- Test: `backend/tests/test_sau_login_worker.py`

worker 在子进程内 import SAU；单测只覆盖「纯逻辑」（JSON 行格式化 + 平台分派选择哪个 setup），不真起浏览器。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_sau_login_worker.py
import json

from app.providers.publisher import sau_login_worker as w


def test_emit_line_is_json(capsys):
    w._emit({"qr": "data:image/png;base64,AAA"})
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == {"qr": "data:image/png;base64,AAA"}


def test_pick_setup_known_platforms():
    assert w._setup_name("douyin") == "douyin_setup"
    assert w._setup_name("kuaishou") == "ks_setup"


def test_pick_setup_unknown_raises():
    import pytest
    with pytest.raises(ValueError):
        w._setup_name("weibo")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_login_worker.py -v`
Expected: FAIL（无模块）

- [ ] **Step 3: 写实现**

```python
# backend/app/providers/publisher/sau_login_worker.py
"""登录子进程：在隔离进程内 import SAU 跑扫码登录，二维码 data URL 与结果以 JSON 行打到 stdout。

由 sau_runner.run_login 用 `python -m app.providers.publisher.sau_login_worker <platform> <account>` 启动，
PYTHONPATH 已注入 sau_conf（使 SAU 的 `import conf` 命中）。主进程不 import 本模块的 SAU 依赖。

stdout 协议（每行一个 JSON）：
  {"qr": "<data-url>"}                     # 二维码就绪/刷新
  {"result": "success|timeout|failed", "error": "<可选>"}   # 终态
"""
from __future__ import annotations

import asyncio
import json
import sys

_SETUP = {"douyin": "douyin_setup", "kuaishou": "ks_setup"}


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _setup_name(platform: str) -> str:
    if platform not in _SETUP:
        raise ValueError(f"unsupported platform: {platform}")
    return _SETUP[platform]


async def _run(platform: str, account: str) -> int:
    # 仅在子进程内 import，主进程永不触达
    if platform == "douyin":
        from uploader.douyin_uploader.main import douyin_setup as setup
    else:
        from uploader.ks_uploader.main import ks_setup as setup

    from sau_cli import resolve_account_file  # 用 SAU 自己的路径规则（受 conf.BASE_DIR 控制）
    account_file = str(resolve_account_file(platform, account))

    def on_qr(payload: dict) -> None:
        data_url = payload.get("image_data_url")
        if data_url:
            _emit({"qr": data_url})

    try:
        result = await setup(account_file, handle=True, return_detail=True,
                             qrcode_callback=on_qr, headless=True)
    except Exception as exc:  # noqa: BLE001
        _emit({"result": "failed", "error": str(exc)})
        return 1

    status = result.get("status") if isinstance(result, dict) else None
    if status == "success" or (isinstance(result, dict) and result.get("success")):
        _emit({"result": "success"})
        return 0
    if status == "timeout":
        _emit({"result": "timeout"})
        return 1
    _emit({"result": "failed", "error": (result.get("message") if isinstance(result, dict) else "登录失败")})
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 2:
        _emit({"result": "failed", "error": "usage: sau_login_worker <platform> <account>"})
        return 2
    platform, account = argv
    _setup_name(platform)  # 提前校验平台
    return asyncio.run(_run(platform, account))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_login_worker.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/publisher/sau_login_worker.py backend/tests/test_sau_login_worker.py
git commit -m "feat(publish): 登录 worker 子进程（callback 二维码 → stdout JSON 行）"
```

---

## Task 9: sau_runner — `run_login`

**Files:**
- Modify: `backend/app/providers/publisher/sau_runner.py`
- Test: `backend/tests/test_sau_runner_login.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_sau_runner_login.py
import asyncio

import pytest

from app.providers.publisher import sau_runner as r


class FakeStream:
    def __init__(self, lines: list[bytes]):
        self._lines = lines

    async def readline(self):
        return self._lines.pop(0) if self._lines else b""


class FakeProc:
    def __init__(self, lines, returncode=0):
        self.stdout = FakeStream(lines)
        self.stderr = FakeStream([])
        self.returncode = returncode
        self.pid = 99

    async def wait(self):
        return self.returncode


@pytest.mark.asyncio
async def test_run_login_emits_qr_then_success(monkeypatch):
    lines = [b'{"qr": "data:image/png;base64,AAA"}\n', b'{"result": "success"}\n', b""]

    async def fake_exec(*a, **k):
        return FakeProc(lines)
    monkeypatch.setattr(r.asyncio, "create_subprocess_exec", fake_exec)

    seen = []
    ok, status = await r.run_login("douyin", "acct1", on_qr=seen.append)
    assert seen == ["data:image/png;base64,AAA"]
    assert ok is True
    assert status == "success"


@pytest.mark.asyncio
async def test_run_login_invalid_account(monkeypatch):
    ok, status = await r.run_login("douyin", "../bad", on_qr=lambda x: None)
    assert ok is False
    assert status == "failed"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_login.py -v`
Expected: FAIL（无 `run_login`）

- [ ] **Step 3: 写实现（追加到 sau_runner.py）**

```python
import json
from typing import Callable


async def run_login(platform: str, account: str,
                    on_qr: Callable[[str], None]) -> tuple[bool, str]:
    """起登录 worker 子进程，逐行读 stdout：qr → on_qr(data_url)；result → 终态。

    返回 (ok, status)，status ∈ success|timeout|failed。超时杀进程树。
    """
    acct = safe_account(account)
    if not acct:
        return False, "failed"

    argv = [sys.executable, "-m", "app.providers.publisher.sau_login_worker", platform, acct]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=subprocess_env(), **_spawn_kwargs())
    except FileNotFoundError:
        return False, "failed"

    async def _pump() -> str:
        status = "failed"
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            try:
                msg = json.loads(raw.decode("utf-8", "ignore").strip() or "{}")
            except json.JSONDecodeError:
                continue
            if "qr" in msg:
                on_qr(msg["qr"])
            elif "result" in msg:
                status = msg["result"]
        await proc.wait()
        return status

    try:
        status = await asyncio.wait_for(_pump(), timeout=LOGIN_TIMEOUT)
    except asyncio.TimeoutError:
        kill_process_tree(proc)
        return False, "timeout"

    return status == "success", status
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_sau_runner_login.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/publisher/sau_runner.py backend/tests/test_sau_runner_login.py
git commit -m "feat(publish): sau_runner.run_login（读 worker stdout，回调二维码）"
```

---

## Task 10: 重写抖音/快手适配器

**Files:**
- Rewrite: `backend/app/providers/publisher/douyin.py`
- Rewrite: `backend/app/providers/publisher/kuaishou.py`
- Test: `backend/tests/test_publisher_douyin_kuaishou.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_publisher_douyin_kuaishou.py
import pytest

from app.providers.publisher.douyin import DouyinPublisher
from app.providers.publisher.kuaishou import KuaishouPublisher


@pytest.mark.asyncio
async def test_no_account():
    res = await DouyinPublisher(account="").publish("v.mp4", None, "t", "d", ["x"])
    assert res.status == "failed" and "未配置账号" in res.error_message


@pytest.mark.asyncio
async def test_not_logged_in(monkeypatch, tmp_path):
    from app.providers.publisher import sau_runner
    monkeypatch.setattr(sau_runner, "cookie_path", lambda p, a: tmp_path / "missing.json")
    res = await DouyinPublisher(account="acct1").publish("v.mp4", None, "t", "d", [])
    assert res.status == "failed" and "未登录" in res.error_message


@pytest.mark.asyncio
async def test_success(monkeypatch, tmp_path):
    from app.providers.publisher import sau_runner
    f = tmp_path / "douyin_acct1.json"; f.write_text("{}")
    monkeypatch.setattr(sau_runner, "cookie_path", lambda p, a: f)

    async def ok(*a, **k):
        return True, "submitted"
    monkeypatch.setattr(sau_runner, "run_upload", ok)
    res = await DouyinPublisher(account="acct1").publish("v.mp4", None, "标题", "简介", ["a"])
    assert res.status == "success"
    assert res.platform == "douyin"


@pytest.mark.asyncio
async def test_failure_propagates_message(monkeypatch, tmp_path):
    from app.providers.publisher import sau_runner
    f = tmp_path / "kuaishou_acct1.json"; f.write_text("{}")
    monkeypatch.setattr(sau_runner, "cookie_path", lambda p, a: f)

    async def fail(*a, **k):
        return False, "登录态失效，请重新扫码登录"
    monkeypatch.setattr(sau_runner, "run_upload", fail)
    res = await KuaishouPublisher(account="acct1").publish("v.mp4", None, "t", "d", [])
    assert res.status == "failed" and "登录态失效" in res.error_message
    assert res.platform == "kuaishou"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_publisher_douyin_kuaishou.py -v`
Expected: FAIL（旧 `DouyinPublisher` 签名不符 / 行为不符）

- [ ] **Step 3: 重写两个适配器**

```python
# backend/app/providers/publisher/douyin.py
from app.logging import get_logger
from app.providers import publisher as _pub  # noqa: F401  (保持包初始化)
from app.providers.base import PublisherAdapter, PublishResult
from app.providers.publisher import sau_runner

log = get_logger("publisher.douyin")


class DouyinPublisher(PublisherAdapter):
    """抖音发布：浏览器自动化（social-auto-upload，扫码登录 + Cookie）。"""

    def __init__(self, account: str = ""):
        self._account = account

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str,
                      description: str, tags: list[str], subtitle_path: str | None = None) -> PublishResult:
        if not self._account:
            return PublishResult(platform="douyin", status="failed", error_message="未配置账号")
        if not sau_runner.cookie_path("douyin", self._account).exists():
            return PublishResult(platform="douyin", status="failed",
                                 error_message="未登录：请先在发布管理页扫码登录")
        log.info("Publishing to Douyin: '%s'", title[:60])
        ok, msg = await sau_runner.run_upload("douyin", self._account, video_path, title, description, tags or [])
        return PublishResult(platform="douyin", status="success" if ok else "failed",
                             error_message=None if ok else msg)
```

```python
# backend/app/providers/publisher/kuaishou.py
from app.logging import get_logger
from app.providers.base import PublisherAdapter, PublishResult
from app.providers.publisher import sau_runner

log = get_logger("publisher.kuaishou")


class KuaishouPublisher(PublisherAdapter):
    """快手发布：浏览器自动化（social-auto-upload，扫码登录 + Cookie）。"""

    def __init__(self, account: str = ""):
        self._account = account

    async def publish(self, video_path: str, thumbnail_path: str | None, title: str,
                      description: str, tags: list[str], subtitle_path: str | None = None) -> PublishResult:
        if not self._account:
            return PublishResult(platform="kuaishou", status="failed", error_message="未配置账号")
        if not sau_runner.cookie_path("kuaishou", self._account).exists():
            return PublishResult(platform="kuaishou", status="failed",
                                 error_message="未登录：请先在发布管理页扫码登录")
        log.info("Publishing to Kuaishou: '%s'", title[:60])
        ok, msg = await sau_runner.run_upload("kuaishou", self._account, video_path, title, description, tags or [])
        return PublishResult(platform="kuaishou", status="success" if ok else "failed",
                             error_message=None if ok else msg)
```

> 注：`douyin.py` 顶部那行 `from app.providers import publisher as _pub` 仅为示意包关系，若引发循环导入请删除——只保留 `from app.providers.publisher import sau_runner` 即可（sau_runner 不依赖适配器，无循环）。

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_publisher_douyin_kuaishou.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/publisher/douyin.py backend/app/providers/publisher/kuaishou.py backend/tests/test_publisher_douyin_kuaishou.py
git commit -m "feat(publish): 重写抖音/快手适配器走 sau_runner 浏览器路线"
```

---

## Task 11: `_build_one` 注册（消除死代码）

**Files:**
- Modify: `backend/app/providers/publisher/__init__.py:24-41`（`_build_one` 函数）
- Test: `backend/tests/test_build_publishers_douyin_kuaishou.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_build_publishers_douyin_kuaishou.py
from app.providers.publisher import build_publishers
from app.providers.publisher.douyin import DouyinPublisher
from app.providers.publisher.kuaishou import KuaishouPublisher
from app.store.targets_store import TargetData


def test_build_douyin():
    t = TargetData(slug="dy", name="抖音", platform="douyin", enabled=True, config={"account": "acct1"})
    pubs = build_publishers([t])
    assert len(pubs) == 1
    _, adapter = pubs[0]
    assert isinstance(adapter, DouyinPublisher)
    assert adapter._account == "acct1"


def test_build_kuaishou():
    t = TargetData(slug="ks", name="快手", platform="kuaishou", enabled=True, config={"account": "acct2"})
    _, adapter = build_publishers([t])[0]
    assert isinstance(adapter, KuaishouPublisher)
    assert adapter._account == "acct2"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_build_publishers_douyin_kuaishou.py -v`
Expected: FAIL（`_build_one` 对 douyin/kuaishou 返回 None → `pubs == []` → IndexError/len 0）

- [ ] **Step 3: 在 `_build_one` 注册**

在 `backend/app/providers/publisher/__init__.py` 的 `_build_one` 内，`youtube` 分支之后、`return None` 之前插入：

```python
    if platform == "douyin":
        from app.providers.publisher.douyin import DouyinPublisher
        return DouyinPublisher(account=cfg.get("account", ""))
    if platform == "kuaishou":
        from app.providers.publisher.kuaishou import KuaishouPublisher
        return KuaishouPublisher(account=cfg.get("account", ""))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_build_publishers_douyin_kuaishou.py tests/test_build_publishers.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add backend/app/providers/publisher/__init__.py backend/tests/test_build_publishers_douyin_kuaishou.py
git commit -m "feat(publish): _build_one 注册抖音/快手，消除死代码"
```

---

## Task 12: 登录与登录态 API

**Files:**
- Modify: `backend/app/api/publishers.py`（顶部 import + 3 个新路由）
- Test: `backend/tests/test_api_publishers_login.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_api_publishers_login.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, config
from app.api.dependencies import get_db
from app.auth import create_token, hash_password
from app.main import create_app
from app.models import Base
from app.models.user import User


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.yaml")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config.get_settings().infra, "data_dir", str(tmp_path / "data"))
    auth._secret.cache_clear()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sf = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    app = create_app()

    def override():
        s = sf()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    s = sf(); s.add(User(username="admin", password_hash=hash_password("admin"))); s.commit(); s.close()
    return TestClient(app), create_token("admin")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_login_start_rejects_bad_platform(client):
    c, tok = client
    r = c.post("/api/publishers/login/start", json={"platform": "weibo", "account": "a"}, headers=_h(tok))
    assert r.status_code == 422


def test_login_start_rejects_bad_account(client):
    c, tok = client
    r = c.post("/api/publishers/login/start", json={"platform": "douyin", "account": "../bad"}, headers=_h(tok))
    assert r.status_code == 422


def test_login_start_creates_session_row(client, monkeypatch):
    c, tok = client
    from app.api import publishers as route

    # 屏蔽真实后台流程（避免触达真实 DB / 起子进程），只验证会话行已建、status 端点可读
    async def noop(*a, **k):
        return None
    monkeypatch.setattr(route, "_run_login_flow", noop)

    r = c.post("/api/publishers/login/start", json={"platform": "douyin", "account": "acct1"}, headers=_h(tok))
    assert r.status_code == 200
    sid = r.json()["sid"]

    st = c.get(f"/api/publishers/login/status?sid={sid}", headers=_h(tok))
    assert st.status_code == 200
    # 行已在 start 时提交，状态为初始 starting（后台被屏蔽）
    assert st.json()["status"] == "starting"


def test_login_status_unknown_sid(client):
    c, tok = client
    r = c.get("/api/publishers/login/status?sid=nope", headers=_h(tok))
    assert r.json()["status"] == "error"


def test_login_status_for_target(client, monkeypatch):
    c, tok = client
    # 建一个抖音账号
    c.post("/api/publishers/", json={"name": "抖音", "platform": "douyin",
           "config_json": '{"account": "acct1"}'}, headers=_h(tok))
    from app.api import publishers as route

    async def fake_check(platform, account, deep=False):
        return True
    monkeypatch.setattr(route.sau_runner, "check_login", fake_check)
    # slug 由 name slugify 得空→fallback platform=douyin
    r = c.get("/api/publishers/douyin/login-status", headers=_h(tok))
    assert r.status_code == 200
    assert r.json()["logged_in"] is True


def test_login_status_wrong_platform(client):
    c, tok = client
    c.post("/api/publishers/", json={"name": "b", "platform": "bilibili",
           "config_json": '{"sessdata": "s"}'}, headers=_h(tok))
    r = c.get("/api/publishers/b/login-status", headers=_h(tok))
    assert r.status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n env_news_videos_wf pytest tests/test_api_publishers_login.py -v`
Expected: FAIL（404，路由不存在）

- [ ] **Step 3: 实现路由**

在 `backend/app/api/publishers.py` 顶部 import 区补：

```python
import asyncio
import secrets

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_session_factory
from app.models.browser_login_session import BrowserLoginSession  # noqa: F401  注册建表
from app.providers.publisher import sau_runner

_LOGIN_PLATFORMS = {"douyin", "kuaishou"}
_LOGIN_TASKS: set = set()  # 持有后台任务引用，防被 GC


class LoginStartBody(BaseModel):
    platform: str
    account: str
```

后台登录流程——**用独立 session**（请求级 `db` 在响应返回后即关闭，不能在后台任务里复用）：

```python
async def _run_login_flow(sid: str, platform: str, account: str) -> None:
    """后台跑扫码登录：自开 DB session，二维码就绪/终态都回写 BrowserLoginSession。"""
    factory = get_session_factory()

    def on_qr(data_url: str) -> None:
        s = factory()
        try:
            row = s.query(BrowserLoginSession).filter_by(sid=sid).first()
            if row:
                row.qr_base64 = data_url
                row.status = "qr_ready"
                s.commit()
        finally:
            s.close()

    try:
        _ok, status = await sau_runner.run_login(platform, account, on_qr)
    except Exception:  # noqa: BLE001
        log.exception("login worker crashed")
        status = "failed"

    s = factory()
    try:
        row = s.query(BrowserLoginSession).filter_by(sid=sid).first()
        if row:
            row.status = status if status in ("success", "timeout", "failed") else "failed"
            s.commit()
    finally:
        s.close()
```

在文件末尾追加路由：

```python
@router.post("/login/start")
def login_start(body: LoginStartBody, db: Session = Depends(get_db)):
    if body.platform not in _LOGIN_PLATFORMS:
        raise HTTPException(status_code=422, detail="仅支持抖音/快手扫码登录")
    account = sau_runner.safe_account(body.account)
    if not account:
        raise HTTPException(status_code=422, detail="账号标识非法（仅 a-z 0-9 _ -）")

    # 清理本账号旧的非进行中会话（并发判据：仍 starting/qr_ready 的不动）
    db.query(BrowserLoginSession).filter_by(platform=body.platform, account=account)\
        .filter(BrowserLoginSession.status.notin_(["starting", "qr_ready"])).delete(synchronize_session=False)
    sid = secrets.token_urlsafe(24)
    db.add(BrowserLoginSession(sid=sid, platform=body.platform, account=account, status="starting"))
    db.commit()

    task = asyncio.create_task(_run_login_flow(sid, body.platform, account))
    _LOGIN_TASKS.add(task)
    task.add_done_callback(_LOGIN_TASKS.discard)
    return {"sid": sid}


@router.get("/login/status")
def login_status(sid: str, db: Session = Depends(get_db)):
    s = db.query(BrowserLoginSession).filter_by(sid=sid).first()
    if s is None:
        return {"status": "error", "error": "会话不存在"}
    return {"status": s.status, "qr_base64": s.qr_base64, "error": s.error}


@router.get("/{slug}/login-status")
async def target_login_status(slug: str, deep: bool = False):
    t = targets_store.get_target(slug)
    if t is None:
        raise HTTPException(status_code=404, detail="Target not found")
    if t.platform not in _LOGIN_PLATFORMS:
        raise HTTPException(status_code=422, detail="该平台不支持扫码登录态查询")
    account = sau_runner.safe_account((t.config or {}).get("account", ""))
    if not account:
        return {"logged_in": False}
    logged_in = await sau_runner.check_login(t.platform, account, deep=deep)
    return {"logged_in": logged_in}
```

> 路由匹配：`/login/status`（段 `[login, status]`）与 `/{slug}/login-status`（段 `[*, login-status]`）第二段不同，不冲突；`/login/start` 是 POST、与既有 `POST /` 路径不同。现有 `PATCH/DELETE /{slug}` 只匹配单段且方法不同，互不影响。按本任务把三个新路由追加到文件末尾即可，无顺序陷阱。

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n env_news_videos_wf pytest tests/test_api_publishers_login.py tests/test_api_publishers.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/publishers.py backend/tests/test_api_publishers_login.py
git commit -m "feat(publish): 抖音/快手扫码登录 + 登录态查询 API（DB 状态机）"
```

---

## Task 13: 前端字段收敛（抖音/快手 → account）

**Files:**
- Modify: `frontend/src/types/index.ts:130-141`（`PLATFORM_FIELDS` 的 douyin/kuaishou）
- Test: `pnpm lint` + `pnpm build`（类型检查）

- [ ] **Step 1: 改字段定义**

把 `frontend/src/types/index.ts` 中 douyin/kuaishou 两段替换为：

```typescript
  douyin: [
    { key: "account", label: "账号标识", required: true, placeholder: "仅小写字母/数字/_/-，如 my_acct（扫码登录后用）" },
  ],
  kuaishou: [
    { key: "account", label: "账号标识", required: true, placeholder: "仅小写字母/数字/_/-，如 my_acct（扫码登录后用）" },
  ],
```

- [ ] **Step 2: 类型检查与构建**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: 无类型错误（PLATFORM_FIELDS 结构不变，仅内容变更）

- [ ] **Step 3: 提交**

```bash
git add frontend/src/types/index.ts
git commit -m "feat(publish): 前端抖音/快手字段收敛为 account（去路线 A 字段）"
```

---

## Task 14: 前端扫码登录 UI + 登录态徽标

**Files:**
- Modify: `frontend/src/pages/Publishers.tsx`
- Test: `pnpm lint` + `pnpm build` + 手动验证

本任务在账号卡片（`PLATFORM_CHIP` 渲染附近，约 `Publishers.tsx:163-195`）为 `douyin`/`kuaishou` 账号增加「扫码登录」按钮与登录态徽标。下面是要新增的最小 React 逻辑，插入到列表项渲染中。

- [ ] **Step 1: 新增登录弹窗组件（同文件内）**

在 `Publishers.tsx` 顶部 import 之后、`PublishersPage` 组件之前，加入：

```tsx
function ScanLoginButton({ platform, account }: { platform: string; account: string }) {
  const [open, setOpen] = useState(false);
  const [qr, setQr] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");

  async function start() {
    setOpen(true); setQr(null); setStatus("starting");
    const res = await fetch("/api/publishers/login/start", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeader() },
      body: JSON.stringify({ platform, account }),
    });
    if (!res.ok) { setStatus("failed"); return; }
    const { sid } = await res.json();
    const timer = setInterval(async () => {
      const s = await fetch(`/api/publishers/login/status?sid=${sid}`, { headers: authHeader() });
      const b = await s.json();
      setStatus(b.status);
      if (b.qr_base64) setQr(b.qr_base64);
      if (["success", "failed", "timeout", "error"].includes(b.status)) clearInterval(timer);
    }, 1500);
  }

  return (
    <>
      <button className="text-xs underline text-cyan-300" onClick={start} disabled={!account}>扫码登录</button>
      {open && (
        <div className={dialogOverlayCls} onClick={() => setOpen(false)}>
          <div className={dialogPanelCls} onClick={(e) => e.stopPropagation()}>
            <p className="mb-3 text-sm">扫码登录 {platform} · {account}</p>
            {qr ? <img src={qr} alt="登录二维码" className="mx-auto w-48 h-48" /> : <p className="text-white/60">二维码生成中…（{status}）</p>}
            {status === "success" && <p className="mt-3 text-green-400">登录成功</p>}
            {(status === "failed" || status === "timeout") && <p className="mt-3 text-red-400">登录失败（{status}），请重试</p>}
          </div>
        </div>
      )}
    </>
  );
}
```

> `authHeader()`：复用本项目已有的鉴权头工具。若 `Publishers.tsx` 现有 fetch 是通过统一的 `api` 封装发起的，请改用该封装（查看文件内现有请求写法，保持一致，不要新造 `authHeader`）。本步以裸 fetch 示意；执行时**以文件内既有请求方式为准**。

- [ ] **Step 2: 在账号卡片渲染处挂上按钮 + 徽标**

在列表项（`PLATFORM_LABELS[t.platform]` 徽标附近）为抖音/快手追加：

```tsx
{(t.platform === "douyin" || t.platform === "kuaishou") && (
  <ScanLoginButton platform={t.platform} account={(() => {
    try { return JSON.parse(t.config_json || "{}").account || ""; } catch { return ""; }
  })()} />
)}
```

- [ ] **Step 3: 类型检查与构建**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: 无类型错误

- [ ] **Step 4: 手动验证（需本机 SAU + Chrome）**

Run: 启动前端 `pnpm dev`，进「发布管理」，新建抖音账号填 `account`，点「扫码登录」，确认弹窗出现二维码图片。
Expected: 弹窗显示二维码（来自后端 `login/status` 的 `qr_base64`）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/Publishers.tsx
git commit -m "feat(publish): 发布管理页抖音/快手扫码登录 UI"
```

---

## Task 15: 依赖忽略 + 文档

**Files:**
- Modify: `.gitignore`
- Modify: `docs/video-publish-guide.md`（第 4/5 节 抖音/快手）
- Test: 人工核对

- [ ] **Step 1: 忽略 cookie 目录**

在 `.gitignore` 追加：

```
# 抖音/快手扫码登录 cookie 与临时二维码（social-auto-upload）
publish_cookies/
```

- [ ] **Step 2: 改写发布指南抖音/快手两节**

把 `docs/video-publish-guide.md` 的「## 4. 抖音」「## 5. 快手」两节正文替换为浏览器自动化路线：

```markdown
## 4. 抖音 / 5. 快手（浏览器自动化扫码登录）

### 前置（一次性，本机）
1. 在后端 conda 环境装：`pip install "git+https://github.com/dreammis/social-auto-upload@<锁定commit>"`
2. **安装 Google Chrome**（uploader 用 `channel="chrome"`；或在 `backend/app/providers/publisher/sau_conf/conf.py` 填 `LOCAL_CHROME_PATH`）。
3. 后端机器需能起浏览器（headless 即可）。

### 使用
1. 「发布管理」→「+ 添加平台」选 抖音/快手，填 **账号标识**（仅 a-z 0-9 _ -，如 `my_acct`）。
2. 点账号卡片「扫码登录」，用抖音/快手 App 扫弹出的二维码。
3. 卡片显示「已登录」后即可在任务里选该账号发布。Cookie 存仓库根 `publish_cookies/`，失效后重新扫码即可。

> 无需企业资质；与 B 站逆向 Cookie 路线同类，存在平台改版导致失效的风险，失效时重新扫码。
```

- [ ] **Step 3: 全量回归测试**

Run: `cd backend && conda run -n env_news_videos_wf pytest -q`
Expected: 全绿（含新增与既有用例）

- [ ] **Step 4: 提交**

```bash
git add .gitignore docs/video-publish-guide.md
git commit -m "docs(publish): 抖音/快手改写为扫码登录路线 + 忽略 publish_cookies"
```

---

## 完成标准

- [ ] `conda run -n env_news_videos_wf pytest -q`（backend）全绿。
- [ ] `pnpm lint && pnpm build`（frontend）无错。
- [ ] 「发布管理」可新建抖音/快手账号、扫码登录出二维码、登录态徽标正确。
- [ ] 一条 pipeline 跑到 publish 阶段，选中已登录的抖音/快手账号可成功发布（人工端到端）。
