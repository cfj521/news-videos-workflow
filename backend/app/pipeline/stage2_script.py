import json
import time

from app.logging import get_logger
from app.providers.base import RawArticleData, TextProvider

log = get_logger("stage2")

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

DAILY_DIGEST_SYSTEM_PROMPT = """你是一个专业的 AI 资讯日报播报脚本编写者。根据下面整理好的「今日 AI 日报」生成一个汇总播报视频分镜脚本。

输出要求：
1. 纯 JSON 格式，不要包含 markdown 标记
2. 旁白文案用口语化中文，像新闻主播在播报当日 AI 资讯汇总
3. 第一个分镜根据日报开场语作总览引入，最后一个分镜作总结
4. 中间每条重要资讯一个分镜，按重要性挑选，**总分镜数不超过 10 个**
5. 每个分镜 4-8 秒
6. image_prompt 用英文，描述静态画面的构图、色调、风格
7. motion_prompt 用英文，描述镜头运动方向

输出 JSON 结构：
{
  "title": "视频标题（中文，吸引眼球）",
  "description": "视频简介（中文，1-2句话）",
  "tags": ["标签1", "标签2"],
  "scenes": [
    {
      "id": 1,
      "narration": "旁白文本（中文）",
      "image_prompt": "Scene description in English",
      "motion_prompt": "Camera slowly zooms in",
      "duration_hint": 5
    }
  ]
}"""


async def run_stage2(
    article: RawArticleData,
    text_provider: TextProvider,
    language: str = "zh",
    style: str = "single",
) -> dict:
    log.info("Generating script (style=%s) for: '%s' (%d chars)", style, article.title, len(article.content))
    t0 = time.time()

    if style == "daily":
        system_prompt = DAILY_DIGEST_SYSTEM_PROMPT
        content_limit = 8000
    else:
        system_prompt = SCRIPT_SYSTEM_PROMPT
        content_limit = 3000

    prompt = f"""请为以下内容生成视频分镜脚本：

标题：{article.title}
来源：{article.source_name}
原文：
{article.content[:content_limit]}
"""

    response = await text_provider.generate(prompt=prompt, system_prompt=system_prompt)
    log.debug("Raw response: %d chars", len(response))

    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        log.error("Failed to parse script JSON — raw response:\n%s", cleaned[:500])
        raise

    scene_count = len(result.get("scenes", []))
    log.info("Script generated: '%s' — %d scenes in %.1fs", result.get("title", "?"), scene_count, time.time() - t0)
    return result
