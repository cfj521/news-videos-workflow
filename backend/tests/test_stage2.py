import json
from unittest.mock import AsyncMock

import pytest

from app.pipeline.stage2_script import DAILY_DIGEST_SYSTEM_PROMPT, SCRIPT_SYSTEM_PROMPT, run_stage2
from app.providers.base import RawArticleData

SAMPLE_SCRIPT_JSON = json.dumps(
    {
        "title": "AI 新突破",
        "description": "今天的科技新闻速报",
        "tags": ["AI", "科技"],
        "scenes": [
            {
                "id": 1,
                "narration": "今天我们来看一条重磅消息",
                "image_prompt": "A futuristic chip closeup",
                "motion_prompt": "Camera slowly zooms in",
                "duration_hint": 5,
            },
            {
                "id": 2,
                "narration": "研究人员宣布了一项重大突破",
                "image_prompt": "Researchers in a laboratory",
                "motion_prompt": "Camera slowly pans",
                "duration_hint": 6,
            },
        ],
    }
)


@pytest.mark.asyncio
async def test_stage2_generates_script():
    mock_text = AsyncMock()
    mock_text.generate.return_value = SAMPLE_SCRIPT_JSON

    article = RawArticleData(
        title="AI Breakthrough",
        content="Scientists announced a major AI breakthrough today...",
        source_url="https://example.com",
        source_name="Test",
    )

    script = await run_stage2(article=article, text_provider=mock_text)

    assert script["title"] == "AI 新突破"
    assert len(script["scenes"]) == 2
    assert script["scenes"][0]["narration"] != ""
    assert script["scenes"][0]["image_prompt"] != ""


@pytest.mark.asyncio
async def test_stage2_calls_provider_with_article():
    mock_text = AsyncMock()
    mock_text.generate.return_value = SAMPLE_SCRIPT_JSON

    article = RawArticleData(
        title="Test Article",
        content="Article content here",
        source_url="https://example.com",
        source_name="Source",
    )

    await run_stage2(article=article, text_provider=mock_text)

    call_args = mock_text.generate.call_args
    prompt = call_args[1].get("prompt", call_args[0][0] if call_args[0] else "")
    assert "Test Article" in prompt
    assert "Article content" in prompt


def test_system_prompt_exists():
    assert "分镜" in SCRIPT_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_stage2_daily_uses_digest_prompt():
    mock_text = AsyncMock()
    mock_text.generate.return_value = SAMPLE_SCRIPT_JSON

    article = RawArticleData(
        title="今日 AI 日报",
        content="日报正文内容。" * 800,  # 远超 3000 字，验证放宽截断
        source_url="https://aihot.virxact.com",
        source_name="AI HOT 日报",
        metadata={"source_group": "aihot", "aihot_method": "daily"},
    )

    await run_stage2(article=article, text_provider=mock_text, style="daily")

    kwargs = mock_text.generate.call_args[1]
    assert kwargs["system_prompt"] == DAILY_DIGEST_SYSTEM_PROMPT
    assert len(kwargs["prompt"]) > 4000  # 截断上限放宽到 8000


def test_daily_digest_prompt_exists():
    assert "日报" in DAILY_DIGEST_SYSTEM_PROMPT
    assert "分镜" in DAILY_DIGEST_SYSTEM_PROMPT
