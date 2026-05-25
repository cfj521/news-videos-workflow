# Plan 3: Stage 2+3 Content Generation — 文案生成、图片生成、TTS

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Stage 2（文案和分镜生成）和 Stage 3（图片生成 + TTS 语音合成），从新闻文章生成完整的视频分镜脚本和素材。

**Architecture:** TextProvider（Claude）生成分镜 JSON，ImageProvider（OpenAI gpt-image-2）生成图片，TTSProvider（Edge-TTS）生成语音。每个 Provider 独立可测试。

**Tech Stack:** anthropic SDK, openai SDK, edge-tts, Pillow

**前置依赖:** Plan 1 + Plan 2 已完成

---

### Task 1: Claude TextProvider

**Files:**
- Create: `backend/app/providers/text/claude.py`
- Test: `backend/tests/test_text_claude.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_text_claude.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_text_claude.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 Claude Provider**

```python
# backend/app/providers/text/claude.py
import anthropic

from app.providers.base import TextProvider


class ClaudeTextProvider(TextProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        message = await self._client.messages.create(**kwargs)
        return message.content[0].text
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_text_claude.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/text/claude.py backend/tests/test_text_claude.py
git commit -m "feat: add Claude text provider"
```

---

### Task 2: Stage 2 — 分镜脚本生成

**Files:**
- Create: `backend/app/pipeline/stage2_script.py`
- Test: `backend/tests/test_stage2.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_stage2.py
import pytest
import json
from unittest.mock import AsyncMock
from app.pipeline.stage2_script import run_stage2, SCRIPT_SYSTEM_PROMPT
from app.providers.base import RawArticleData

SAMPLE_SCRIPT_JSON = json.dumps({
    "title": "AI 新突破",
    "description": "今天的科技新闻速报",
    "tags": ["AI", "科技"],
    "scenes": [
        {
            "id": 1,
            "narration": "今天我们来看一条重磅消息",
            "image_prompt": "一张科技感十足的芯片特写图",
            "motion_prompt": "镜头缓慢推进",
            "duration_hint": 5
        },
        {
            "id": 2,
            "narration": "研究人员宣布了一项重大突破",
            "image_prompt": "实验室中的研究人员",
            "motion_prompt": "镜头缓慢平移",
            "duration_hint": 6
        },
    ],
})


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
    prompt = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    assert "Test Article" in prompt
    assert "Article content" in prompt


def test_system_prompt_exists():
    assert "分镜" in SCRIPT_SYSTEM_PROMPT or "scene" in SCRIPT_SYSTEM_PROMPT.lower()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_stage2.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 Stage 2**

```python
# backend/app/pipeline/stage2_script.py
import json

from app.providers.base import TextProvider, RawArticleData


SCRIPT_SYSTEM_PROMPT = """你是一个专业的新闻视频分镜脚本编写者。根据新闻原文生成一个视频分镜脚本。

输出要求：
1. 纯 JSON 格式，不要包含 markdown 标记
2. 旁白文案用口语化中文，像是一个专业新闻主播在播报
3. 每个分镜 3-8 秒，整个视频 30-90 秒
4. image_prompt 用英文，描述一张静态画面的构图、色调、风格
5. motion_prompt 用英文，描述镜头运动方向（用于视频动效）
6. 第一个分镜作为开场引入，最后一个分镜作为总结

输出 JSON 结构：
{
  "title": "视频标题（中文，吸引眼球）",
  "description": "视频简介（中文，1-2句话）",
  "tags": ["标签1", "标签2"],
  "scenes": [
    {
      "id": 1,
      "narration": "旁白文本（中文）",
      "image_prompt": "A detailed scene description in English, specifying composition, color palette, and style",
      "motion_prompt": "Camera slowly zooms in, particles floating",
      "duration_hint": 5
    }
  ]
}"""


async def run_stage2(
    article: RawArticleData,
    text_provider: TextProvider,
    language: str = "zh",
) -> dict:
    prompt = f"""请为以下新闻生成视频分镜脚本：

标题：{article.title}
来源：{article.source_name}
原文：
{article.content[:3000]}
"""

    response = await text_provider.generate(
        prompt=prompt,
        system_prompt=SCRIPT_SYSTEM_PROMPT,
    )

    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]

    return json.loads(cleaned)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_stage2.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/stage2_script.py backend/tests/test_stage2.py
git commit -m "feat: add Stage 2 - script generation with Claude"
```

---

### Task 3: OpenAI ImageProvider

**Files:**
- Create: `backend/app/providers/image/openai_image.py`
- Test: `backend/tests/test_image_openai.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_image_openai.py
import pytest
import base64
from unittest.mock import patch, MagicMock, AsyncMock
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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_image_openai.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 OpenAI Image Provider**

```python
# backend/app/providers/image/openai_image.py
import base64
from pathlib import Path

import openai

from app.providers.base import ImageProvider, AssetResult


SIZE_MAP = {
    "1080x1920": "1024x1792",
    "1920x1080": "1792x1024",
    "1024x1024": "1024x1024",
}


class OpenAIImageProvider(ImageProvider):
    def __init__(self, api_key: str, model: str = "gpt-image-1"):
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._model = model

    async def generate(
        self,
        prompt: str,
        size: str = "1080x1920",
        output_path: str = "",
    ) -> AssetResult:
        api_size = self._map_size(size)

        response = await self._client.images.generate(
            model=self._model,
            prompt=prompt,
            size=api_size,
            quality="high",
            n=1,
            response_format="b64_json",
        )

        image_data = base64.b64decode(response.data[0].b64_json)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(image_data)

        return AssetResult(file_path=output_path)

    def _map_size(self, size: str) -> str:
        return SIZE_MAP.get(size, "1024x1792")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_image_openai.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/image/openai_image.py backend/tests/test_image_openai.py
git commit -m "feat: add OpenAI image generation provider"
```

---

### Task 4: Edge-TTS Provider

**Files:**
- Create: `backend/app/providers/tts/edge_tts_provider.py`
- Test: `backend/tests/test_tts_edge.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_tts_edge.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.providers.tts.edge_tts_provider import EdgeTTSProvider


@pytest.mark.asyncio
async def test_edge_tts_synthesize(tmp_path):
    provider = EdgeTTSProvider()
    output_path = str(tmp_path / "test.mp3")

    with patch("app.providers.tts.edge_tts_provider.edge_tts.Communicate") as MockComm:
        mock_comm = MagicMock()
        mock_comm.save = AsyncMock()
        MockComm.return_value = mock_comm

        result = await provider.synthesize(
            text="今天我们来看一条重磅消息",
            voice="zh-CN-XiaoxiaoNeural",
            output_path=output_path,
        )

    assert result.file_path == output_path
    MockComm.assert_called_once()


def test_default_voice():
    provider = EdgeTTSProvider()
    assert provider._default_voice == "zh-CN-XiaoxiaoNeural"

    provider_en = EdgeTTSProvider(default_voice="en-US-JennyNeural")
    assert provider_en._default_voice == "en-US-JennyNeural"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_tts_edge.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 Edge-TTS Provider**

```python
# backend/app/providers/tts/edge_tts_provider.py
from pathlib import Path

import edge_tts

from app.providers.base import TTSProvider, AssetResult


class EdgeTTSProvider(TTSProvider):
    def __init__(self, default_voice: str = "zh-CN-XiaoxiaoNeural"):
        self._default_voice = default_voice

    async def synthesize(
        self,
        text: str,
        voice: str = "",
        speed: float = 1.0,
        output_path: str = "",
    ) -> AssetResult:
        voice = voice or self._default_voice
        rate_str = f"+{int((speed - 1) * 100)}%" if speed >= 1 else f"{int((speed - 1) * 100)}%"

        communicate = edge_tts.Communicate(text, voice, rate=rate_str)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        await communicate.save(output_path)

        duration_ms = self._estimate_duration(text, speed)

        return AssetResult(file_path=output_path, duration_ms=duration_ms)

    def _estimate_duration(self, text: str, speed: float) -> int:
        chars = len(text)
        chars_per_second = 4.0 * speed  # 中文约 4 字/秒
        return int((chars / chars_per_second) * 1000)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_tts_edge.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/tts/edge_tts_provider.py backend/tests/test_tts_edge.py
git commit -m "feat: add Edge-TTS provider for speech synthesis"
```

---

### Task 5: Stage 3 — 素材生成 Pipeline

**Files:**
- Create: `backend/app/pipeline/stage3_assets.py`
- Test: `backend/tests/test_stage3.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_stage3.py
import pytest
from unittest.mock import AsyncMock
from app.pipeline.stage3_assets import run_stage3
from app.providers.base import AssetResult


@pytest.mark.asyncio
async def test_stage3_generates_image_and_audio(tmp_path):
    mock_image = AsyncMock()
    mock_image.generate.return_value = AssetResult(file_path="scene_01_image.png")

    mock_tts = AsyncMock()
    mock_tts.synthesize.return_value = AssetResult(
        file_path="scene_01_audio.mp3", duration_ms=5000,
    )

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
    mock_tts.synthesize.return_value = AssetResult(
        file_path="audio.mp3", duration_ms=5000,
    )

    script = {
        "title": "Test",
        "scenes": [
            {"id": 1, "narration": "Text 1", "image_prompt": "P1", "motion_prompt": "", "duration_hint": 5},
            {"id": 2, "narration": "Text 2", "image_prompt": "P2", "motion_prompt": "", "duration_hint": 5},
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
    assert assets[1].get("error") is not None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd backend && python -m pytest tests/test_stage3.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 Stage 3**

```python
# backend/app/pipeline/stage3_assets.py
from pathlib import Path

from app.providers.base import ImageProvider, TTSProvider, AssetResult


async def run_stage3(
    script: dict,
    image_provider: ImageProvider,
    tts_provider: TTSProvider,
    assets_dir: str,
    resolution: str = "1080x1920",
    video_route: str = "hyperframes",
) -> list[dict]:
    Path(assets_dir).mkdir(parents=True, exist_ok=True)
    scene_assets: list[dict] = []

    for scene in script["scenes"]:
        scene_id = scene["id"]
        entry: dict = {"scene_id": scene_id}

        try:
            image_path = str(Path(assets_dir) / f"scene_{scene_id:02d}_image.png")
            image_result = await image_provider.generate(
                prompt=scene["image_prompt"],
                size=resolution,
                output_path=image_path,
            )
            entry["image"] = {
                "file_path": image_result.file_path,
                "duration_ms": image_result.duration_ms,
            }
        except Exception as e:
            entry["error"] = f"image generation failed: {e}"

        try:
            audio_path = str(Path(assets_dir) / f"scene_{scene_id:02d}_audio.mp3")
            audio_result = await tts_provider.synthesize(
                text=scene["narration"],
                output_path=audio_path,
            )
            entry["audio"] = {
                "file_path": audio_result.file_path,
                "duration_ms": audio_result.duration_ms,
            }
        except Exception as e:
            entry.setdefault("error", "")
            entry["error"] += f" tts failed: {e}"

        scene_assets.append(entry)

    return scene_assets
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd backend && python -m pytest tests/test_stage3.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/stage3_assets.py backend/tests/test_stage3.py
git commit -m "feat: add Stage 3 - image generation and TTS asset pipeline"
```

---

### Task 6: 运行全部 Plan 3 测试

- [ ] **Step 1: 运行完整测试**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: 全部 PASS

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "chore: finalize Plan 3 - content generation pipeline"
```

---

## Plan 3 完成检查

- ✅ ClaudeTextProvider — AI 文案生成
- ✅ Stage 2 pipeline — 从新闻生成分镜 JSON
- ✅ OpenAIImageProvider — 图片生成
- ✅ EdgeTTSProvider — 语音合成
- ✅ Stage 3 pipeline — 批量生成图片+音频素材
- ✅ 错误处理：单个分镜失败不阻塞整体
