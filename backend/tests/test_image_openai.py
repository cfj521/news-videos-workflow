import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.image.openai_image import OpenAIImageProvider


@pytest.mark.asyncio
async def test_openai_image_generate(tmp_path):
    provider = OpenAIImageProvider(api_key="test-key")
    output_path = str(tmp_path / "test.png")

    fake_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()
    mock_response = MagicMock()
    mock_response.data = [MagicMock(b64_json=fake_b64)]

    with patch.object(provider, "_client") as mock_client:
        mock_client.images.generate = AsyncMock(return_value=mock_response)
        result = await provider.generate(
            prompt="A futuristic city",
            size="1080x1920",
            output_path=output_path,
        )

    assert result.file_path == output_path
    assert (tmp_path / "test.png").exists()


def test_size_mapping():
    provider = OpenAIImageProvider(api_key="test")
    assert provider._map_size("1080x1920") == "1024x1792"
    assert provider._map_size("1920x1080") == "1792x1024"
    assert provider._map_size("1024x1024") == "1024x1024"
