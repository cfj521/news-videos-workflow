"""回归测试：FFmpeg 合成不得用 shell=True + 列表参数。

POSIX（Docker/WSL）下 subprocess.run(列表, shell=True) 只把列表第一项当命令、其余
当 /bin/sh 自身的参数，ffmpeg 实际收到零参数而打印用法退出。这里断言合成调用以
列表形式传参且不开启 shell，锁定该修复。
"""

from pathlib import Path

import app.pipeline.runner as runner


def _make_timeline(tmp_path: Path) -> dict:
    assets = tmp_path / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    img = assets / "scene_01_image.png"
    aud = assets / "scene_01_audio.mp3"
    img.write_bytes(b"x")
    aud.write_bytes(b"x")
    return {
        "entries": [
            {"start_ms": 0, "end_ms": 2000, "image_path": str(img), "audio_path": str(aud)},
        ],
        "total_duration_ms": 2000,
    }


def test_ffmpeg_compose_does_not_use_shell(tmp_path, monkeypatch):
    captured = {}

    def fake_run(args, **kw):
        captured["args"] = args
        captured["shell"] = kw.get("shell", False)
        (tmp_path / "output.mp4").write_bytes(b"video")

        class R:
            returncode = 0
            stderr = b""

        return R()

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)

    out = runner._ffmpeg_compose(_make_timeline(tmp_path), tmp_path, "1080x1920", "30")

    assert out.endswith("output.mp4")
    # 参数必须以列表传入，且 shell 必须为 falsy —— 否则 POSIX 下参数会被丢弃
    assert isinstance(captured["args"], list)
    assert captured["args"][0] == "ffmpeg"
    assert not captured["shell"]


def test_ffmpeg_compose_inserts_per_scene_drawtext(tmp_path, monkeypatch):
    from app.config import OverlayCfg
    from app.pipeline import runner
    font = tmp_path / "f.ttc"; font.write_bytes(b"F")
    captured = {}

    def fake_run_ffmpeg(cmd, service=""):
        captured["fc"] = cmd[cmd.index("-filter_complex") + 1]
        open(cmd[-1], "wb").write(b"OUT")
    monkeypatch.setattr(runner, "_run_ffmpeg", fake_run_ffmpeg)

    timeline = {"entries": [
        {"scene_id": 1, "image_path": "a.png", "audio_path": "x.mp3", "start_ms": 0, "end_ms": 2000, "title": "甲"},
        {"scene_id": 2, "image_path": "b.png", "audio_path": "y.mp3", "start_ms": 2000, "end_ms": 4000, "title": "乙"},
    ]}
    runner._ffmpeg_compose(timeline, tmp_path, "1080x1920", "30", overlay=OverlayCfg(font_file=str(font)))
    assert captured["fc"].count("drawtext=") == 2  # 每镜一个，文本各异
