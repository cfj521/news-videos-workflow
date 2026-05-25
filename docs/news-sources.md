# 信息源配置参考

> 2026-05-26 整理

---

## 1. 抓取时间范围

| 参数值 | 含义 | 典型场景 |
|--------|------|---------|
| `1d` | 最近 1 天 | 日更视频、突发新闻速报 |
| `3d` | 最近 3 天 | 常规更新节奏 |
| `7d` | 最近 7 天（默认） | 周报式合集 |
| `15d` | 最近 15 天 | 半月盘点 |
| `1m` | 最近 1 个月 | 月度回顾 |

```yaml
collector:
  time_range: "7d"       # 抓取范围
  max_articles: 5         # 最终选取条数
  dedup_lookback: "30d"   # 去重回溯范围
```

---

## 2. 接入方式分类

系统支持 4 种信息源接入方式，每种方式对应一个 CollectorProvider 适配器：

| 类型 | 说明 | 认证 | 时间过滤 |
|------|------|------|---------|
| `rss` | 标准 RSS/Atom Feed 解析 | 无需 | 按 `<pubDate>` 字段过滤 |
| `api` | 调用专用 API（HN、搜索服务等） | 视服务而定 | API 参数控制 |
| `search` | 搜索引擎 API（Brave、Tavily 等） | API Key | 搜索参数控制 |
| `scrape` | 网页抓取（Scrapling） | 无需 | 抓取后按页面日期过滤 |

---

## 3. RSS 源接入

### 3.1 RSS 标准协议

所有 RSS 源使用统一的解析器，无需认证，直接 HTTP GET 获取 XML。

**请求**：

```
GET https://www.marktechpost.com/feed/
Accept: application/rss+xml
```

**响应结构**（RSS 2.0）：

```xml
<rss version="2.0">
  <channel>
    <title>MarkTechPost</title>
    <link>https://www.marktechpost.com</link>
    <item>
      <title>文章标题</title>
      <link>https://www.marktechpost.com/2026/05/...</link>
      <description>文章摘要或全文...</description>
      <pubDate>Mon, 26 May 2026 08:00:00 +0000</pubDate>
      <category>AI</category>
      <dc:creator>作者名</dc:creator>
    </item>
    <!-- 更多 item -->
  </channel>
</rss>
```

**解析提取字段映射**：

| RSS 字段 | → RawArticle 字段 | 说明 |
|----------|-------------------|------|
| `<title>` | `title` | 标题 |
| `<link>` | `source_url` | 原文链接 |
| `<description>` | `content`（初步） | 可能是摘要，需判断是否全文 |
| `<pubDate>` | `published_at` | 发布时间，用于 time_range 过滤 |
| `<category>` | `category` | 分类（可能需要映射到我们的标签体系） |
| `<dc:creator>` | `author` | 作者 |

**全文获取策略**：RSS `<description>` 可能只是摘要。如需全文：
1. 检查 `<content:encoded>` 字段（部分 RSS 提供全文）
2. 若无全文，通过 `<link>` 二次抓取网页正文

**Python 实现依赖**：`feedparser` 库

```python
import feedparser

feed = feedparser.parse("https://www.marktechpost.com/feed/")
for entry in feed.entries:
    article = {
        "title": entry.title,
        "source_url": entry.link,
        "content": entry.get("content", [{}])[0].get("value", entry.summary),
        "published_at": entry.published_parsed,  # time.struct_time
        "author": entry.get("author", ""),
    }
```

### 3.2 所有 RSS 源清单

**国际（英文）**：

