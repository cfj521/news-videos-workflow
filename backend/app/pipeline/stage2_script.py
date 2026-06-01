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


ROUNDUP_ARTICLE_SYSTEM_PROMPT = """你是新闻汇总短视频的分镜脚本编写者。下面给你一条资讯，为它生成 1~3 个分镜（内容多/重要则多，简短则 1 个）。
输出纯 JSON（无 markdown 标记）：
{"scenes":[{"narration":"口语化中文旁白","image_prompt":"English static scene description","motion_prompt":"English camera motion","duration_hint":5}]}
要求：旁白像新闻主播口播；image_prompt 用英文描述构图/色调/风格；分镜数不超过 3。"""

DAILY_BATCH_SYSTEM_PROMPT = """你是 AI 资讯日报短视频的分镜脚本编写者。下面给你同一类目下的若干条资讯，请**每条资讯生成 1 个分镜**，顺序与给定一致。
输出纯 JSON（无 markdown 标记）：
{"scenes":[{"narration":"...","image_prompt":"...","motion_prompt":"...","duration_hint":5}]}
分镜数量须等于给定资讯条数。"""

SUMMARY_META_SYSTEM_PROMPT = """你是短视频运营。下面给你一条汇总视频包含的各条资讯标题，生成整条视频的吸睛标题与简介。
输出纯 JSON（无 markdown 标记）：{"title":"中文标题","description":"1-2句中文简介","tags":["标签1","标签2"]}"""

WEEKLY_DIGEST_SYSTEM_PROMPT = """你是 AI 资讯周报编辑。下面给你过去一整周的全部资讯条目（含日期/分类线索）。
请跨天归纳出**本周 3-5 个最重要的热点主题**，每个主题挑 1-3 条最有代表性的资讯，**全部主题的资讯总条数不超过 9 条**。
要求：体现"本周"视角（趋势、归纳），合并跨天对同一事件的重复报道。
输出纯 JSON（无 markdown 标记）：
{"sections":[{"label":"主题名(中文)","items":[{"title":"资讯标题","summary":"一句话摘要"}]}]}"""


def _parse_json(response: str) -> dict:
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]
    return json.loads(cleaned)


def _sample_weekly_items(weekly_items: list[dict], per_day: int = 8, char_cap: int = 12000) -> str:
    """按天采样渲染，避免简单截断偏向前半周。"""
    from collections import OrderedDict
    by_day: "OrderedDict[str, list]" = OrderedDict()
    for it in weekly_items:
        by_day.setdefault(it.get("date", ""), []).append(it)
    lines: list[str] = []
    total = 0
    for day, day_items in by_day.items():
        for it in day_items[:per_day]:
            line = f"[{day}/{it.get('category', '')}] 「{it.get('title', '')}」{it.get('summary', '')}"
            if total + len(line) > char_cap:
                return "\n".join(lines)
            lines.append(line)
            total += len(line)
    return "\n".join(lines)


def _fallback_weekly_sections(weekly_items: list[dict], max_sections: int = 5, per_section: int = 3) -> list[dict]:
    """提炼失败兜底：按 category 分组，形状同 daily_sections。"""
    from collections import OrderedDict
    groups: "OrderedDict[str, list]" = OrderedDict()
    for it in weekly_items:
        groups.setdefault(it.get("category", "其它"), []).append(
            {"title": it.get("title", ""), "summary": it.get("summary", "")})
    sections: list[dict] = []
    for label, items in groups.items():
        sections.append({"label": label, "items": items[:per_section]})
        if len(sections) >= max_sections:
            break
    return sections


async def distill_weekly_sections(weekly_items: list[dict], text_provider) -> list[dict]:
    """把一周扁平条目跨天提炼成主题 sections（形状同 daily_sections）。失败/空则兜底分组。"""
    text = _sample_weekly_items(weekly_items)
    try:
        resp = await text_provider.generate(
            prompt="本周资讯条目：\n" + text, system_prompt=WEEKLY_DIGEST_SYSTEM_PROMPT)
        sections = _parse_json(resp).get("sections", [])
    except Exception:
        log.warning("[S1] weekly distill parse failed")
        sections = []
    sections = [s for s in sections if s.get("items")]
    if not sections:
        log.warning("[S1] weekly distill empty — fallback group by category")
        sections = _fallback_weekly_sections(weekly_items)
    log.info("[S1] weekly distilled into %d themes", len(sections))
    return sections


