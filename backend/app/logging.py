from __future__ import annotations

import contextvars
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "logs"
GLOBAL_LOG = LOG_DIR / "app.log"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5
# 每行带 [run=N] 标记：所有日志统一汇入 app.log，靠该标记区分属于哪个 run（无 run 时为 -）。
FMT = "%(asctime)s [%(levelname)s] [run=%(run_id)s] %(name)s: %(message)s"
FMT_FILE = FMT
DATEFMT = "%Y-%m-%d %H:%M:%S"

# 当前 pipeline run 的 id（execute_pipeline 设置）。asyncio 中每个 task 独立拷贝，
# 同一 run 的 stage/provider 日志（不同 logger）都能在 handler filter 里读到它。
_current_run_id: contextvars.ContextVar[int | None] = contextvars.ContextVar("nv_run_id", default=None)


def set_run_context(run_id: int | None):
    """进入某个 run 的执行上下文，返回 token 供 reset。"""
    return _current_run_id.set(run_id)


def reset_run_context(token) -> None:
    try:
        _current_run_id.reset(token)
    except Exception:
        pass


async def bind_run_log(run_id: int):
    """FastAPI 依赖：把当前请求绑定到某个 run 的日志上下文，请求结束自动复位。

    挂到带 path 参数 run_id 的路由上，请求内（含各 provider）日志统一带 [run=N]，
    修复 regen/scene 等接口日志打成 [run=-] 的问题。必须是 async（async 依赖与
    async 路由在同一 task 上下文执行，contextvar 才能传到路由；sync 依赖跑在线程池、传不过去）。
    """
    token = set_run_context(run_id)
    try:
        yield
    finally:
        reset_run_context(token)


class _RunIdFilter(logging.Filter):
    """把当前 run_id 注入每条 LogRecord，供 format 的 %(run_id)s 使用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = _current_run_id.get()
        record.run_id = rid if rid is not None else "-"
        return True


def setup_global_logger(level: str = "INFO") -> logging.Logger:
    root = logging.getLogger("nv")
    if root.handlers:
        return root
    root.setLevel(logging.DEBUG)

    run_filter = _RunIdFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter(FMT, datefmt=DATEFMT))
    console.addFilter(run_filter)
    root.addHandler(console)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(str(GLOBAL_LOG), maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(FMT_FILE, datefmt=DATEFMT))
    fh.addFilter(run_filter)
    root.addHandler(fh)

    return root


def get_run_logger(run_id: int, run_dir: str | Path | None = None) -> logging.Logger:
    """返回该 run 的 logger。日志不再单独写 per-run pipeline.log，而是经 run 上下文
    打上 [run=N] 标记后统一汇入 app.log（run_dir 参数保留兼容，已不使用）。"""
    return logging.getLogger(f"nv.run.{run_id}")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"nv.{name}")
