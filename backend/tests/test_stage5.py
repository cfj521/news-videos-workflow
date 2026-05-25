from unittest.mock import AsyncMock

import pytest

from app.pipeline.stage5_compose import run_stage5
from app.providers.base import VideoResult


@pytest.mark.asyncio
async def test_stage5_calls_composer():
    mock_composer = AsyncMock()
    mock_composer.compose.return_value = VideoResult(
        file_path="output.mp4",
        thumbnail_path="thumb.jpg",
        duration_ms=11000,
        resolution="1080x1920",
    )

    timeline = {
        "entries": [
            {
                "scene_id": 1,
                "start_ms": 0,
                "end_ms": 5000,
                "image_path": "img.png",
                "audio_path": "audio.mp3",
                "audio_duration_ms": 5000,
                "subtitle_text": "Text",
            },
        ],
        "total_duration_ms": 5000,
    }

    result = await run_stage5(
        timeline=timeline,
        composer=mock_composer,
        assets_dir="/tmp/assets",
        output_path="/tmp/output.mp4",
    )

    assert result.file_path == "output.mp4"
    mock_composer.compose.assert_called_once()
