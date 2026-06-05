"""流水线进程内事件总线（用于 SSE 实时推送）。

主流水线(execute_pipeline)跑在主事件循环；手动重发布(_publish_bg)用 asyncio.run 起的是
另一个循环/线程。故 publish 必须跨循环安全——记录每个订阅队列所属的事件循环，用
call_soon_threadsafe 投递。
"""
import asyncio
from collections import defaultdict

# {run_id: {queue: 该队列所属事件循环}}
_subs: dict[int, dict[asyncio.Queue, asyncio.AbstractEventLoop]] = defaultdict(dict)


def _safe_put(q: asyncio.Queue, event: dict) -> None:
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        pass


def publish(run_id: int, event: dict) -> None:
    """向该 run 的所有订阅者投递事件；可从任意线程/事件循环调用，不阻塞调用方。"""
    for q, loop in list(_subs.get(run_id, {}).items()):
        try:
            loop.call_soon_threadsafe(_safe_put, q, event)
        except RuntimeError:
            pass  # 目标循环已关闭


def subscribe(run_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subs[run_id][q] = asyncio.get_running_loop()
    return q


def unsubscribe(run_id: int, q: asyncio.Queue) -> None:
    d = _subs.get(run_id)
    if d is not None:
        d.pop(q, None)
        if not d:
            _subs.pop(run_id, None)