def _batch_items(n: int) -> list[int]:
    """把 n 条 items 切成每批 2~4（以 3 为主，无尾批 1）；n==1→[1]。"""
    if n <= 0:
        return []
    sizes: list[int] = []
    remaining = n
    while remaining > 4:
        sizes.append(3)
        remaining -= 3
    sizes.append(remaining)
    return sizes


async def _gen_article_scenes(article, tp) -> list[dict]:
    prompt = f"标题：{article.title}\n来源：{article.source_name}\n内容：\n{(article.content or article.title)[:2000]}"
    resp = await tp.generate(prompt=prompt, system_prompt=ROUNDUP_ARTICLE_SYSTEM_PROMPT)
    try:
        scenes = _parse_json(resp).get("scenes", [])
    except Exception:
        log.warning("[S2] parse article scenes failed for '%s'", article.title)
        scenes = []
    if not scenes:
        scenes = [{"narration": article.title, "image_prompt": article.title, "motion_prompt": "", "duration_hint": 5}]
    return scenes[:3]


async def _gen_daily_batch_scenes(items: list[dict], tp) -> list[dict]:
    lines = [f"{i + 1}. 「{it.get('title', '')}」{it.get('summary', '')}" for i, it in enumerate(items)]
    resp = await tp.generate(prompt="本组资讯：\n" + "\n".join(lines), system_prompt=DAILY_BATCH_SYSTEM_PROMPT)
    try:
        scenes = _parse_json(resp).get("scenes", [])
    except Exception:
        log.warning("[S2] parse daily batch scenes failed")
        scenes = []
    if not scenes:
        scenes = [{"narration": it.get("title", ""), "image_prompt": it.get("title", ""), "motion_prompt": "", "duration_hint": 5} for it in items]
    return scenes


async def _gen_summary_meta(titles: list[str], tp) -> dict:
    resp = await tp.generate(prompt="各条资讯标题：\n" + "\n".join(f"- {t}" for t in titles), system_prompt=SUMMARY_META_SYSTEM_PROMPT)
    try:
        m = _parse_json(resp)
    except Exception:
        m = {}
    return {"title": m.get("title", "资讯汇总"), "description": m.get("description", ""), "tags": m.get("tags", [])}


async def run_stage2_multi(articles: list, text_provider, language: str = "zh") -> dict:
    scenes: list[dict] = []
    groups: list[dict] = []
    next_id = 1
    next_gid = 1
    titles: list[str] = []

    for idx, article in enumerate(articles):
        sections = article.metadata.get("daily_sections")
        if article.metadata.get("aihot_method") in ("daily", "weekly") and sections:
            for section in sections:
                label = section.get("label", "")
                items = section.get("items", [])
                sizes = _batch_items(len(items))
                multi = len(sizes) > 1
                start = 0
                for bi, size in enumerate(sizes):
                    batch = items[start:start + size]
                    start += size
                    gid = next_gid
                    next_gid += 1
                    gtitle = label if not multi else f"{label} ({bi + 1})"
                    batch_scenes = await _gen_daily_batch_scenes(batch, text_provider)
                    if len(batch_scenes) != len(batch):
                        log.warning("[S2] daily batch returned %d scenes for %d items", len(batch_scenes), len(batch))
                    for sc in batch_scenes:
                        sc["id"] = next_id
                        next_id += 1
                        sc["group_id"] = gid
                        sc["group_title"] = gtitle
                        scenes.append(sc)
                    groups.append({"id": gid, "title": gtitle, "source_index": idx})
                    titles.extend(it.get("title", "") for it in batch)
        else:
            gid = next_gid
            next_gid += 1
            art_scenes = await _gen_article_scenes(article, text_provider)
            for sc in art_scenes:
                sc["id"] = next_id
                next_id += 1
                sc["group_id"] = gid
                sc["group_title"] = article.title
                scenes.append(sc)
            groups.append({"id": gid, "title": article.title, "source_index": idx})
            titles.append(article.title)

    meta = await _gen_summary_meta(titles, text_provider)
    log.info("[S2] multi script: %d groups, %d scenes", len(groups), len(scenes))
    return {"title": meta["title"], "description": meta["description"], "tags": meta["tags"], "groups": groups, "scenes": scenes}
