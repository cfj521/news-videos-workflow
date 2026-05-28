import asyncio
from app.pipeline.stage3_assets import run_stage3


class _FakeImg:
    def __init__(self): self.calls = 0
    async def generate(self, prompt, size="1080x1920", output_path=""):
        self.calls += 1
        raise AssertionError("image generate must not be called in audio_only")


class _FakeTTS:
    def __init__(self): self.calls = 0
    async def synthesize(self, text, voice="", speed=1.0, output_path=""):
        self.calls += 1
        class R: file_path = output_path; duration_ms = 1000
        return R()


def test_audio_only_skips_image(tmp_path):
    script = {"scenes": [{"id": 1, "narration": "你好", "image_prompt": "x"},
                          {"id": 2, "narration": "世界", "image_prompt": "y"}]}
    img, tts = _FakeImg(), _FakeTTS()
    assets = asyncio.run(run_stage3(script, img, tts, str(tmp_path), audio_only=True))
    assert img.calls == 0
    assert tts.calls == 2
    assert all("image" not in a for a in assets)
    assert all(a.get("audio") for a in assets)
