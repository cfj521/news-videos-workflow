from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.tts.edge_tts_provider import EdgeTTSProvider


@pytest.mark.asyncio
async def test_edge_tts_synthesize(tmp_path):
    provider = EdgeTTSProvider()
    output_path = str(tmp_path / "test.mp3")

    with patch("app.providers.tts.edge_tts_provider.edge_tts.Communicate") as mock_comm_cls:
        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()
        mock_comm_cls.return_value = mock_comm

        result = await provider.synthesize(
            text="今天我们来看一条重磅消息",
            voice="zh-CN-XiaoxiaoNeural",
            output_path=output_path,
        )

    assert result.file_path == output_path
    mock_comm_cls.assert_called_once()


def test_default_voice():
    provider = EdgeTTSProvider()
    assert provider._default_voice == "zh-CN-XiaoxiaoNeural"

    provider_en = EdgeTTSProvider(default_voice="en-US-JennyNeural")
    assert provider_en._default_voice == "en-US-JennyNeural"


def test_duration_estimation():
    provider = EdgeTTSProvider()
    duration = provider._estimate_duration("十个字的文本哈哈哈哈", 1.0)
    assert duration > 0
    assert duration == int(10 / 4.0 * 1000)
