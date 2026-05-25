from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.text.claude import ClaudeTextProvider


@pytest.mark.asyncio
async def test_claude_generate():
    provider = ClaudeTextProvider(api_key="test-key")
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Generated response")]

    with patch.object(provider, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_message)
        result = await provider.generate("test prompt")

    assert result == "Generated response"


@pytest.mark.asyncio
async def test_claude_generate_with_system():
    provider = ClaudeTextProvider(api_key="test-key")
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Response")]

    with patch.object(provider, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_message)
        result = await provider.generate("prompt", system_prompt="You are helpful")

    assert result == "Response"
    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["system"] == "You are helpful"
