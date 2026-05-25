import json

from app.providers.base import RawArticleData, TextProvider

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
      "image_prompt": "Scene description in English with composition, color, style",
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
