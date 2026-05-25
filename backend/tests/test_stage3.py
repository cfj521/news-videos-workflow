from unittest.mock import AsyncMock

import pytest

from app.pipeline.stage3_assets import run_stage3
from app.providers.base import AssetResult


@pytest.mark.asyncio
async def test_stage3_generates_image_and_audio(tmp_path):
    mock_image = AsyncMock()
    mock_image.generate.return_value = AssetResult(file_path="scene_01_image.png")

    mock_tts = AsyncMock()
    mock_tts.synthesize.return_value = AssetResult(file_path="scene_01_audio.mp3", duration_ms=5000)

    script = {
        "title": "Test",
        "scenes": [
            {
                "id": 1,
                "narration": "旁白文本",
                "image_prompt": "A futuristic scene",
                "motion_prompt": "",
                "duration_hint": 5,
            },
            {
                "id": 2,
                "narration": "第二段旁白",
                "image_prompt": "A laboratory",
                "motion_prompt": "",
                "duration_hint": 6,
            },
        ],
    }

    assets = await run_stage3(
        script=script,
        image_provider=mock_image,
        tts_provider=mock_tts,
        assets_dir=str(tmp_path),
        resolution="1080x1920",
    )

    assert len(assets) == 2
    assert assets[0]["scene_id"] == 1
    assert "image" in assets[0]
    assert "audio" in assets[0]
    assert mock_image.generate.call_count == 2
    assert mock_tts.synthesize.call_count == 2


@pytest.mark.asyncio
async def test_stage3_handles_single_scene_failure(tmp_path):
    mock_image = AsyncMock()
    mock_image.generate.side_effect = [
        AssetResult(file_path="scene_01_image.png"),
        Exception("API Error"),
    ]

    mock_tts = AsyncMock()
    mock_tts.synthesize.return_value = AssetResult(file_path="audio.mp3", duration_ms=5000)

    script = {
        "title": "Test",
        "scenes": [
            {
                "id": 1,
                "narration": "T1",
                "image_prompt": "P1",
                "motion_prompt": "",
                "duration_hint": 5,
            },  # noqa: E501
            {
                "id": 2,
                "narration": "T2",
                "image_prompt": "P2",
                "motion_prompt": "",
                "duration_hint": 5,
            },  # noqa: E501
        ],
    }

    assets = await run_stage3(
        script=script,
        image_provider=mock_image,
        tts_provider=mock_tts,
        assets_dir=str(tmp_path),
    )

    assert len(assets) == 2
    assert assets[0]["image"]["file_path"] == "scene_01_image.png"
    assert "error" in assets[1]
