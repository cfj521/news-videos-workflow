import base64
from pathlib import Path

import openai

from app.providers.base import AssetResult, ImageProvider

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
