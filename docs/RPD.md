# 新闻视频自动化工作流 — 需求产品设计文档 (RPD)

## 1. 产品定位

一套从新闻资讯采集到短视频自动发布的全链路自动化系统。支持全自动定时运行和半自动人工审核两种模式，可处理单条新闻或批量合集，最终输出带配音的短视频并分发到多平台。

## 2. 用户角色

| 角色 | 说明 |
|------|------|
| 运营者 | 配置新闻源、设定抓取参数、审核内容、监控任务状态、手动干预 |
| 系统 | 自动执行 pipeline、定时抓取、定时发布 |

## 3. 核心流程

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ 1.获取   │───▶│ 2.文案   │───▶│ 3.素材   │───▶│ 4.校验   │───▶│ 5.合成   │───▶│ 6.发布   │
│ 和处理   │    │ 和分镜   │    │ 生成     │    │ 和调整   │    │ 与输出   │    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                                     │                               │
                              ┌──────┴──────┐                ┌──────┴──────┐
                              │ Hyperframes  │                │ Hyperframes  │
                              │ 仅图片+音频  │                │ HTML→MP4    │
                              ├─────────────┤                ├─────────────┤
                              │ LTX 路线    │                │ LTX 路线    │
                              │ 图片→视频+音频│               │ FFmpeg 拼接  │
                              └─────────────┘                └─────────────┘
