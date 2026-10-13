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


def test_save_in_place_preserves_inode(tmp_path: Path):
    """原地写：覆盖已存在文件应保留原 inode（无 os.replace 重命名）。

    这是 EBUSY 修复的回归依据——单文件 bind mount 上 os.replace 到挂载点会 EBUSY，
    原地截断写则保留 inode、安全。断言两次保存 inode 不变，证明没有 rename。
    """
    p = tmp_path / "y.yaml"
    _io.save_yaml(p, {"k": "v"})
    first_inode = p.stat().st_ino
    _io.save_yaml(p, {"k": "v2"})
    assert p.stat().st_ino == first_inode, "原地写应保留 inode（无 os.replace 重命名）"
    assert _io.load_yaml(p) == {"k": "v2"}
    # 无临时文件残留
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
