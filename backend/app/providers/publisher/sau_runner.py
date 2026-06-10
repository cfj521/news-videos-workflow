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
from pathlib import Path
from typing import Callable

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
