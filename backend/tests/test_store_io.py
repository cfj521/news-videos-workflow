import threading
from pathlib import Path

from app.store import _io


def test_save_then_load_roundtrip(tmp_path: Path):
    p = tmp_path / "x.yaml"
    _io.save_yaml(p, {"a": 1, "b": ["x", "y"]})
    assert _io.load_yaml(p) == {"a": 1, "b": ["x", "y"]}


def test_load_missing_returns_empty(tmp_path: Path):
    assert _io.load_yaml(tmp_path / "nope.yaml") == {}


def test_load_corrupt_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("a: [unclosed\n", encoding="utf-8")
    try:
        _io.load_yaml(p)
        raise AssertionError("应抛出错误")
    except Exception as e:  # noqa: BLE001
        assert str(p) in str(e)


def test_save_is_atomic_no_partial_temp_left(tmp_path: Path):
    p = tmp_path / "y.yaml"
    _io.save_yaml(p, {"k": "v"})
    leftovers = [f.name for f in tmp_path.iterdir() if f.name != "y.yaml"]
    assert leftovers == []


def test_file_lock_serializes_writers(tmp_path: Path):
    import time
    p = tmp_path / "z.yaml"
    order: list[str] = []

    def worker(tag: str):
        with _io.file_lock(p):
            order.append(f"{tag}-start")
            time.sleep(0.05)
            order.append(f"{tag}-end")

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    # 持锁串行：每个 start 紧跟自己的 end，不交错
    assert order in (
        ["a-start", "a-end", "b-start", "b-end"],
        ["b-start", "b-end", "a-start", "a-end"],
    )
