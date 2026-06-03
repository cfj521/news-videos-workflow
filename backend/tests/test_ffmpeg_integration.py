"""真跑 FFmpeg 的端到端组件验证（L2）。

现有 test_audio_merge / test_stage5 全程 mock 了 subprocess，从未真实产出过
mp3/mp4。本文件用 lavfi 造真实素材，真跑 _ffmpeg_merge_audio / _ffmpeg_compose，
再用 ffprobe 校验产物，验证「成片合成」这一核心能力的真实可用性。

无 ffmpeg/ffprobe 的环境（如 CI）自动跳过，不影响纯单测。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from app.pipeline.runner import _ffmpeg_compose, _ffmpeg_merge_audio, export_final

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="需要系统 PATH 中的 ffmpeg + ffprobe",
)


def _make_audio(path: Path, seconds: float, freq: int = 440) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
         "-q:a", "2", str(path)],
        capture_output=True, check=True,
    )


def _make_image(path: Path, color: str = "blue", size: str = "320x240") -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}:d=1",
         "-frames:v", "1", str(path)],
        capture_output=True, check=True,
    )


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _resolution(path: Path) -> str:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


# ─── S5-5：纯音频合并真跑 ─────────────────────────────────────

def test_merge_audio_real(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    _make_audio(assets / "scene_01_audio.mp3", 1.0)
    _make_audio(assets / "scene_02_audio.mp3", 2.0)
    _make_audio(assets / "scene_03_audio.mp3", 1.5)
    script = {"scenes": [{"id": 1}, {"id": 2}, {"id": 3}]}

    out = _ffmpeg_merge_audio(script, assets, tmp_path)

    assert Path(out).exists() and Path(out).stat().st_size > 0
    # 合并时长 ≈ 1+2+1.5 = 4.5s（mp3 帧对齐允许 ±0.5s 误差）
    assert abs(_duration(Path(out)) - 4.5) < 0.5


# ─── S5-2 / S5-4：FFmpeg 图片+音频合成真跑（Hyperframes/ComfyUI 失败时的兜底） ──

def test_ffmpeg_compose_real(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    img1, img2 = assets / "s1.png", assets / "s2.png"
    aud1, aud2 = assets / "s1.mp3", assets / "s2.mp3"
    _make_image(img1, "blue")
    _make_image(img2, "red")
    _make_audio(aud1, 1.0)
    _make_audio(aud2, 1.5)

    timeline = {
        "entries": [
            {"scene_id": 1, "start_ms": 0, "end_ms": 1000,
             "image_path": str(img1), "audio_path": str(aud1)},
            {"scene_id": 2, "start_ms": 1000, "end_ms": 2500,
             "image_path": str(img2), "audio_path": str(aud2)},
        ],
        "total_duration_ms": 2500,
    }

    out = _ffmpeg_compose(timeline, tmp_path, resolution="320x240", fps="10")

    out_p = Path(out)
    assert out_p.exists() and out_p.stat().st_size > 0
    assert _resolution(out_p) == "320x240"
    # 两段 1.0 + 1.5 = 2.5s（±0.6s）
    assert abs(_duration(out_p) - 2.5) < 0.6


def test_ffmpeg_compose_no_valid_scene_raises(tmp_path):
    # entries 缺 image/audio → 应抛错而非产出空文件
    timeline = {"entries": [{"scene_id": 1, "start_ms": 0, "end_ms": 1000}], "total_duration_ms": 1000}
    with pytest.raises(Exception):
        _ffmpeg_compose(timeline, tmp_path, resolution="320x240", fps="10")


# ─── S5-7：成品归档导出 ───────────────────────────────────────

def test_export_final_copies_to_output_dir(tmp_path, monkeypatch):
    from app import config as cfg_mod

    src = tmp_path / "output.mp3"
    src.write_bytes(b"final-bytes")
    out_dir = tmp_path / "archive"

    settings = cfg_mod.Settings()
    settings.storage.output_dir = str(out_dir)
    monkeypatch.setattr(cfg_mod, "_settings", settings)

    dest = export_final(42, str(src), title='测试/标题:非法*字符')

    assert dest is not None and Path(dest).exists()
    # 文件名做了非法字符清洗
    assert Path(dest).read_bytes() == b"final-bytes"
    assert "run_42" in Path(dest).name