| 源 | Feed URL | 内容类型 | 说明 |
|----|---------|---------|------|
| MarkTechPost | `https://www.marktechpost.com/feed/` | 全文 | 最佳 AI RSS 源 |
| TechCrunch | `https://techcrunch.com/feed/` | 全文 | 无 paywall |
| OpenAI Blog | `https://openai.com/blog/rss.xml` | 摘要 | 需二次抓取全文 |
| Anthropic Blog | `https://www.anthropic.com/feed.xml` | 摘要 | 需二次抓取全文 |
| Hugging Face Blog | `https://huggingface.co/blog/feed.xml` | 全文 | 开源模型动态 |
| MIT Tech Review | `https://www.technologyreview.com/feed/` | 摘要 | 部分 paywall |
| The Gradient | `https://thegradient.pub/rss/` | 全文 | AI 深度评论 |
| arXiv cs.AI | `https://rss.arxiv.org/rss/cs.AI` | 摘要 | 论文速递 |
| Last Week in AI | `https://lastweekin.ai/feed` | 全文 | 周报汇总 |
| Ars Technica | `https://feeds.arstechnica.com/arstechnica/index` | 摘要 | 深度分析 |
| The Verge AI | `https://www.theverge.com/rss/ai-artificial-intelligence/index.xml` | 摘要 | 消费科技+AI |
| Wired | `https://www.wired.com/feed/rss` | 摘要 | 科技文化 |

**中国大陆（中文）**：

| 源 | Feed URL | 内容类型 | 说明 |
|----|---------|---------|------|
| 36氪 | `https://36kr.com/feed` | 全文 | 创投+科技 |
| 虎嗅 | `https://www.huxiu.com/rss/0.xml` | 摘要 | 科技商业 |
| InfoQ 中文 | `https://www.infoq.cn/feed` | 摘要 | 开发者向 |
| 少数派 | `https://sspai.com/feed` | 全文 | 效率工具 |
| IT之家 | `https://www.ithome.com/rss/` | 摘要 | 泛科技，速度快 |

---

## 4. API 源接入

### 4.1 Hacker News — Firebase 官方 API

```
基础 URL:  https://hacker-news.firebaseio.com/v0/
认证:      无需
Rate Limit: 无限制
协议:      REST + JSON，支持 SSE 实时流
```

**列表端点**（返回 ID 数组，最多 500 条）：

| 端点 | 说明 |
|------|------|
| `GET /topstories.json` | 热门帖子 |
| `GET /newstories.json` | 最新帖子 |
| `GET /beststories.json` | 最佳帖子 |
| `GET /askstories.json` | Ask HN（最多 200） |
| `GET /showstories.json` | Show HN（最多 200） |

**响应**：`[12345, 12346, 12347, ...]`

**详情端点**：

```
GET /item/{id}.json
```

**响应**：

```json
{
  "id": 12345,
  "type": "story",
  "by": "username",
  "time": 1716681600,
  "title": "Article Title",
  "url": "https://example.com/article",
  "score": 150,
  "descendants": 42,
  "kids": [12346, 12347]
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 唯一 ID |
| `type` | string | `story` / `comment` / `job` / `poll` |
| `by` | string | 作者用户名 |
| `time` | int | Unix 时间戳 |
| `title` | string | 标题 |
| `url` | string | 原文链接（自发帖无此字段） |
| `score` | int | 得分 |
| `descendants` | int | 评论总数 |
| `kids` | int[] | 直接回复的 ID 列表 |
| `text` | string | 帖子正文（自发帖/评论，HTML 格式） |
| `deleted` | bool | 是否已删 |
| `dead` | bool | 是否被标记 |

**时间过滤**：API 本身不支持时间过滤参数，需在客户端根据 `time` 字段过滤。

**集成流程**：
1. `GET /topstories.json` 获取 ID 列表
2. 批量 `GET /item/{id}.json` 获取详情（可并发）
3. 按 `time` 过滤 time_range
4. `url` 不为空的 story → 通过 Scrapling 抓取原文全文

### 4.2 Hacker News — Algolia 搜索 API

```
基础 URL:  https://hn.algolia.com/api/v1/
认证:      无需
Rate Limit: 宽松（无严格限制文档）
```

**端点**：

| 端点 | 说明 |
|------|------|
| `GET /search` | 按相关度排序 |
| `GET /search_by_date` | 按时间倒序 |

**查询参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `query` | string | 搜索关键词 |
| `tags` | string | 过滤标签，可组合：`story`, `comment`, `show_hn`, `ask_hn`, `front_page` |
| `numericFilters` | string | 数值过滤：`created_at_i>TIMESTAMP`, `points>100` |
| `page` | int | 分页页码（从 0 开始） |
| `hitsPerPage` | int | 每页条数（默认 20，最大 1000） |

**响应**：

```json
{
  "hits": [
    {
      "objectID": "12345",
      "title": "Article Title",
      "url": "https://example.com/article",
      "author": "username",
      "points": 150,
      "num_comments": 42,
      "created_at": "2026-05-26T08:00:00.000Z",
      "created_at_i": 1716681600,
      "story_text": null,
      "_tags": ["story", "front_page"]
    }
  ],
  "nbHits": 1000,
  "page": 0,
  "nbPages": 50,
  "hitsPerPage": 20
}
```

**时间过滤示例**：

```python
import time

