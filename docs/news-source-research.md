# 新闻源与评分排序 — 开源项目调研

---

## 重点项目

### 1. Horizon — AI 新闻雷达

- **仓库**: https://github.com/Thysrael/Horizon
- **Stars**: 46.4k | **语言**: Python | **活跃度**: 2026 年 5 月仍在更新

**做什么的**

全自动 AI 新闻聚合器。从 Hacker News、RSS、Reddit、Telegram、Twitter/X、GitHub Releases 等多源拉取内容，自动去重、AI 评分、过滤低质量内容、富化上下文，输出中英双语每日简报。

**信息源管理**

支持的源类型及采集方式：

| 源 | 采集方法 | 配置项 |
|----|---------|--------|
| Hacker News | Algolia API | 最低分数阈值、查询关键词 |
| RSS/Atom | feedparser | 订阅 URL 列表 |
| Reddit | Reddit API / 爬虫 | subreddit 列表、排序方式 |
| Telegram | Telethon (MTProto) | 频道列表 |
| Twitter/X | 爬虫 / Nitter | 用户列表、搜索关键词 |
| GitHub | Releases API | 仓库列表 |

每个源独立配置采集频率、过滤规则、语言偏好。源之间通过统一的文章数据结构对齐。

**评分方法**

用 LLM 对每条新闻打 **0-10 分**。核心做法：

1. 将文章标题 + 摘要 + 来源信息拼成 prompt
2. 调用 LLM（支持 Claude/GPT/Gemini/DeepSeek/Ollama 本地模型）
3. LLM 返回整数评分 + 简短理由
4. 用户设置阈值（如 ≥7 分才保留），低于阈值的直接丢弃

评分维度包括：新闻价值、技术深度、时效性、影响范围。prompt 可自定义调整评分偏好。

**去重策略**

跨平台 URL 去重 — 同一篇文章从 HN 和 Reddit 同时抓到时，通过 URL 归一化（去除 tracking 参数、统一 scheme）识别为同一条目，只保留评分最高的那条。

**与本项目的关系**

架构与我们的 Stage 1（搜索整理）高度重合：
- 多源采集 → 对应我们的 `stage1_collect.py` + 各 collector
- AI 评分 → 对应我们的 `scoring.py`（目前是简单规则，可升级为 LLM 评分）
- URL 去重 → 对应我们的 `dedup.py`

**可以借鉴的：**
- LLM 评分的 prompt 设计（评分维度 + 输出格式约束）
- 评分阈值过滤机制
- URL 归一化去重（去 tracking 参数、统一 www/non-www）
- 多源统一数据结构的设计

---

### 2. text-dedup — 文本去重算法库

- **仓库**: https://github.com/ChenghaoMou/text-dedup
- **Stars**: 708 | **语言**: Python | **活跃度**: 2025 年活跃更新

**做什么的**

一站式文本去重工具库，实现了 4 种主流去重算法，专门处理大规模文本数据集的近似/精确去重。

**算法对比**

| 算法 | 类型 | F1 分数 | 速度 | 适用场景 |
|------|------|---------|------|----------|
| MinHash + LSH | 近似去重 | 0.9455 | 24s | 新闻文章近似去重（推荐） |
| SimHash | 近似去重 | 0.7853 | 210s | 大规模文档指纹比较 |
| SuffixArray | 精确子串 | 0.6400 | 34s | 检测大段复制粘贴 |
| Bloom Filter | 精确去重 | N/A | 极快 | URL/标题完全相同 |

**MinHash 原理（推荐用于新闻去重）**

1. 将文章文本切分为 n-gram（如 5-gram）
2. 对每个 n-gram 集合计算多个 hash 函数，取每组最小值组成签名（MinHash signature）
3. 用 LSH（Locality-Sensitive Hashing）将相似签名分桶，同桶内的文档视为候选重复对
4. 对候选对计算 Jaccard 相似度，超过阈值（如 0.7）判定为重复

优势：时间复杂度接近 O(n)，适合实时/增量去重。

**使用方式**

```python
# TOML 配置驱动
# 或直接 Python API
from text_dedup.minhash import MinHashDeduplicator

dedup = MinHashDeduplicator(
    num_perm=128,        # hash 函数数量，越大越精确
    threshold=0.7,       # Jaccard 相似度阈值
    ngram_size=5,        # n-gram 大小
)

# 输入文档列表，返回去重后的索引
unique_indices = dedup.fit_transform(documents)
```

**与本项目的关系**

目前 `dedup.py` 大概率用的是简单的标题/URL 匹配。可以用 MinHash 升级为基于正文内容的近似去重：
- 同一事件的不同报道（标题不同但内容相似）能被识别
- 洗稿/转载检测
- 增量去重（新文章 vs 历史库）

