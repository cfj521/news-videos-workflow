from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.tts.edge_tts_provider import EdgeTTSProvider


@pytest.mark.asyncio
async def test_edge_tts_synthesize(tmp_path):
    provider = EdgeTTSProvider()
    output_path = str(tmp_path / "test.mp3")

    with patch("app.providers.tts.edge_tts_provider.edge_tts.Communicate") as mock_comm_cls, \
         patch("app.providers.tts.edge_tts_provider.measure_audio_ms", return_value=4200):
        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()
        mock_comm_cls.return_value = mock_comm

        result = await provider.synthesize(
            text="今天我们来看一条重磅消息",
            voice="zh-CN-XiaoxiaoNeural",
            output_path=output_path,
        )

    assert result.file_path == output_path
    assert result.duration_ms == 4200  # 来自测量，不再估算
    mock_comm_cls.assert_called_once()


@pytest.mark.asyncio
async def test_edge_tts_raises_when_duration_unmeasurable(tmp_path):
    # 测不到时长（无音频文件）必须报错，绝不估算
    from app.providers.base import ProviderError
    provider = EdgeTTSProvider()
    with patch("app.providers.tts.edge_tts_provider.edge_tts.Communicate") as mock_comm_cls, \
         patch("app.providers.tts.edge_tts_provider.measure_audio_ms", return_value=0):
        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()
        mock_comm_cls.return_value = mock_comm
        with pytest.raises(ProviderError):
            await provider.synthesize(text="x", output_path=str(tmp_path / "a.mp3"))


def test_default_voice():
    provider = EdgeTTSProvider()
    assert provider._default_voice == "zh-CN-XiaoxiaoNeural"

    provider_en = EdgeTTSProvider(default_voice="en-US-JennyNeural")
    assert provider_en._default_voice == "en-US-JennyNeural"


def test_measure_audio_ms_bad_path_returns_zero():
    # 文件不存在 / ffprobe 不可用时优雅回退 0，让调用方走估算
    from app.providers.tts.audio_duration import measure_audio_ms
    assert measure_audio_ms(str("no_such_dir/nope.mp3")) == 0