# 最近 7 天
seven_days_ago = int(time.time()) - 7 * 86400
url = f"https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story&numericFilters=created_at_i>{seven_days_ago}&hitsPerPage=30"

# 高分 + 最近 3 天
three_days_ago = int(time.time()) - 3 * 86400
url = f"https://hn.algolia.com/api/v1/search?query=LLM&tags=story&numericFilters=created_at_i>{three_days_ago},points>50"
```

**建议**：MVP 优先用 Algolia API（自带搜索+时间过滤），Firebase API 作为备选（实时流场景）。

### 4.3 Google News RSS

```
基础 URL:  https://news.google.com/rss/
认证:      无需
Rate Limit: 每次最多 100 条，无官方文档限制
```

**URL 模式**：

| 类型 | URL | 说明 |
|------|-----|------|
| 热门头条 | `/rss?hl=zh-CN&gl=CN&ceid=CN:zh` | 中国中文头条 |
| 按主题 | `/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en` | 可用：TECHNOLOGY, SCIENCE, BUSINESS, WORLD, HEALTH |
| 关键词搜索 | `/rss/search?q=AI+artificial+intelligence&hl=en-US&gl=US&ceid=US:en` | 搜索新闻 |
| 按地区 | `/rss/headlines/section/geo/Beijing?hl=zh-CN&gl=CN&ceid=CN:zh` | 地区新闻 |

**搜索参数**（拼接在 `q=` 后）：

| 参数 | 示例 | 说明 |
|------|------|------|
| 关键词 | `q=AI` | 默认 AND 连接 |
| OR 组合 | `q=AI OR LLM` | 任一匹配 |
| 排除 | `q=AI -crypto` | 排除 crypto |
| 精确匹配 | `q="large language model"` | 完整词组 |
| 时间范围 | `q=AI when:7d` | 最近 N 天：`1d`,`3d`,`7d` / N 小时：`12h` / N 月：`1m` |
| 日期范围 | `q=AI after:2026-05-20 before:2026-05-27` | 精确日期 |
| 标题搜索 | `q=intitle:GPT` | 仅搜标题 |

**语言/地区代码**：

| 参数 | 中国中文 | 美国英文 | 说明 |
|------|---------|---------|------|
| `hl` | `zh-CN` | `en-US` | 界面语言 |
| `gl` | `CN` | `US` | 地区 |
| `ceid` | `CN:zh` | `US:en` | 国家:语言 |

**响应**：标准 RSS 2.0 XML，用 `feedparser` 解析即可。

---

## 5. 搜索服务接入

用于按关键词主动搜索新闻，补充 RSS 和 API 无法覆盖的内容。

### 5.1 Brave Search API

```
基础 URL:  https://api.search.brave.com/res/v1/
认证:      Header: X-Subscription-Token: <API_KEY>
注册:      https://api-dashboard.search.brave.com/
Rate Limit: 50 req/sec
免费额度:  $5/月信用额度（≈1000 次查询），需绑定信用卡
```

**新闻搜索端点**：

```
GET https://api.search.brave.com/res/v1/news/search
```

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `q` | string | ✅ | 搜索关键词 |
| `count` | int | | 结果数量（默认 20） |
| `offset` | int | | 分页偏移 |
| `freshness` | string | | 时效过滤：`pd`(24h), `pw`(7d), `pm`(30d), `py`(1y), 或 `YYYY-MM-DDtoYYYY-MM-DD` |
| `country` | string | | 国家代码（如 `US`, `CN`） |
| `search_lang` | string | | 搜索语言（如 `en`, `zh`） |
| `spellcheck` | int | | 拼写检查 `0`/`1` |

**请求示例**：

```python
import httpx