**可以借鉴的：**
- MinHash + LSH 算法实现，直接 pip install 使用
- Jaccard 阈值 0.7 是新闻去重的合理起点
- 5-gram 切分对中文需要调整（改为字级别 or jieba 分词后的词级别）

---

### 3. quality-news — HN 排序公式改进

- **仓库**: https://github.com/social-protocols/quality-news
- **Stars**: 84 | **语言**: Go | **活跃度**: 持续更新

**做什么的**

对 Hacker News 排序算法的实验性改进。每分钟爬取 HN API 数据，提出用 **upvoteRate**（投票率）替代绝对票数的新排序方法，消除"先发优势"和"位置偏差"。

**HN 经典排序公式**

```
score = (upvotes - 1)^0.8 / (age_hours + 2)^1.8
```

问题：
- **先发优势**：早发的帖子在首页停留久，获得更多曝光和票数，形成正反馈
- **位置偏差**：排名靠前的帖子更容易被看到和投票，与内容质量无关
- 结果：排名高的不一定好，只是发得早或运气好

**upvoteRate 改进算法**

核心思想：不看"获得了多少票"，而看"看到这篇文章的人中有多少比例投了票"。

```
upvoteRate = P(user votes for this article) / P(user votes for average article)
```

计算方法：
1. 追踪每篇文章在 HN 首页各位置的停留时间
2. 根据位置估算曝光量（位置 1 曝光最高，往下递减）
3. `upvoteRate = actual_votes / expected_votes_given_exposure`
4. 按 upvoteRate 排序

效果：
- 一篇好文章即使发得晚、曝光少，只要看过的人投票率高，就会排上来
- 一篇平庸文章即使因为早发获得了很多票，投票率不高就会下降
- 消除了位置和时间的系统性偏差

**数据展示**

项目提供了一个实时对比页面，展示 upvoteRate 排序 vs HN 默认排序的差异，附带每篇文章的投票率变化曲线图。

**与本项目的关系**

目前 `scoring.py` 可能用的是简单的 points/upvotes 排序。可以引入 upvoteRate 思路：

```python
# 简化版 upvoteRate 估算
def estimate_quality(article):
    # 从 HN API 获取 points 和 age
    points = article.points
    age_hours = article.age_hours
    
    # 估算曝光量（基于文章在首页的平均位置和停留时间）
    # 简化：用 age 和 HN 的流量模型粗略估算
    expected_votes = estimate_exposure(age_hours) * avg_vote_rate
    
    # upvoteRate = 实际投票 / 期望投票
    return points / max(expected_votes, 1)
```

**可以借鉴的：**
- upvoteRate 的核心思路：用投票率而非绝对票数衡量质量
- 位置偏差的矫正方法
- 可以作为 AI 评分之外的**数据驱动信号**，两者结合效果更好
- 算法本身与语言无关，虽然项目是 Go 写的，逻辑可以直接用 Python 实现

---

## 其他参考项目

| 项目 | Stars | 核心价值 |
|------|-------|---------|
| [auto-news](https://github.com/finaldie/auto-news) | 848 | 多源 + LangChain LLM 降噪管线 |
| [UglyFeed](https://github.com/fabriziosalmi/UglyFeed) | 307 | RSS → LLM 质量评估 → 内容改写三阶段 |
| [RSSbrew](https://github.com/yinan-c/RSSbrew) | 277 | 规则过滤（正则/AND/OR/NOT）+ AI 摘要 |
| [newsscore](https://github.com/themaximalist/newsscore) | — | AI 标题+正文综合评分 + 标题重写 |
| [news-aggregator](https://github.com/tony-stark-eth/news-aggregator) | — | AI 情感评分 + 规则降级双保险 |
| [social-ranking](https://github.com/haphan/social-ranking) | — | Reddit/HN 热度公式简洁实现 |
| [curator-ai](https://github.com/marmelab/curator-ai) | — | 基于用户兴趣的文章选择 |

---

## 对本项目的改进建议

**评分层（scoring.py）：** 双信号融合
1. **LLM 评分**（参考 Horizon）：调用文本 provider 打 0-10 分，关注新闻价值/时效性/影响力
2. **数据信号**（参考 quality-news）：从 HN/Reddit 等平台获取互动数据，计算 upvoteRate
3. 加权合并：`final_score = 0.6 * llm_score + 0.4 * normalize(upvote_rate)`

**去重层（dedup.py）：** 升级为内容级去重
1. URL 归一化精确去重（现有）
2. MinHash 近似去重（新增，参考 text-dedup），阈值 0.7
3. 中文适配：用 jieba 分词后按词级别计算 n-gram

**降级策略**（参考 news-aggregator）：
- AI 评分不可用时，自动切换为关键词规则评分
- 保证管线不因 API 故障中断
