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


def _lang_directive(language: str) -> str:
    """追加到各生成 prompt 末尾的语言/画面风格指令（明确覆盖模板内默认，优先级最高）。"""
    if (language or "zh").lower().startswith("en"):
        return ("\n\n[LANGUAGE OVERRIDE] Ignore any language instruction above. Output ALL "
                "narration / title / description / tags in natural, fluent English. For image_prompt, "
                "depict Western / European faces and real-world settings (NOT Asian/Chinese faces).")
    return ("\n\n[语言要求] narration / 标题 / 简介 / 标签 一律用简体中文；"
            "image_prompt 画面人物为亚洲/中国面孔、中式真实场景。")


async def _gen_article_scenes(article, tp, language: str = "zh") -> list[dict]:
    prompt = f"标题：{article.title}\n来源：{article.source_name}\n内容：\n{(article.content or article.title)[:2000]}"
    resp = await tp.generate(prompt=prompt, system_prompt=resolve_prompt("roundup_article") + _lang_directive(language))
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
    resp = await tp.generate(prompt="本组资讯：\n" + "\n".join(lines), system_prompt=resolve_prompt("daily_batch") + _lang_directive(language))
    try:
        scenes = _parse_json(resp).get("scenes", [])
    except Exception:
        log.warning("[S2] parse daily batch scenes failed")
        scenes = []
    if not scenes:
        scenes = [{"narration": it.get("title", ""), "image_prompt": it.get("title", ""), "motion_prompt": "", "duration_hint": 5} for it in items]
    return scenes


async def _gen_summary_meta(titles: list[str], tp, language: str = "zh") -> dict:
    resp = await tp.generate(prompt="各条资讯标题：\n" + "\n".join(f"- {t}" for t in titles), system_prompt=resolve_prompt("summary_meta") + _lang_directive(language))
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

    meta = await _gen_summary_meta(titles, text_provider, language)
    log.info("[S2] multi script: %d groups, %d scenes", len(groups), len(scenes))
    return {"title": meta["title"], "description": meta["description"], "tags": meta["tags"], "groups": groups, "scenes": scenes}
