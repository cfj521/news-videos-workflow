# -*- coding: utf-8 -*-
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptDef:
    key: str
    label: str
    desc: str
    default: str       # 中文默认
    default_en: str = ""  # 英文默认（语言=en 时用）


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

_SCENE_REPLAN = """你是短视频分镜优化师。用户给出当前分镜列表和一个图片数量上限。
请把零碎、简短或主题相近的分镜合并，使分镜总数不超过该上限；重要、信息量大的分镜尽量独立保留。
合并时把相关旁白改写融合成一段连贯的口播旁白，并为合并后的画面写一条新的英文 image_prompt。
输出纯 JSON（无 markdown 标记）：
{"scenes":[{"narration":"口语化中文旁白","image_prompt":"English scene description","motion_prompt":"English camera motion","duration_hint":5,"group_title":"中文小标题"}]}
要求：
- scenes 数量严格不超过给定上限。
- narration 用通俗中文口播；image_prompt / motion_prompt 用英文（English only），人物为亚洲/中国人面孔、中式场景。
- group_title 为该分镜的简短中文标题。"""

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

中国视野（额外权重）：
在国际视野基础上，对中国 AI 生态的重要进展给予额外重视——包括国产大模型新版本、中国头部 AI 企业/实验室（如百度、阿里、字节、华为、智谱、月之暗面、深势、商汤等）的重大突破、知名华人技术领袖的研究成果、以及与中国 AI 相关的重要政策与监管动态。
此类高价值中国相关新闻应给予与国际重磅新闻相当的分数（通常 7-10 分）。

输出纯 JSON，不要 markdown 标记：
{"score": <0-10整数>, "reason": "<一句话理由>", "tags": ["<标签1>", "<标签2>"]}"""

# ---- 英文默认（语言=en 时用；同样可在「提示词配置」页编辑覆盖）----
_ROUNDUP_EN = """You are a script writer for news short videos. For the news item below, generate 1-3 scenes (more if rich/important, otherwise 1).
Output PURE JSON (no markdown): {"scenes":[{"narration":"spoken English narration","image_prompt":"English scene description","motion_prompt":"English camera motion","duration_hint":5}]}
Rules:
- narration: natural fluent English like a TV news anchor; simple and clear.
- image_prompt / motion_prompt: English; depict Western / European faces and real-world settings (NOT Asian/Chinese faces).
- At most 3 scenes."""

_DAILY_BATCH_EN = """You are a script writer for an AI news digest short video. For the items below (same category), generate EXACTLY ONE scene per item, in the given order.
Output PURE JSON (no markdown): {"scenes":[{"narration":"spoken English narration","image_prompt":"English scene description","motion_prompt":"English camera motion","duration_hint":5}]}
Rules:
- narration: natural fluent English.
- image_prompt / motion_prompt: English; Western / European faces and settings (NOT Asian/Chinese).
- The number of scenes MUST equal the number of items."""

_SUMMARY_META_EN = """You are a short-video operator. Given the news item titles in a roundup video, produce a catchy English title, description and tags.
Output PURE JSON: {"title":"English title","description":"1-2 sentence English description","tags":["tag1","tag2"]}"""

_WEEKLY_DIGEST_EN = """You are an AI weekly digest editor. Given all news items of the past week (with date/category hints), distill the 3-5 most important themes of the week, each with 1-3 representative items, at most 9 items total. Merge duplicate reports of the same event across days.
Output PURE JSON: {"sections":[{"label":"theme name (English)","items":[{"title":"item title","summary":"one-sentence summary"}]}]}"""

_IMAGE_REGEN_EN = """You are an expert at AI image prompts. From the narration, write a detailed English image-generation prompt for a matching scene.
Output English only; depict Western / European faces and real-world settings (NOT Asian/Chinese). Output only the prompt itself."""

_SCENE_REPLAN_EN = """You are a short-video scene editor. The user gives the current scene list and a maximum image count.
Merge fragmentary, short, or topically-related scenes so the total number of scenes does not exceed the limit; keep important, information-rich scenes standalone when possible.
When merging, rewrite the related narrations into one coherent spoken narration, and write one new English image_prompt for the merged visual.
Output PURE JSON (no markdown): {"scenes":[{"narration":"spoken English narration","image_prompt":"English scene description","motion_prompt":"English camera motion","duration_hint":5,"group_title":"short English title"}]}
Rules:
- The number of scenes MUST NOT exceed the given limit.
- narration: natural fluent English; image_prompt / motion_prompt: English, with Western / European faces and settings.
- group_title: a short English title for the scene."""

_ARTICLE_SUMMARY_EN = """Summarize the news article concisely in English. Output only the summary text."""

_NEWS_SCORING_EN = """You are a news scoring expert. Score the news as an integer 0-10:
- 9-10: major breakthrough / paradigm shift / major release of widely-used tech
- 7-8: in-depth technical article, novel method, insightful analysis
- 5-6: incremental improvement, useful tutorial, moderate interest
- 3-4: minor update, common knowledge, over-hyped
- 0-2: spam, pure promotion, off-topic, trivial
Output PURE JSON (no markdown): {"score": <0-10 int>, "reason": "<one sentence>", "tags": ["<tag1>", "<tag2>"]}"""

PROMPTS: list[PromptDef] = [
    PromptDef("roundup_article", "资讯分镜（单条）", "每条资讯→1~3 个分镜（旁白+画面提示词）", _ROUNDUP, _ROUNDUP_EN),
    PromptDef("summary_meta", "汇总标题/简介", "整片标题、简介、标签", _SUMMARY_META, _SUMMARY_META_EN),
    PromptDef("weekly_digest", "周报主题提炼", "一周条目→3~5 个主题", _WEEKLY_DIGEST, _WEEKLY_DIGEST_EN),
    PromptDef("image_regen", "旁白→图片提示词", "单分镜重生成图片提示词", _IMAGE_REGEN, _IMAGE_REGEN_EN),
    PromptDef("scene_replan", "分镜重规划（图片限额）", "超过图片上限时合并短文章分镜", _SCENE_REPLAN, _SCENE_REPLAN_EN),
    PromptDef("article_summary", "文章摘要（普通源）", "采集后对文章做摘要（字数上限自动追加）", _ARTICLE_SUMMARY, _ARTICLE_SUMMARY_EN),
    PromptDef("news_scoring", "新闻评分（普通源）", "评分排序用", _NEWS_SCORING, _NEWS_SCORING_EN),
]

DEFAULTS: dict[str, str] = {p.key: p.default for p in PROMPTS}
DEFAULTS_EN: dict[str, str] = {p.key: (p.default_en or p.default) for p in PROMPTS}


def resolve_prompt(key: str, language: str = "zh") -> str:
    """用户在「提示词配置」填了就用用户的，否则用内置默认；按 language 选中/英两套。"""
    from app.config import get_settings
    prompts = get_settings().prompts
    if (language or "zh").lower().startswith("en"):
        override = (getattr(prompts, f"{key}_en", "") or "").strip()
        return override or DEFAULTS_EN[key]
    override = (getattr(prompts, key, "") or "").strip()
    return override or DEFAULTS[key]
