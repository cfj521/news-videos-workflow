import json
import time
from datetime import datetime, timezone

from app import config
from app.logging import get_logger
from app.prompts import resolve_prompt
from app.providers.base import RawArticleData, TextProvider
from app.services.scoring import ScoringService

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


async def distill_weekly_sections(weekly_items: list[dict], text_provider, language: str = "zh") -> list[dict]:
    """把一周扁平条目跨天提炼成主题 sections（形状同 daily_sections）。失败/空则兜底分组。"""
    text = _sample_weekly_items(weekly_items)
    try:
        resp = await text_provider.generate(
            prompt="本周资讯条目：\n" + text, system_prompt=resolve_prompt("weekly_digest", language))
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


def _is_en(language: str) -> bool:
    return (language or "zh").lower().startswith("en")


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
    resp = await tp.generate(prompt=prompt, system_prompt=resolve_prompt("roundup_article", language))
    try:
        scenes = _parse_json(resp).get("scenes", [])
    except Exception:
        log.warning("[S2] parse article scenes failed for '%s'", article.title)
        scenes = []
    if not scenes:
        scenes = [{"narration": article.title, "image_prompt": article.title, "motion_prompt": "", "duration_hint": 5}]
    return scenes[:3]


async def _gen_summary_meta(titles: list[str], tp, language: str = "zh") -> dict:
    resp = await tp.generate(prompt="各条资讯标题：\n" + "\n".join(f"- {t}" for t in titles), system_prompt=resolve_prompt("summary_meta", language))
    try:
        m = _parse_json(resp)
    except Exception:
        m = {}
    return {"title": m.get("title", "资讯汇总"), "description": m.get("description", ""), "tags": m.get("tags", [])}


def _parse_date(s) -> "datetime | None":
    """把 ISO 日期字符串（如 '2026-06-01'）解析为 UTC datetime，失败返回 None。"""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _aihot_candidates(articles: list) -> list:
    """把 AI HOT 三种模式归一为 RawArticleData 候选列表（供 ScoringService 评分）。"""
    out: list = []
    for art in articles:
        method = art.metadata.get("aihot_method", "items")
        sections = art.metadata.get("daily_sections")
        pub = _parse_date(art.metadata.get("report_date") or art.metadata.get("week_end")) or art.published_at
        if method in ("daily", "weekly") and sections:
            for sec in sections:
                label = sec.get("label", "")
                for it in sec.get("items", []):
                    out.append(RawArticleData(
                        title=it.get("title", ""), content=it.get("summary", ""),
                        summary=it.get("summary", ""), source_url=art.source_url,
                        source_name=art.source_name, published_at=pub,
                        category=label, metadata={}))
        else:  # items 模式：article 本身即一条 item
            out.append(art)
    return out


async def _gen_image_prompt(cand, tp, language: str = "zh") -> str:
    """把新闻 title+summary 转成一句视觉画面描述供文生图（非重写旁白）。失败退化为 title。"""
    sys = ("Turn the news into ONE concise visual scene description for image generation "
           "(subject + setting + style). Output the description only, no quotes."
           if _is_en(language) else
           "把这条新闻转成一句用于文生图的画面描述（主体+场景+风格），只输出该句，不要引号。")
    try:
        resp = await tp.generate(prompt=f"{cand.title}。{cand.summary}", system_prompt=sys)
        text = resp.strip().strip('"').strip("「」")
        return text or cand.title
    except Exception:
        log.warning("[S2] image prompt gen failed for '%s' — fallback to title", cand.title[:40])
        return cand.title


async def _run_aihot_direct(articles: list, tp, language: str = "zh") -> dict:
    """AI HOT 直用：归一候选 → ScoringService 选 top N → 每条 1 scene（不 AI 生成旁白）。"""
    candidates = _aihot_candidates(articles)
    top_n = config.get_settings().pipeline.aihot_top_n
    selected = (await ScoringService().select_top(candidates, None, language, n=top_n)).selected  # 规则分；S8 再正式接 tp
    scenes: list[dict] = []
    groups: list[dict] = []
    titles: list[str] = []
    for i, cand in enumerate(selected, start=1):
        image_prompt = await _gen_image_prompt(cand, tp, language)
        scenes.append({
            "id": i, "group_id": i, "group_title": cand.title, "title": cand.title,
            "narration": cand.summary or cand.content, "image_prompt": image_prompt,
            "motion_prompt": "", "duration_hint": 5,
        })
        groups.append({"id": i, "title": cand.title, "source_index": 0})
        titles.append(cand.title)
    meta = await _gen_summary_meta(titles, tp, language)
    log.info("[S2] AI HOT direct: %d candidates → %d scenes (top_n=%d)", len(candidates), len(scenes), top_n)
    return {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
            "groups": groups, "scenes": scenes}


async def run_stage2_multi(articles: list, text_provider, language: str = "zh") -> dict:
    if articles and articles[0].metadata.get("source_group") == "aihot":
        return await _run_aihot_direct(articles, text_provider, language)

    scenes: list[dict] = []
    groups: list[dict] = []
    next_id = 1
    next_gid = 1
    titles: list[str] = []

    for idx, article in enumerate(articles):
        gid = next_gid
        next_gid += 1
        art_scenes = await _gen_article_scenes(article, text_provider, language)
        for sc in art_scenes:
            sc["id"] = next_id
            next_id += 1
            sc["group_id"] = gid
            sc["group_title"] = article.title
            sc["title"] = article.title
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


async def replan_scenes_to_limit(script: dict, limit: int, text_provider, language: str = "zh") -> dict:
    """分镜数超过图片上限时，调 AI 把零碎/简短/相近的分镜合并成 ≤limit 个（合并旁白+单图）。

    失败或无需合并则原样返回。重建后每个合并分镜各自一组，id/group_id 连续。
    """
    scenes = script.get("scenes", [])
    if limit <= 0 or len(scenes) <= limit:
        return script

    lines = [
        f"S{sc.get('id')} [{sc.get('group_title', '')}] 旁白:{sc.get('narration', '')} | 画面:{sc.get('image_prompt', '')}"
        for sc in scenes
    ]
    user = f"图片数量上限：{limit}。当前分镜共 {len(scenes)} 个：\n" + "\n".join(lines)
    try:
        resp = await text_provider.generate(prompt=user, system_prompt=resolve_prompt("scene_replan", language))
        new_scenes = _parse_json(resp).get("scenes", [])
    except Exception:
        log.exception("[S2] scene replan failed, keep original script")
        return script
    if not new_scenes:
        log.warning("[S2] scene replan returned empty, keep original")
        return script

    new_scenes = new_scenes[:limit]
    out: list[dict] = []
    groups: list[dict] = []
    for i, sc in enumerate(new_scenes, start=1):
        gtitle = sc.get("group_title") or f"分镜 {i}"
        out.append({
            "id": i, "group_id": i, "group_title": gtitle,
            "narration": sc.get("narration", ""),
            "image_prompt": sc.get("image_prompt", ""),
            "motion_prompt": sc.get("motion_prompt", ""),
            "duration_hint": sc.get("duration_hint", 5),
        })
        groups.append({"id": i, "title": gtitle, "source_index": i - 1})
    log.info("[S2] replan: %d scenes → %d (limit %d)", len(scenes), len(out), limit)
    return {**script, "groups": groups, "scenes": out}
