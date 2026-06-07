import threading
import time

from app.pipeline import serial_executor as se


def test_jobs_run_serially_in_order():
    order: list[int] = []
    running: list[int] = []
    max_concurrent = [0]
    lock = threading.Lock()

    def job(n: int, dur: float):
        with lock:
            running.append(n)
            max_concurrent[0] = max(max_concurrent[0], len(running))
        time.sleep(dur)
        with lock:
            running.remove(n)
            order.append(n)

    se.submit(job, 1, 0.10, label="j1")
    se.submit(job, 2, 0.02, label="j2")
    se.submit(job, 3, 0.02, label="j3")
    se._q.join()

    assert order == [1, 2, 3]      # FIFO 顺序
    assert max_concurrent[0] == 1  # 任何时刻只有一个在跑（串行）


def test_worker_continues_after_job_error():
    done: list[bool] = []

    def boom():
        raise RuntimeError("intentional")

    def ok():
        done.append(True)

    se.submit(boom, label="boom")
    se.submit(ok, label="ok")
    se._q.join()

    assert done == [True]  # 前一个作业抛错后，下一个仍照常执行