response = httpx.get(
    "https://api.search.brave.com/res/v1/news/search",
    headers={"X-Subscription-Token": "BSA..."},
    params={
        "q": "artificial intelligence",
        "count": 20,
        "freshness": "pw",        # 最近 7 天
        "search_lang": "en",
    }
)
```

**响应结构**：

```json
{
  "type": "news",
  "query": { "original": "artificial intelligence" },
  "results": [
    {
      "title": "Article Title",
      "url": "https://example.com/article",
      "description": "Article snippet...",
      "age": "2 hours ago",
      "meta_url": { "hostname": "example.com" },
      "thumbnail": { "src": "https://..." }
    }
  ]
}
```

**Web 搜索端点**（备选）：

```
GET https://api.search.brave.com/res/v1/web/search
```

参数相同，返回网页结果而非新闻结果。

**费用**：$5 / 1,000 次请求。

### 5.2 Tavily Search API

```
基础 URL:  https://api.tavily.com/
认证:      Bearer Token: tvly-YOUR_API_KEY
注册:      https://app.tavily.com（无需信用卡）
Rate Limit: 未公开严格限制
免费额度:  1,000 credits/月（basic search = 1 credit）
```

**搜索端点**：

```
POST https://api.tavily.com/search
Content-Type: application/json
Authorization: Bearer tvly-YOUR_API_KEY
```

**请求体**：

```json
{
  "query": "AI news today",
  "search_depth": "basic",
  "topic": "news",
  "time_range": "week",
  "max_results": 10,
  "include_answer": false,
  "include_raw_content": "markdown",
  "include_domains": [],
  "exclude_domains": []
}
```

**请求参数详解**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | string | （必填） | 搜索关键词 |
| `search_depth` | string | `"basic"` | `"basic"` (1 credit) / `"advanced"` (2 credits) |
| `topic` | string | `"general"` | `"general"` / `"news"`（新闻搜索时用 `"news"`） |
| `time_range` | string | null | `"day"` / `"week"` / `"month"` / `"year"` |
| `start_date` | string | null | 起始日期 `YYYY-MM-DD` |
| `end_date` | string | null | 结束日期 `YYYY-MM-DD` |
| `max_results` | int | 5 | 最大结果数 0-20 |
| `include_answer` | bool | false | 是否返回 AI 生成的摘要答案 |
| `include_raw_content` | string | false | `"markdown"` / `"text"` / `false`（是否返回正文） |
| `include_domains` | string[] | [] | 仅搜索指定域名（最多 300） |
| `exclude_domains` | string[] | [] | 排除指定域名（最多 150） |
| `country` | string | null | 按国家提升结果（仅 general topic） |

**响应结构**：

```json
{
  "query": "AI news today",
  "answer": null,
  "results": [
    {
      "title": "Article Title",
      "url": "https://example.com/article",
      "content": "Article snippet or full content...",
      "score": 0.95,
      "raw_content": "Full markdown content...",
      "published_date": "2026-05-26"
    }
  ],
  "response_time": 1.23
}
```

**Python SDK**：

```python
from tavily import TavilyClient

client = TavilyClient(api_key="tvly-YOUR_API_KEY")
response = client.search(
    query="latest AI breakthroughs",
    topic="news",
    time_range="week",
    max_results=10,
    include_raw_content="markdown",
)
for result in response["results"]:
    print(result["title"], result["url"])
