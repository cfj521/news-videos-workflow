"""唯一接触 social-auto-upload（sau CLI / 登录 worker 子进程）的层。

主进程绝不 import SAU；所有 SAU 交互都在子进程，cookie 目录由 sau_conf.conf.BASE_DIR 控制。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from app.logging import get_logger

log = get_logger("publisher.sau_runner")

# 抖音/快手 SAU 不限标题长度，仅防御性上限避免异常长标题
TITLE_MAX = 100
MAX_TAGS = 5

# sau_runner.py 位于 backend/app/providers/publisher/
_REPO_ROOT = Path(__file__).resolve().parents[4]
_COOKIES_DIR = _REPO_ROOT / "publish_cookies" / "cookies"
_SAU_CONF_DIR = Path(__file__).resolve().parent / "sau_conf"

_ACCOUNT_RE = re.compile(r"[a-z0-9_-]+")


def ensure_cookies_dir() -> None:
    """确保 cookie 目录存在（SAU 的 resolve_account_file 只做 mkdir(exist_ok=True) 无 parents，
    全新部署下祖父目录缺失会 FileNotFoundError）。"""
    _COOKIES_DIR.mkdir(parents=True, exist_ok=True)


def _sau_utils_dir() -> Path | None:
    """定位已安装 SAU 的 utils 包目录（含静态资源 stealth.min.js），不执行 SAU 代码。"""
    import importlib.util
    try:
        spec = importlib.util.find_spec("utils")
    except Exception:
        return None
    if spec is None:
        return None
    if spec.origin:
        return Path(spec.origin).parent
    if spec.submodule_search_locations:
        return Path(list(spec.submodule_search_locations)[0])
    return None


def ensure_sau_runtime() -> None:
    """准备 SAU 运行所需目录与静态资源。

    我们把 conf.BASE_DIR 指向了仓库根 publish_cookies/，但 SAU 不仅把可写状态（cookies/logs）
    按 BASE_DIR 解析，连**静态资源** stealth.min.js 也按 BASE_DIR/utils/ 解析。故需把它从已安装的
    SAU 包内复制到 publish_cookies/utils/，否则浏览器初始化即 FileNotFoundError。
    """
    ensure_cookies_dir()
    dst = _COOKIES_DIR.parent / "utils" / "stealth.min.js"  # = BASE_DIR/utils/stealth.min.js
    if dst.exists():
        return
    src_dir = _sau_utils_dir()
    if src_dir is None:
        return
    src = src_dir / "stealth.min.js"
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


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


def classify_upload_error(stderr: str) -> str:
    """把 sau 子进程 stderr 映射成可操作中文。未登录关键字来自 SAU 源码英文消息。"""
    s = (stderr or "")
    if "missing or expired" in s.lower():
        return "登录态失效，请重新扫码登录"
    tail = "\n".join(line for line in s.strip().splitlines() if line.strip())[-500:]
    return tail or "发布失败"


UPLOAD_TIMEOUT = 600  # 浏览器自动化 + 大文件，给足 10 分钟
LOGIN_TIMEOUT = 180   # 留足扫码时间


def kill_pid_tree(pid: int | None) -> None:
    """按 PID 杀进程树（SAU 下还有 patchright/Chromium）。Windows 用 taskkill /T，POSIX 用进程组。"""
    if not pid:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, check=False)
        else:
            os.killpg(os.getpgid(pid), 9)
    except Exception:
        pass


def kill_process_tree(proc) -> None:
    """杀子进程及其后代。"""
    pid = getattr(proc, "pid", None)
    if pid:
        kill_pid_tree(pid)
    else:
        try:
            proc.kill()
        except Exception:
            pass


# 进程内登录 worker 注册表：key=f"{platform}:{account}" -> worker pid。
# 用户点「重新生成二维码」时，用它杀掉同账号上一个仍在跑的 worker（含其 Chrome），避免堆积/二维码混淆。
_WORKER_PIDS: dict[str, int] = {}


def kill_login_worker(platform: str, account: str) -> None:
    """杀掉同账号上一个仍在跑的登录 worker（best-effort，仅当前进程内可达）。"""
    pid = _WORKER_PIDS.pop(f"{platform}:{safe_account(account)}", None)
    if pid:
        kill_pid_tree(pid)


def _spawn_kwargs() -> dict:
    """阻塞子进程的平台参数：Windows 不弹控制台黑窗；POSIX 自成进程组，便于整组 kill。"""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def _spawn(argv: list[str], merge_stderr: bool = False) -> subprocess.Popen:
    """启动阻塞子进程（配合 asyncio.to_thread 调用）。

    用阻塞 subprocess 而非 asyncio.create_subprocess_exec —— Windows 的 SelectorEventLoop
    不支持 asyncio 子进程（抛 NotImplementedError），to_thread + 阻塞 subprocess 方案与事件
    循环类型无关，跨平台可靠（本仓库 bilibili 适配器对 biliup 也是 asyncio.to_thread 同理）。
    """
    return subprocess.Popen(
        argv, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
        env=subprocess_env(), **_spawn_kwargs())


def _upload_blocking(argv: list[str]) -> tuple[bool, str]:
    try:
        proc = _spawn(argv)
    except FileNotFoundError:
        return False, "social-auto-upload 未安装（找不到 sau 可执行）"
    try:
        out, err = proc.communicate(timeout=UPLOAD_TIMEOUT)
    except subprocess.TimeoutExpired:
        kill_process_tree(proc)
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        return False, "上传超时"
    if proc.returncode == 0:
        return True, (out or b"").decode("utf-8", "ignore").strip()
    return False, classify_upload_error((err or b"").decode("utf-8", "ignore"))


async def run_upload(platform: str, account: str, file_path: str,
                     title: str, desc: str, tags: list[str]) -> tuple[bool, str]:
    sau = resolve_sau()
    if not sau:
        return False, "social-auto-upload 未安装（pip install git+… 并安装 Google Chrome）"
    acct = safe_account(account)
    if not acct:
        return False, "账号标识非法（仅允许 a-z 0-9 _ -）"
    ensure_sau_runtime()

    argv = [sau, platform, "upload-video", "--account", acct,
            "--file", file_path, "--title", sanitize_text(title)[:TITLE_MAX],
            "--desc", sanitize_text(desc)]
    clean_tags = sanitize_tags(tags)
    if clean_tags:
        argv += ["--tags", ",".join(clean_tags)]
    argv.append("--headless")

    return await asyncio.to_thread(_upload_blocking, argv)


def _check_blocking(argv: list[str]) -> bool:
    try:
        proc = _spawn(argv)
    except FileNotFoundError:
        return False
    try:
        proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        kill_process_tree(proc)
        return False
    return proc.returncode == 0


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
    argv = [sau, platform, "check", "--account", acct]
    return await asyncio.to_thread(_check_blocking, argv)


def _login_blocking(argv: list[str], on_qr: Callable[[str], None], key: str) -> str:
    """阻塞跑登录 worker：逐行读其 stdout（已并入 stderr），qr → on_qr，result → 终态。

    返回 status ∈ success|timeout|failed。worker 崩溃（无 result 行）时把非 JSON 输出写日志便于排查。
    key 用于把 worker pid 登记进 _WORKER_PIDS，供「重新生成」时杀旧 worker。
    """
    try:
        proc = _spawn(argv, merge_stderr=True)
    except FileNotFoundError:
        return "failed"
    _WORKER_PIDS[key] = proc.pid

    timed_out = {"v": False}

    def _on_timeout():
        timed_out["v"] = True
        kill_process_tree(proc)

    timer = threading.Timer(LOGIN_TIMEOUT, _on_timeout)
    timer.start()
    status = "failed"
    noise: list[str] = []
    try:
        # readline（而非 for-in，避免读前瞻缓冲拖慢二维码送达）
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "ignore").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                noise.append(line)  # worker 的 traceback / loguru 输出
                continue
            if "qr" in msg:
                on_qr(msg["qr"])
            elif "result" in msg:
                status = msg.get("result", "failed")
        proc.wait()
    finally:
        timer.cancel()
        if _WORKER_PIDS.get(key) == proc.pid:
            _WORKER_PIDS.pop(key, None)

    if timed_out["v"]:
        return "timeout"
    if status == "failed" and noise:
        log.error("登录 worker 失败，输出末尾: %s", " | ".join(noise[-15:]))
    return status


async def run_login(platform: str, account: str,
                    on_qr: Callable[[str], None]) -> tuple[bool, str]:
    """起登录 worker 子进程，流式读其 stdout：qr → on_qr(data_url)；result → 终态。

    返回 (ok, status)，status ∈ success|timeout|failed。超时杀进程树。
    """
    acct = safe_account(account)
    if not acct:
        return False, "failed"
    ensure_sau_runtime()

    argv = [sys.executable, "-m", "app.providers.publisher.sau_login_worker", platform, acct]
    status = await asyncio.to_thread(_login_blocking, argv, on_qr, f"{platform}:{acct}")
    return status == "success", status
