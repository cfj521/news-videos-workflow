"""YAML 文件存储基座：原子写 + 每文件线程锁。

后端当前单进程（uvicorn + 单 worker 串行执行器 + OAuth 回调线程），用
threading.Lock 防同文件并发写交错即可，无需跨进程锁。
"""
from __future__ import annotations

import contextlib
import threading
from collections import defaultdict
from collections.abc import Iterator
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
def file_lock(path: Path) -> Iterator[None]:
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
    """原地写：直接 open(path, "w") 截断写，保留原文件 inode。

    注意：本函数自身不持 file_lock；需要读改写一致性的调用方应用 file_lock 包住读+写。

    为何不用「同目录临时文件 + os.replace」原子写：在单文件 bind mount（如 Docker
    挂载）上，os.replace 到挂载点（目标路径）会返回 EBUSY（OSError 16），导致任何
    一次设置保存都崩溃。本后端是单进程单写者（无跨进程并发写），原地截断写的原子性
    损失可接受（与 config._save_yaml 对齐）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