```

Stage 1-2 两条技术路线共用，Stage 3-5 按路线分叉，Stage 6 合流。

---

### Stage 1：获取和处理

**目标**：从多种来源获取新闻原文，去重、合规审查、评分筛选

**输入**：新闻源配置 + 抓取参数（时间范围、条数等）

**处理**：

1. **多源抓取**
   - RSS 订阅源解析（36氪、TechCrunch、MarkTechPost 等）
   - API 调用（Hacker News Firebase/Algolia API）
   - 网页抓取（Scrapling，支持反爬、动态渲染，用于机器之心等无 RSS 的源）

2. **时间范围过滤**
   - 支持 `1d / 3d / 7d / 15d / 1m`，默认 `7d`
   - 仅保留指定时间范围内的新闻

3. **去重**
   - 与历史期做对比（回溯范围独立配置，默认 `30d`）
   - 去重策略：标题相似度（编辑距离 / 余弦相似度）+ 正文指纹（SimHash）
   - 每一期生成概括记录，作为后续去重的基准

4. **合规审查**（以中国大陆法规为主）
   - AI 初筛：调用 TextProvider 对内容做合规评估
   - 关键词过滤：维护敏感词库，命中则标记为待人工审核
   - 全自动模式下自动排除高风险内容，半自动模式下标记供人工确认

5. **评分与筛选**
   - 评分公式：来源权重 × 时效性 × 与主题相关度
   - 自动分类打标签（科技、AI、财经、社会等）
   - 按评分排序，选取 top N 条（默认 5 条）

**输出**：`RawArticle[]` — 筛选后的新闻列表，含原文、来源、分类、评分、合规状态

**审核点（半自动模式）**：人工筛选/排除不合适的新闻，修改分类和标签

**信息源配置**：详见 [news-sources.md](./news-sources.md)

---

### Stage 2：文案和分镜

**目标**：将新闻原文转化为视频脚本（旁白文案 + 分镜 + 画面提示词）

**输入**：`RawArticle`（单条）或 `RawArticle[]`（合集模式）

**处理**：
- AI 提炼新闻要点，生成口语化旁白文案
- 按旁白自然段落切分为分镜（每个分镜 3-8 秒）
- 每个分镜生成：
  - `narration` — 旁白文本
  - `image_prompt` — 静态画面描述提示词（两条路线共用）
  - `motion_prompt` — 运动和镜头描述（LTX 路线专用，Hyperframes 路线忽略）
  - `duration_hint` — 建议时长
- 合集模式下自动生成开头/转场/结尾文案

**输出**：

```json
{
  "title": "视频标题",
  "description": "视频简介（用于发布）",
  "tags": ["AI", "科技", "新闻"],
  "scenes": [
    {
      "id": 1,
      "narration": "今天我们来看一条重磅消息...",
      "image_prompt": "一张现代科技风格的芯片特写图，蓝色调，背景模糊",
      "motion_prompt": "镜头缓慢推进，光线从芯片表面反射，粒子效果",
      "duration_hint": 5
    }
  ]
}
```

**审核点（半自动模式）**：人工修改旁白文案、画面提示词、调整分镜顺序

---

### Stage 3：素材生成

**目标**：根据分镜脚本生成图片（和视频片段）及语音素材

**输入**：分镜脚本 `Script`

**处理**：

**图片生成**（两条路线共用）：
- 根据每个分镜的 `image_prompt` 调用 ImageProvider
- 统一输出尺寸（适配目标平台：9:16 竖屏 / 16:9 横屏）
- 风格一致性控制（同一视频内保持统一视觉风格）
- 候选实现：gpt-image-2、Stable Diffusion、Flux

**视频片段生成**（仅 LTX 路线）：
- 将生成的静态图片 + `motion_prompt` 输入 LTX 2.3 Image-to-Video
- 每张图生成 3-8 秒动态视频片段
- 约束：宽高为 32 的倍数，帧数为 8n+1，最长 ~10 秒
- 需要 GPU（≥16GB VRAM）

**语音合成**（两条路线共用）：
- 将旁白文案调用 TTSProvider
- 支持选择音色、语速、情感
- 输出每段旁白的音频文件 + 实际时长信息
- 候选实现：Edge-TTS（免费、中文效果好）、CosyVoice、Azure TTS

**输出**：

| 路线 | 输出 |
|------|------|
| Hyperframes | `ImageAsset[]` + `AudioAsset[]` |
| LTX | `ImageAsset[]` + `VideoClip[]` + `AudioAsset[]` |

**审核点（半自动模式）**：预览图片/视频片段/试听语音，可单独重新生成

---

### Stage 4：校验和调整

**目标**：确保图片/视频片段、语音和字幕对齐，生成精确时间轴

**输入**：分镜脚本 + 素材资产（图片或视频片段 + 音频）

**处理**：

| 项目 | Hyperframes 路线 | LTX 路线 |
|------|-----------------|---------|
| 对齐目标 | 图片展示时长 vs 旁白音频时长 | 视频片段时长 vs 旁白音频时长 |
| 音频 > 画面 | 延长图片展示 / 拆分为多张图 | 循环视频片段尾部 / 加黑场过渡 |
| 音频 < 画面 | 加入留白停顿 / 缩短图片展示 | 截取视频片段 / 加速 |
| 字幕生成 | 从旁白文本生成 SRT/ASS | 同左 |

- 校验总时长是否符合目标平台限制
- 生成最终时间轴（timeline），精确到毫秒

**输出**：`Timeline` — 精确的时间轴配置，包含每个分镜的起止时间、素材引用、字幕时间码

**审核点（半自动模式）**：检查时间轴节奏，可微调分镜时长

---

### Stage 5：合成与输出

**目标**：将所有素材按时间轴合成最终视频

**输入**：`Timeline` + 素材资产

**处理**：

**Hyperframes 路线**：
- 根据 Timeline 生成 HTML 视频合成代码
- 图片 + CSS/GSAP 动态过渡效果（Ken Burns 平移缩放、淡入淡出、滑动等）
- HTML 文字层叠加字幕
- 叠加旁白音轨
- 可选：背景音乐（自动混音）、片头片尾模板（HTML 模板）
- Hyperframes 渲染输出 MP4
- 依赖：Node.js（Puppeteer 渲染）+ FFmpeg（编码）

**LTX 路线**：
- 按 Timeline 拼接视频片段
- FFmpeg 滤镜实现转场效果
- FFmpeg 烧录字幕或添加独立字幕轨
- 叠加旁白音轨
- 可选：背景音乐、片头片尾（预渲染视频片段拼接）
- FFmpeg 编码输出 MP4

**共通**：
- 自动生成视频封面（从关键帧截取或额外生成一张封面图）
- 支持多分辨率输出（适配不同发布平台）

**输出**：`output.mp4` + `thumbnail.jpg`（可配置多个分辨率版本）

**审核点（半自动模式）**：预览成片，确认后进入发布

---

### Stage 6：发布

**目标**：自动上传视频到目标平台

**输入**：视频文件 + 封面 + 发布元数据（标题、描述、标签）

**处理**：
- 按平台适配：标题长度、标签格式、封面尺寸、视频规格
- 通过各平台 API 或自动化工具上传
- 记录发布状态和链接

**目标平台及可行性**：

| 平台 | 接入方式 | 可行性 | MVP |
|------|---------|--------|-----|
| YouTube | Data API v3 | ✅ 成熟公开 API | ✅ 首选 |
| B站 | 开放平台 API | ✅ 有创作者 API | 二期 |
| TikTok | TikTok for Developers API | ⚠️ 需要审核 | 后续 |
| 抖音 | 抖音开放平台 | ⚠️ 需企业号/服务商资质 | 后续 |
| 快手 | 快手开放平台 | ⚠️ 需企业号资质 | 后续 |
| 小红书 | 无公开上传 API | ❌ 需浏览器自动化 | 后续 |
| Instagram Reels | Meta Graph API | ⚠️ 需审核 | 后续 |

**输出**：`PublishResult[]` — 各平台发布状态、链接

**审核点（半自动模式）**：确认发布参数后手动触发

---

## 4. 运行模式

### 全自动模式
- 定时任务（cron / 调度器）触发完整 pipeline
- 按预设规则自动筛选新闻、生成视频、发布
- 异常时通知运营者（邮件 / webhook）

### 半自动模式
- 手动或定时触发抓取
- 在关键节点暂停等待人工审核（通过 Web 管理面板）
- 审核通过后继续下一阶段

**审核点汇总**：

| 阶段 | 审核内容 | 全自动时行为 |
|------|---------|-------------|
| Stage 1 后 | 筛选新闻、排除不合适内容 | 按评分自动取 top N |
| Stage 2 后 | 修改旁白文案、调整画面提示词 | 跳过 |
| Stage 3 后 | 预览图片/视频片段/试听语音 | 跳过 |
| Stage 4 后 | 检查时间轴节奏 | 跳过 |
| Stage 5 后 | 预览成片 | 跳过 |
| Stage 6 前 | 确认发布参数 | 自动发布 |

### 单条 / 合集模式
- **单条模式**：一条新闻 → 一个独立短视频
- **合集模式**：多条新闻 → 一个"今日要闻"式合集视频，自动生成转场

## 5. 技术架构

### 5.1 系统架构

```
┌──────────────────────────────────────────────────────────┐
│                   Frontend (React)                        │
│         任务监控 · 内容审核 · 配置管理 · 预览              │
└──────────────────────┬───────────────────────────────────┘
                       │ REST API
