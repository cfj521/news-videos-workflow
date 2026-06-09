import pytest
from app.providers.composer.comfyui_composer import ComfyUIVideoComposer


@pytest.mark.asyncio
async def test_compose_calls_provider_per_scene_and_concats(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    timeline = {"total_duration_ms": 4000, "entries": [
        {"scene_id": 1, "image_path": str(tmp_path / "a.png"), "audio_path": "", "start_ms": 0, "end_ms": 2000, "subtitle_text": "一"},
        {"scene_id": 2, "image_path": str(tmp_path / "b.png"), "audio_path": "", "start_ms": 2000, "end_ms": 4000, "subtitle_text": "二"},
    ]}
    calls = []

    class VP:
        async def generate(self, image_path, prompt, duration, resolution="704x480", output_path=""):
            calls.append((prompt, duration)); open(output_path, "wb").write(b"MP4")
            from app.providers.base import AssetResult
            return AssetResult(file_path=output_path)

    def fake_run(cmd, **kw):
        open(cmd[-1], "wb").write(b"OUT")
        class R: returncode = 0; stderr = b""
        return R()
    monkeypatch.setattr("app.providers.composer.comfyui_composer.subprocess.run", fake_run)

    comp = ComfyUIVideoComposer(VP(), fps=24)
    res = await comp.compose(timeline, str(tmp_path / "assets"), str(tmp_path / "out.mp4"), "704x480")
    assert len(calls) == 2 and calls[0][1] == 2.0
    assert res.file_path == str(tmp_path / "out.mp4")


@pytest.mark.asyncio
async def test_compose_burns_title_via_drawtext(tmp_path, monkeypatch):
    from app.config import OverlayCfg
    font = tmp_path / "f.ttc"; font.write_bytes(b"F")
    (tmp_path / "assets").mkdir()
    timeline = {"total_duration_ms": 2000, "entries": [
        {"scene_id": 1, "image_path": str(tmp_path / "a.png"), "audio_path": "",
         "start_ms": 0, "end_ms": 2000, "subtitle_text": "x", "title": "新闻标题甲"},
    ]}
    open(tmp_path / "a.png", "wb").write(b"P")
    cmds = []

    class VP:
        async def generate(self, image_path, prompt, duration, resolution="704x480", output_path=""):
            open(output_path, "wb").write(b"MP4")
            from app.providers.base import AssetResult
            return AssetResult(file_path=output_path)

    def fake_run(cmd, **kw):
        cmds.append(cmd); open(cmd[-1], "wb").write(b"OUT")
        class R: returncode = 0; stderr = b""
        return R()
    monkeypatch.setattr("app.providers.composer.comfyui_composer.subprocess.run", fake_run)

    comp = ComfyUIVideoComposer(VP(), fps=24, overlay=OverlayCfg(font_file=str(font)))
    await comp.compose(timeline, str(tmp_path / "assets"), str(tmp_path / "out.mp4"), "704x480")
    assert any("drawtext=" in part for cmd in cmds for part in cmd)
