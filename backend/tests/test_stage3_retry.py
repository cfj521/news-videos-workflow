"""S3 素材生成失败重试（针对限流/超时/5xx 等瞬时错误）回归测试。"""

import pytest

from app.pipeline import stage3_assets
from app.pipeline.stage3_assets import run_stage3
from app.providers.base import AssetResult


class _FlakyImage:
    def __init__(self, fail_times: int):
        self.calls = 0
        self.fail_times = fail_times

    async def generate(self, prompt, size="1080x1920", output_path=""):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("rate limit exceeded (429)")
        return AssetResult(file_path=output_path)


class _OkTTS:
    async def synthesize(self, text, voice="", speed=1.0, output_path=""):
        return AssetResult(file_path=output_path)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _fast(*a, **k):
        return None
    monkeypatch.setattr(stage3_assets.asyncio, "sleep", _fast)


@pytest.mark.asyncio
async def test_image_retry_recovers(tmp_path):
    img = _FlakyImage(fail_times=2)  # 前两次失败，第三次成功
    script = {"scenes": [{"id": 1, "image_prompt": "x", "narration": "y"}]}
    out = await run_stage3(script, img, _OkTTS(), str(tmp_path), max_retries=3, retry_base_delay=0.01)
    assert img.calls == 3
    assert "error" not in out[0]
    assert out[0]["image"]["file_path"].endswith("scene_01_image.png")


@pytest.mark.asyncio
async def test_image_retry_exhausted_records_error(tmp_path):
    img = _FlakyImage(fail_times=99)  # 一直失败
    script = {"scenes": [{"id": 1, "image_prompt": "x", "narration": "y"}]}
    out = await run_stage3(script, img, _OkTTS(), str(tmp_path), max_retries=3, retry_base_delay=0.01)
    assert img.calls == 3  # 重试 3 次后放弃
    assert "error" in out[0]
    assert "429" in out[0]["error"]  # 真实异常文本进入 error 便于排查
