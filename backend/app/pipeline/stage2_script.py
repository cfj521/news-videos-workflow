import json
import time

from app.logging import get_logger
from app.prompts import resolve_prompt
from app.providers.base import RawArticleData, TextProvider

log = get_logger("stage2")



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
            prompt="本周资讯条目：\n" + text, system_prompt=resolve_prompt("weekly_digest"))
        sections = _parse_json(resp).get("sections", [])
    except Exception:
        # 含 provider 鉴权/网络错误：记完整堆栈再兜底，避免静默退化成 category 分组
        log.exception("[S1] weekly distill failed (provider/parse) — 将按 category 兜底")
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


def _is_en(language: str) -> bool:
    return (language or "zh").lower().startswith("en")


# 英文模式直接用内置英文指令，绕开可能写死「中文/亚洲面孔」的（含用户自定义）中文模板，
# 避免末尾追加的 override 被模板内强指令压过导致 narration/图片仍是中文/亚洲。
_EN_ROUNDUP = (
    "You are a script writer for news short videos. For the news item below, generate 1-3 scenes "
    "(more if rich/important, otherwise 1).\n"
    'Output PURE JSON (no markdown): {"scenes":[{"narration":"spoken English narration",'
    '"image_prompt":"English scene description","motion_prompt":"English camera motion","duration_hint":5}]}\n'
    "Rules:\n"
    "- narration: natural fluent English like a TV news anchor; simple and clear.\n"
    "- image_prompt / motion_prompt: English; depict Western / European faces and real-world settings "
    "(NOT Asian/Chinese faces).\n"
    "- At most 3 scenes."
)
_EN_DAILY_BATCH = (
    "You are a script writer for an AI news digest short video. For the items below (same category), "
    "generate EXACTLY ONE scene per item, in the given order.\n"
    'Output PURE JSON (no markdown): {"scenes":[{"narration":"spoken English narration",'
    '"image_prompt":"English scene description","motion_prompt":"English camera motion","duration_hint":5}]}\n'
    "Rules:\n"
    "- narration: natural fluent English.\n"
    "- image_prompt / motion_prompt: English; Western / European faces and settings (NOT Asian/Chinese).\n"
    "- The number of scenes MUST equal the number of items."
)
_EN_SUMMARY_META = (
    "You are a short-video operator. Given the news item titles in a roundup video, produce a catchy "
    'English title, description and tags.\nOutput PURE JSON: {"title":"English title",'
    '"description":"1-2 sentence English description","tags":["tag1","tag2"]}'
)


async def _translate_to_en(texts: list[str], tp) -> dict:
    """把一组（中文）小标题翻成英文，返回 {原文: 译文}。失败则空 dict。"""
    uniq = list(dict.fromkeys(t for t in texts if t))
    if not uniq:
        return {}
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(uniq))
    try:
        resp = await tp.generate(
            prompt="Translate each numbered line into a concise, natural English title (keep order):\n" + numbered,
            system_prompt='Output PURE JSON only: {"items":["en1","en2",...]} with the SAME count and order.')
        arr = _parse_json(resp).get("items", [])
        return {uniq[i]: arr[i] for i in range(min(len(uniq), len(arr))) if arr[i]}
    except Exception:
        log.warning("[S2] group title translate to EN failed")
        return {}


async def _gen_article_scenes(article, tp, language: str = "zh") -> list[dict]:
    prompt = f"标题：{article.title}\n来源：{article.source_name}\n内容：\n{(article.content or article.title)[:2000]}"
    system = _EN_ROUNDUP if _is_en(language) else resolve_prompt("roundup_article")
    resp = await tp.generate(prompt=prompt, system_prompt=system)
    try:
        scenes = _parse_json(resp).get("scenes", [])
    except Exception:
        log.warning("[S2] parse article scenes failed for '%s'", article.title)
        scenes = []
    if not scenes:
        scenes = [{"narration": article.title, "image_prompt": article.title, "motion_prompt": "", "duration_hint": 5}]
    return scenes[:3]


async def _gen_daily_batch_scenes(items: list[dict], tp, language: str = "zh") -> list[dict]:
    lines = [f"{i + 1}. 「{it.get('title', '')}」{it.get('summary', '')}" for i, it in enumerate(items)]
    system = _EN_DAILY_BATCH if _is_en(language) else resolve_prompt("daily_batch")
    resp = await tp.generate(prompt="本组资讯：\n" + "\n".join(lines), system_prompt=system)
    try:
        scenes = _parse_json(resp).get("scenes", [])
    except Exception:
        log.warning("[S2] parse daily batch scenes failed")
        scenes = []
    if not scenes:
        scenes = [{"narration": it.get("title", ""), "image_prompt": it.get("title", ""), "motion_prompt": "", "duration_hint": 5} for it in items]
    return scenes


async def _gen_summary_meta(titles: list[str], tp, language: str = "zh") -> dict:
    system = _EN_SUMMARY_META if _is_en(language) else resolve_prompt("summary_meta")
    resp = await tp.generate(prompt="各条资讯标题：\n" + "\n".join(f"- {t}" for t in titles), system_prompt=system)
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
                    batch_scenes = await _gen_daily_batch_scenes(batch, text_provider, language)
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
            art_scenes = await _gen_article_scenes(article, text_provider, language)
            for sc in art_scenes:
                sc["id"] = next_id
                next_id += 1
                sc["group_id"] = gid
                sc["group_title"] = article.title
                scenes.append(sc)
            groups.append({"id": gid, "title": article.title, "source_index": idx})
            titles.append(article.title)

    # 英文模式：子标题（分组名，可能来自数据源中文分类）翻成英文
    if _is_en(language) and groups:
        trans = await _translate_to_en([g["title"] for g in groups], text_provider)
        if trans:
            for g in groups:
                g["title"] = trans.get(g["title"], g["title"])
            for sc in scenes:
                if sc.get("group_title") in trans:
                    sc["group_title"] = trans[sc["group_title"]]

    meta = await _gen_summary_meta(titles, text_provider, language)
    log.info("[S2] multi script: %d groups, %d scenes", len(groups), len(scenes))
    return {"title": meta["title"], "description": meta["description"], "tags": meta["tags"], "groups": groups, "scenes": scenes}