┌──────────────────────▼───────────────────────────────────┐
│                  Backend (FastAPI)                         │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────────────┐ │
│  │ API 层  │  │ 调度层    │  │ Pipeline Engine          │ │
│  │ Routes  │  │ Celery   │  │ Stage 1→2→3→4→5→6       │ │
│  └─────────┘  └──────────┘  └──────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              Provider 抽象层                          │ │
│  │  CollectorProvider · TextProvider · ImageProvider     │ │
│  │  TTSProvider · VideoProvider · PublisherAdapter       │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────┬───────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌──────────┐  ┌───────────┐  ┌──────────┐
   │ SQLite/  │  │   Redis   │  │ 文件存储  │
   │ Postgres │  │  (队列)   │  │ (素材)   │
   └──────────┘  └───────────┘  └──────────┘
```

### 5.2 技术路线分叉

```
                    ┌─ Hyperframes 路线（MVP）─────────────────────────┐
                    │  Stage 3: ImageProvider 生成静态图片              │
配置选择             │  Stage 5: Hyperframes HTML→MP4 渲染              │
video_route:  ──────│  依赖: Node.js + Puppeteer + FFmpeg              │
 "hyperframes"      │  GPU: 不需要                                     │
 | "ltx"            │                                                   │
                    ├─ LTX 路线（二期）──────────────────────────────────┤
                    │  Stage 3: ImageProvider + LTX 2.3 Image-to-Video │
                    │  Stage 5: FFmpeg 拼接 + 编码                      │
                    │  依赖: FFmpeg + PyTorch + CUDA                    │
                    │  GPU: ≥16GB VRAM                                  │
                    └───────────────────────────────────────────────────┘
```

### 5.3 Provider 接口

| Provider 类型 | 接口签名 | 候选实现 |
|---------------|---------|---------|
| CollectorProvider | `collect(source, time_range) → RawArticle[]` | RSS 解析器、Hacker News API、Scrapling |
| TextProvider | `generate(prompt) → text` | Claude、OpenAI、通义千问 |
| ImageProvider | `generate(prompt, size) → image` | gpt-image-2、Stable Diffusion、Flux |
| TTSProvider | `synthesize(text, voice) → audio` | Edge-TTS、CosyVoice、Azure TTS |
| VideoClipProvider | `generate(image, prompt, duration) → video_clip` | LTX 2.3（仅 LTX 路线，Stage 3 用） |
| ComposerProvider | `compose(timeline, assets) → video` | Hyperframes（HTML 渲染）、FFmpegComposer（LTX 路线拼接） |
| PublisherAdapter | `publish(video, thumbnail, meta) → result` | YouTube API、B站 API 等 |

**Provider 职责划分**：
- **VideoClipProvider**（Stage 3）：单张图片 → 单个动态视频片段（仅 LTX 路线使用）
- **ComposerProvider**（Stage 5）：Timeline + 全部素材 → 最终成片（两条路线各有实现）
  - Hyperframes 实现：从 Timeline 生成 HTML 场景代码 → `npx hyperframes render` 渲染 MP4
  - FFmpeg 实现：按 Timeline 拼接视频片段 + 叠加音轨 → FFmpeg 编码 MP4

### 5.4 文件存储

```
data/
├── runs/                          # 按 pipeline 运行组织
│   └── {run_id}/
│       ├── articles/              # Stage 1 抓取的原始内容
│       │   └── summary.md         # 本期概括（用于去重基准）
│       ├── script.json            # Stage 2 分镜脚本
│       ├── assets/                # Stage 3 生成的素材
│       │   ├── scene_01_image.png
│       │   ├── scene_01_video.mp4 # LTX 路线才有
│       │   ├── scene_01_audio.mp3
│       │   └── ...
│       ├── timeline.json          # Stage 4 时间轴
│       ├── output.mp4             # Stage 5 最终视频
│       └── thumbnail.jpg          # 封面图
└── history/                       # 历史期概括（去重用）
    ├── 2026-05-26_run001.md
    └── ...