```

**费用**：免费 1,000 credits/月，超出 $0.008/credit。

**优势**：专为 AI agent 设计，`include_raw_content` 可直接获取正文 markdown，无需二次抓取。`topic="news"` 专门优化新闻搜索。

### 5.3 Serper API（Google 搜索结果）

```
基础 URL:  https://google.serper.dev/
认证:      Header: X-API-KEY: <API_KEY>
注册:      https://serper.dev/
Rate Limit: 未公开
免费额度:  2,500 次查询（一次性，6 个月有效）
```

**新闻搜索端点**：

```
POST https://google.serper.dev/news
Content-Type: application/json
X-API-KEY: YOUR_API_KEY
```

**请求体**：

```json
{
  "q": "artificial intelligence",
  "gl": "us",
  "hl": "en",
  "num": 10,
  "tbs": "qdr:w"
}
```

**请求参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `q` | string | 搜索关键词 |
| `gl` | string | 地区代码（`us`, `cn`） |
| `hl` | string | 语言代码（`en`, `zh`） |
| `num` | int | 结果数量（最多 100） |
| `tbs` | string | 时间过滤：`qdr:h`(1h), `qdr:d`(24h), `qdr:w`(7d), `qdr:m`(30d) |
| `page` | int | 分页 |

**响应结构**：

```json
{
  "news": [
    {
      "title": "Article Title",
      "link": "https://example.com/article",
      "snippet": "Article snippet...",
      "date": "2 hours ago",
      "source": "TechCrunch",
      "imageUrl": "https://...",
      "position": 1
    }
  ]
}
```

**费用**：免费 2,500 次 → 之后 $1/1K（Developer）或 $0.10/1K（Pro $50/月）。

**优势**：本质是 Google 搜索结果的 JSON 封装，覆盖面最广。响应速度 <100ms。

### 5.4 DuckDuckGo（非官方方案）

```
状态: 无官方 API，依赖第三方封装
认证: 无需
Rate Limit: 不稳定，可能被限流
```

**可用方案**：

| 方案 | 说明 | 可靠性 |
|------|------|--------|
| `duckduckgo-search` Python 包 | 抓取 DuckDuckGo HTML 结果 | ⚠️ 可能被反爬 |
| DuckDuckGo MCP Server | Claude Code 可用，无需 API key | ⚠️ 依赖抓取 |
| SerpApi DuckDuckGo | 付费代理 | ✅ 稳定但收费 |

**Python 示例**（`duckduckgo-search` 包）：

```python
from duckduckgo_search import DDGS

with DDGS() as ddgs:
    results = ddgs.news(
        keywords="AI artificial intelligence",
        region="wt-wt",        # 全球
        safesearch="moderate",
        timelimit="w",         # 时间: d(天), w(周), m(月)
        max_results=20,
    )
    for r in results:
        print(r["title"], r["url"], r["date"])
```

**响应字段**：`title`, `url`, `body`, `date`, `source`, `image`

**MVP 建议**：不推荐作为主要源（不稳定），可作为免费备选。

---

## 6. 网页抓取（Scrapling）

用于没有 RSS/API 的源（如机器之心、量子位）和从 HN/搜索结果链接抓取全文。

```
工具:       Scrapling
认证:       无需（访问目标网站）
依赖:       Python 3.10+, pip install "scrapling[all]", scrapling install
反爬支持:   内置 Stealth 模式、动态渲染
```

**配置方式**：每个抓取源需要定义 CSS 选择器：

```yaml
scrape_sources:
  jiqizhixin:
    url: "https://www.jiqizhixin.com/"
    list_page:
      article_selector: ".article-item"    # 文章列表项
      title_selector: ".article-title a"
      link_selector: ".article-title a"
      date_selector: ".article-date"
    detail_page:
      content_selector: ".article-content"
      author_selector: ".author-name"
    pagination:
      next_page_selector: ".next-page a"
      max_pages: 3

  qbitai:
    url: "https://www.qbitai.com/"
    list_page:
      article_selector: ".post-item"
      title_selector: ".post-title a"
      link_selector: ".post-title a"
      date_selector: ".post-date"
    detail_page:
      content_selector: ".post-content"
