"""YAML 文件存储基座：原子写 + 每文件线程锁。

后端当前单进程（uvicorn + 单 worker 串行执行器 + OAuth 回调线程），用
threading.Lock 防同文件并发写交错即可，无需跨进程锁。
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

# 每个文件路径一把锁（按绝对路径字符串归一）
_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    """获取指定路径的文件锁（按绝对路径归一化）。"""
    key = str(path.resolve())
    with _locks_guard:
        return _locks[key]


@contextlib.contextmanager
def file_lock(path: Path):
    """上下文管理器：获取文件锁并在退出时释放。"""
    lock = _lock_for(path)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def load_yaml(path: Path) -> dict[str, Any]:
    """读 YAML；文件不存在返回 {}；解析失败抛带路径的错误。"""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise RuntimeError(f"YAML 解析失败：{path}：{e}") from e


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    """原子写：先写同目录临时文件再 os.replace，避免半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            with contextlib.suppress(OSError):
                os.remove(tmp)
