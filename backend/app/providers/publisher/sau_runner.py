"""唯一接触 social-auto-upload（sau CLI / 登录 worker 子进程）的层。

主进程绝不 import SAU；所有 SAU 交互都在子进程，cookie 目录由 sau_conf.conf.BASE_DIR 控制。
"""
from __future__ import annotations

import os
import re
import shutil
import sys
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