```

**全文抓取流程**（用于 RSS 摘要源和搜索结果链接）：

```python
from scrapling import Fetcher

fetcher = Fetcher(auto_match=True)

page = fetcher.get("https://example.com/article")
title = page.css_first("h1").text()
content = page.css_first("article").text()
```

**需要 Scrapling 的源**：

| 源 | URL | 说明 |
|----|-----|------|
| 机器之心 | `https://www.jiqizhixin.com/` | 国内最专业 AI 媒体 |
| 量子位 | `https://www.qbitai.com/` | AI 深度报道 |
| 雷锋网 | `https://www.leiphone.com/` | AI + 硬件 |
| 极客公园 | `https://www.geekpark.net/` | 创新产品 |
| RSS 摘要全文 | 各 RSS 源的 `<link>` | 摘要型 RSS 需二次抓取 |
| 搜索结果全文 | 搜索 API 返回的 URL | 搜索只返回 snippet |

---

## 7. 认证汇总

| 源 / 服务 | 认证方式 | API Key 环境变量 | 免费额度 | 费用 |
|-----------|---------|-----------------|---------|------|
| Hacker News Firebase | 无需 | — | 无限 | 免费 |
| Hacker News Algolia | 无需 | — | 无限 | 免费 |
| Google News RSS | 无需 | — | 每次最多 100 条 | 免费 |
| 所有 RSS 源 | 无需 | — | 无限 | 免费 |
| Brave Search | Header `X-Subscription-Token` | `BRAVE_SEARCH_API_KEY` | ~1,000 次/月 | $5/1K 次 |
| Tavily | Bearer Token | `TAVILY_API_KEY` | 1,000 credits/月 | $0.008/credit |
| Serper | Header `X-API-KEY` | `SERPER_API_KEY` | 2,500 次（一次性） | $1/1K 次起 |
| DuckDuckGo | 无需 | — | 无限（非官方） | 免费 |
| Scrapling | 无需 | — | 无限 | 免费 |
| x.com (Twitter) | Bearer Token | `TWITTER_BEARER_TOKEN` | 极有限 | $200+/月 |
| Reddit | OAuth2 | `REDDIT_CLIENT_ID` + `REDDIT_SECRET` | 100 req/min | 免费（受限） |
| YouTube Data API | API Key | `YOUTUBE_API_KEY` | 10,000 units/天 | 免费额度内 |

---

## 8. 源配置数据结构

