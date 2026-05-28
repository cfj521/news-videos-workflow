import subprocess
from pathlib import Path
import pytest
from app.pipeline.runner import _ffmpeg_merge_audio


def _make_assets(assets_dir: Path, ids):
    assets_dir.mkdir(parents=True, exist_ok=True)
    for i in ids:
        (assets_dir / f"scene_{i:02d}_audio.mp3").write_bytes(b"x")


def test_merge_orders_by_scene_and_calls_ffmpeg(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    _make_assets(assets, [1, 2, 3])
    script = {"scenes": [{"id": 2}, {"id": 1}, {"id": 3}]}  # 顺序按 script

    def fake_run(args, **kw):
        (tmp_path / "output.mp3").write_bytes(b"merged")
        class R: returncode = 0
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)

    out = _ffmpeg_merge_audio(script, assets, tmp_path)
    assert out.endswith("output.mp3")
    list_txt = (tmp_path / "audio_concat.txt").read_text(encoding="utf-8")
    assert list_txt.index("scene_02") < list_txt.index("scene_01") < list_txt.index("scene_03")


def test_merge_no_audio_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        _ffmpeg_merge_audio({"scenes": [{"id": 1}]}, tmp_path / "assets", tmp_path)
