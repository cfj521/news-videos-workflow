# -*- coding: utf-8 -*-
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptDef:
    key: str
    label: str
    desc: str
    default: str


_ROUNDUP = """你是新闻短视频的分镜脚本编写者。下面给你一条资讯，为它生成 1~3 个分镜（内容多/重要则多，简短则 1 个）。
输出纯 JSON（无 markdown 标记）：
{"scenes":[{"narration":"口语化中文旁白","image_prompt":"English scene description","motion_prompt":"English camera motion","duration_hint":5}]}
要求：
- narration：像新闻主播口播的通俗中文，简单易懂，少用生僻词和英文。
- image_prompt / motion_prompt：用英文（English only）；画面人物必须是亚洲/中国人面孔（East Asian / Chinese faces），场景与背景为中式真实环境，避免出现欧美面孔。
- 分镜数不超过 3。"""

_DAILY_BATCH = """你是 AI 资讯日报短视频的分镜脚本编写者。下面给你同一类目下的若干条资讯，请每条资讯生成 1 个分镜，顺序与给定一致。
输出纯 JSON（无 markdown 标记）：
{"scenes":[{"narration":"口语化中文旁白","image_prompt":"English scene description","motion_prompt":"English camera motion","duration_hint":5}]}
要求：
- narration：通俗易懂的中文口播，少用英文。
- image_prompt / motion_prompt：用英文（English only）；人物为亚洲/中国人面孔（East Asian / Chinese faces）、中式场景背景，避免欧美面孔。
- 分镜数量须等于给定资讯条数。"""

_SUMMARY_META = """你是短视频运营。下面给你一条汇总视频包含的各条资讯标题，生成整条视频的吸睛标题与简介。
输出纯 JSON（无 markdown 标记）：{"title":"中文标题","description":"1-2句中文简介","tags":["标签1","标签2"]}"""

_WEEKLY_DIGEST = """你是 AI 资讯周报编辑。下面给你过去一整周的全部资讯条目（含日期/分类线索）。
请跨天归纳出**本周 3-5 个最重要的热点主题**，每个主题挑 1-3 条最有代表性的资讯，**全部主题的资讯总条数不超过 9 条**。
要求：体现"本周"视角（趋势、归纳），合并跨天对同一事件的重复报道。
输出纯 JSON（无 markdown 标记）：
{"sections":[{"label":"主题名(中文)","items":[{"title":"资讯标题","summary":"一句话摘要"}]}]}"""

_IMAGE_REGEN = """你是视频图片提示词专家。根据旁白文本生成一段详细的 AI 图片生成提示词，描述一张能配合旁白内容的画面。
要求：用英文输出（English only）；画面人物必须是亚洲/中国人面孔（East Asian / Chinese），场景与背景为中式真实环境，避免欧美面孔。只输出提示词本身，不要其他内容。"""

_ARTICLE_SUMMARY = """用中文为新闻文章生成简洁摘要。只输出摘要文本。"""

_NEWS_SCORING = """你是新闻评分专家。根据以下标准为新闻打分（0-10 整数）：

评分标准：
- 9-10：重大突破、范式转变、广泛使用的技术的重大版本发布
- 7-8：有深度的技术文章、新颖方法、有洞见的分析
- 5-6：增量改进、有用教程、中等社区兴趣
- 3-4：小更新、常识内容、过度宣传
- 0-2：垃圾、纯推广、离题、琐碎更新

评分要考虑：
- 技术深度和新颖性
- 对领域的潜在影响
- 写作/展示质量
- 与 AI/ML、软件工程的相关性
- 社区互动信号（高投票+有质量的讨论 = 社区验证的重要性）

输出纯 JSON，不要 markdown 标记：
{"score": <0-10整数>, "reason": "<一句话理由>", "tags": ["<标签1>", "<标签2>"]}"""

PROMPTS: list[PromptDef] = [
    PromptDef("roundup_article", "资讯分镜（单条）", "每条资讯→1~3 个分镜（旁白+画面提示词）", _ROUNDUP),
    PromptDef("daily_batch", "日报/周报分镜（成组）", "同类目若干条→每条 1 个分镜", _DAILY_BATCH),
    PromptDef("summary_meta", "汇总标题/简介", "整片标题、简介、标签", _SUMMARY_META),
    PromptDef("weekly_digest", "周报主题提炼", "一周条目→3~5 个主题", _WEEKLY_DIGEST),
    PromptDef("image_regen", "旁白→图片提示词", "单分镜重生成图片提示词", _IMAGE_REGEN),
    PromptDef("article_summary", "文章摘要（普通源）", "采集后对文章做摘要（字数上限自动追加）", _ARTICLE_SUMMARY),
    PromptDef("news_scoring", "新闻评分（普通源）", "评分排序用", _NEWS_SCORING),
]

DEFAULTS: dict[str, str] = {p.key: p.default for p in PROMPTS}


def resolve_prompt(key: str) -> str:
    """用户在 Settings 里填了就用用户的，否则用内置默认。"""
    from app.config import get_settings
    override = (getattr(get_settings().prompts, key, "") or "").strip()
    return override or DEFAULTS[key]