```yaml
sources:
  # --- RSS 源 ---
  - name: "MarkTechPost"
    type: "rss"
    url: "https://www.marktechpost.com/feed/"
    category: "ai"
    language: "en"
    priority: 1
    enabled: true
    config:
      full_text: true              # RSS 是否提供全文

  - name: "36氪"
    type: "rss"
    url: "https://36kr.com/feed"
    category: "tech"
    language: "zh"
    priority: 2
    enabled: true
    config:
      full_text: true

  # --- API 源 ---
  - name: "Hacker News"
    type: "api"
    url: "https://hn.algolia.com/api/v1/"
    category: "tech"
    language: "en"
    priority: 1
    enabled: true
    config:
      provider: "hackernews_algolia"
      endpoint: "search_by_date"
      default_query: "AI OR LLM OR GPT"
      tags: "story"
      max_items: 30
      min_points: 10              # 最低分数过滤
      fetch_full_text: true        # 是否通过 url 抓取全文

  - name: "Google News"
    type: "api"
    url: "https://news.google.com/rss/"
    category: "tech"
    language: "zh"
    priority: 3
    enabled: true
    config:
      provider: "google_news_rss"
      search_query: "AI 人工智能"
      hl: "zh-CN"
      gl: "CN"
      ceid: "CN:zh"

  # --- 搜索服务 ---
  - name: "Brave Search"
    type: "search"
    url: "https://api.search.brave.com/res/v1/news/search"
    category: "ai"
    language: "en"
    priority: 2
    enabled: true
    config:
      provider: "brave_search"
      api_key_env: "BRAVE_SEARCH_API_KEY"
      default_query: "artificial intelligence breakthroughs"
      freshness: "pw"             # 最近一周
      count: 20

  - name: "Tavily"
    type: "search"
    url: "https://api.tavily.com/search"
    category: "ai"
    language: "en"
    priority: 2
    enabled: true
    config:
      provider: "tavily"
      api_key_env: "TAVILY_API_KEY"
      default_query: "AI news breakthroughs"
      topic: "news"
      search_depth: "basic"
      time_range: "week"
      max_results: 10
      include_raw_content: "markdown"  # 直接获取正文

  - name: "Serper"
    type: "search"
    url: "https://google.serper.dev/news"
    category: "tech"
    language: "en"
    priority: 3
    enabled: false                 # 默认关闭，用户按需启用
    config:
      provider: "serper"
      api_key_env: "SERPER_API_KEY"
      default_query: "AI"
      gl: "us"
      tbs: "qdr:w"

  # --- 网页抓取 ---
  - name: "机器之心"
    type: "scrape"
    url: "https://www.jiqizhixin.com/"
    category: "ai"
    language: "zh"
    priority: 1
    enabled: true
    config:
      provider: "scrapling"
      list_page:
        article_selector: ".article-item"
        title_selector: ".article-title a"
        link_selector: ".article-title a"
        date_selector: ".article-date"
      detail_page:
        content_selector: ".article-content"
      max_pages: 3

  # --- 受限源（默认关闭） ---
  - name: "x.com"
    type: "api"
    url: "https://api.x.com/2/"
    category: "tech"
    language: "en"
    priority: 10
    enabled: false
    tier: "premium"
    config:
      provider: "twitter"
      api_key_env: "TWITTER_BEARER_TOKEN"
      search_query: "AI OR LLM lang:en"
```

---

## 9. MVP 默认源推荐

| 优先级 | 源 | 类型 | 语言 | 认证 | 理由 |
|--------|---|------|------|------|------|
| 1 | Hacker News (Algolia) | API | EN | 无需 | 免费无限制，自带搜索+时间过滤 |
| 2 | Tavily | Search | EN | API Key（免费） | 1,000 次/月免费，直接返回正文 markdown |
| 3 | Google News RSS | API | ZH+EN | 无需 | 免费，支持关键词+时间过滤 |
| 4 | MarkTechPost | RSS | EN | 无需 | 最佳 AI RSS，全文 |
| 5 | 36氪 | RSS | ZH | 无需 | 国内科技综合，全文 RSS |
| 6 | 机器之心 | Scrape | ZH | 无需 | 国内最权威 AI 媒体 |

**后续扩展**：Brave Search → TechCrunch RSS → 量子位 → Serper → OpenAI/Anthropic Blog

---

## 10. CollectorProvider 适配器设计

每种接入类型对应一个适配器，统一返回 `RawArticle[]`：

```python
class CollectorProvider(ABC):
    async def collect(
        self,
        source: NewsSource,
        time_range: str,          # "1d" / "3d" / "7d" / "15d" / "1m"
        max_items: int = 30,
    ) -> list[RawArticle]: ...

# 适配器实现
class RSSCollector(CollectorProvider): ...           # feedparser 解析
class HackerNewsCollector(CollectorProvider): ...     # Algolia/Firebase API
class GoogleNewsCollector(CollectorProvider): ...     # Google News RSS 解析
class BraveSearchCollector(CollectorProvider): ...    # Brave Search API
class TavilyCollector(CollectorProvider): ...         # Tavily Search API
class SerperCollector(CollectorProvider): ...         # Serper API
class DuckDuckGoCollector(CollectorProvider): ...     # duckduckgo-search 包
class ScraplingCollector(CollectorProvider): ...      # Scrapling 网页抓取

# 通用全文抓取（供摘要型源和搜索结果二次获取正文）
class FullTextFetcher:
    async def fetch(self, url: str) -> str: ...      # Scrapling 抓取正文
```
