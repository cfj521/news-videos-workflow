"""评分系统硬编码集中存放（词表/来源分层/默认权重/参数）。改这里即可调整规则评分。"""

# 来源分层：正则(小写)自上而下首个命中生效，匹配 source_url|source_name；未命中用 DEFAULT_SOURCE_WEIGHT
SOURCE_TIERS: list[tuple[str, float]] = [
    # T1 一手源
    (r"anthropic\.com|openai\.com|deepmind\.google|ai\.meta\.com|mistral\.ai|arxiv\.org", 1.0),
    (r"@(anthropicai|openai|googledeepmind|aiatmeta)\b", 1.0),
    # T2 权威快讯/半一手
    (r"news\.ycombinator\.com|hn\.algolia|hacker news|机器之心|jiqizhixin|量子位|qbitai|marktechpost|theinformation", 0.88),
    # T3 一般科技媒体
    (r"techcrunch|theverge|venturebeat|arstechnica|technologyreview|36kr|36氪|infoq|leiphone|雷锋网|wired", 0.7),
    # T4 搜索/聚合兜底
    (r"tavily|brave|google news|googlenews|serper|duckduckgo", 0.5),
]
DEFAULT_SOURCE_WEIGHT = 0.5

# 关键词（小写子串匹配）
POSITIVE_ENTITIES = [
    "openai", "anthropic", "claude", "gpt", "google", "deepmind", "gemini", "meta", "llama",
    "microsoft", "copilot", "nvidia", "xai", "grok", "mistral", "cohere", "hugging face", "perplexity",
]
POSITIVE_LEADERS = [
    "sam altman", "altman", "dario amodei", "amodei", "demis hassabis", "hassabis", "ilya",
    "karpathy", "lecun", "hinton", "jensen huang", "elon musk",
]
TECH_TERMS = [
    "agent", "agentic", "mcp", "rag", "multimodal", "reasoning", "world model", "embodied",
    "具身", "robotics", "diffusion", "transformer", "fine-tune", "open weights", "开源", "benchmark", "inference",
]
NEGATIVE_TERMS = [
    "crypto", "nft", "bitcoin", "blockchain", "meme coin", "casino", "gambling",
    "加密货币", "比特币", "赌博", "招聘", "hiring", "软文", "广告", "clickbait", "标题党",
]
# 仅中文视野计正向；英文视野剔除"中国"词且此名单不加分
CHINA_TERMS = [
    "中国", "国产", "国产大模型", "信创", "自主可控",
    "阿里", "通义", "qwen", "字节", "豆包", "doubao", "百度", "文心", "ernie", "腾讯", "混元",
    "deepseek", "深度求索", "月之暗面", "kimi", "智谱", "glm", "chatglm", "minimax", "零一万物", "yi",
    "李彦宏", "王小川", "杨植麟", "梁文锋", "李开复",
]

# 默认权重（ScoringCfg 可覆盖）
W_FINAL_LLM, W_FINAL_RULE = 0.6, 0.4
W_SOURCE, W_RECENCY, W_KEYWORD = 0.4, 0.2, 0.4
# 关键词分：基线 + 增减
KW_BASE, KW_ENTITY, KW_TERM, KW_NEG = 0.4, 0.15, 0.08, 0.25
# 新鲜度：0–FULL_DAYS 由 1.0 弱衰减到 WEEK_END；FULL_DAYS–FLOOR_DAYS 衰减到 FLOOR；之后及无时间 = FLOOR
FRESH_FULL_DAYS, FRESH_WEEK_END, FRESH_FLOOR_DAYS, FRESH_FLOOR = 7, 0.9, 30, 0.3
# LLM / 选取
LLM_CONCURRENCY, LLM_CANDIDATE_CAP, MIN_SCORE = 5, 25, 0.35
LLM_TIMEOUT_S, LLM_RETRIES = 30, 1
