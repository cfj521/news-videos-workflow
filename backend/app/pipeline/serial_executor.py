"""全局串行执行器：所有重后台作业（流水线运行 / 重出文章 / 渲染 / 发布）排进单一 FIFO
队列，由一个常驻 daemon worker 线程逐个执行——同一时刻最多一个任务在跑。

- 作业失败 / 抛异常 / 被停止都不会卡住队列：worker 捕获异常后继续下一个。
- 作业正常完成后，若队列里还有，立即开始下一个；没有就空闲等待。
- 进程重启队列丢失（与原 FastAPI BackgroundTasks 行为一致；遗留 processing 由僵尸回收兜底）。
"""
import queue
import threading
from typing import Callable

from app.logging import get_logger

log = get_logger("pipeline.serial")

_q: "queue.Queue[tuple]" = queue.Queue()
_worker_lock = threading.Lock()
_worker_started = False


def submit(fn: Callable, *args, label: str = "") -> None:
    """把一个同步后台作业排进全局串行队列（非阻塞，立即返回）。"""
    _ensure_worker()
    name = label or getattr(fn, "__name__", "job")
    _q.put((fn, args, name))
    log.info("Queued [%s] — pending in queue: %d", name, _q.qsize())


def pending_count() -> int:
    """队列中尚未开始执行的作业数（不含正在运行的那个）。"""
    return _q.qsize()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_run_loop, name="pipeline-serial-worker", daemon=True).start()
        _worker_started = True
        log.info("Serial pipeline worker started")


def _run_loop() -> None:
    while True:
        fn, args, label = _q.get()
        log.info("Running [%s]", label)
        try:
            fn(*args)
        except Exception:  # noqa: BLE001 — 单个作业失败不能拖垮 worker
            log.exception("Serial job [%s] crashed", label)
        finally:
            _q.task_done()