```

## 6. 数据模型（核心）

| 实体 | 关键字段 | 说明 |
|------|---------|------|
| NewsSource | url, type(rss/api/scrape), provider, category, language, priority, enabled, config_json | 新闻源配置 |
| PipelineRun | mode(auto/manual), video_route(hyperframes/ltx), status, current_stage, time_range, max_articles, started_at | 单次运行记录 |
| RawArticle | run_id, title, content, source_url, source_name, category, score, compliance_status, language | 抓取到的原始新闻 |
| Script | run_id, title, description, tags, scenes_json, mode(single/collection) | 分镜脚本 |
| Asset | script_id, scene_id, type(image/audio/video_clip), file_path, duration_ms, metadata_json | 生成的素材 |
| Timeline | script_id, timeline_json, total_duration_ms | 校验后的时间轴 |
| Video | timeline_id, file_path, thumbnail_path, resolution, format, file_size | 合成的视频 |
| PublishRecord | video_id, platform, status, url, published_at, error_message | 发布记录 |
| IssueSummary | run_id, summary_text, article_fingerprints, created_at | 每期概括（去重基准） |

状态流转：`pending → processing → review → done / failed`

## 7. 错误处理与重试

| 场景 | 策略 |
|------|------|
| AI 生成失败（API 超时/限流） | 指数退避重试，最多 3 次 |
| 单个分镜图片质量不佳 | 重新生成（换 seed），最多 2 次 |
| LTX 视频片段冻结/质量差 | 回退为静态图片 + 动效 |
| TTS 生成失败 | 重试，失败则标记该分镜为 failed |
| 单个分镜失败 | 跳过该分镜继续，最终视频标记为 partial |
| 发布平台 API 失败 | 重试 3 次后标记 failed，不阻塞其他平台 |
| Pipeline 任意阶段中断 | 从断点恢复，已完成的素材不重新生成 |

## 8. 非功能需求

- **可恢复**：pipeline 任意阶段失败后可从断点重跑，不重复已完成的工作
- **可观测**：每个 stage 的耗时、成功率、错误日志通过 Web 面板可见
- **可配置**：新闻源、AI provider、发布平台、视频风格模板、抓取参数均通过配置管理
- **安全**：API key 通过环境变量注入，不落库；发布凭证加密存储
- **合规**：内容经过合规审查后才进入视频生成流程

## 9. MVP 范围（第一期）

优先实现最小可用链路：

1. ✅ 单条新闻 → 单个视频（全自动 + 半自动模式）
2. ✅ 信息源：Hacker News API + RSS（MarkTechPost、TechCrunch、机器之心、36氪、量子位）
3. ✅ 文案生成：接入一个 TextProvider（Claude）
4. ✅ 图片生成：接入一个 ImageProvider（gpt-image-2）
5. ✅ TTS：Edge-TTS（免费、中文效果好）
6. ✅ 视频合成：Hyperframes 渲染（HTML→MP4）
7. ✅ 时间范围：支持 1d/3d/7d/15d/1m 配置
8. ✅ 去重：基于每期概括 md 的历史对比
9. ✅ Web 管理面板：任务监控、内容预览、审核操作、配置管理
10. ✅ 发布：YouTube（Data API v3）
11. ✅ 封面图自动生成

**暂不实现**：
- 合集模式（二期）
- LTX 2.3 视频生成路线（二期，接口预留）
- 多平台发布（二期：B站、TikTok）
- 背景音乐、片头片尾模板（二期）
- x.com / Reddit / YouTube 抓取（需付费 API）
- Lambda 分布式渲染（二期）

## 10. 参考文档

- [信息源配置参考](./news-sources.md) — 信息源列表、API 详情、配置数据结构
- [Hyperframes API 参考](./Hyperframes-API-Reference.md) — CLI 命令、HTML 场景结构、动画模式、集成设计
- [LTX-2.3 API 参考](./LTX-2.3-API-Reference.md) — LTX 2.3 接口规范、代码示例、硬件要求
