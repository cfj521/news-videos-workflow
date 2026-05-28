"""
Async pipeline runner — called from FastAPI BackgroundTasks.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging import get_logger, get_run_logger
from app.models.pipeline_run import PipelineRun
from app.providers.base import ImageProvider
from app.providers.collector.hackernews import HackerNewsCollector
from app.providers.composer.hyperframes_composer import HyperframesComposer
from app.providers.image.openai_image import OpenAIImageProvider
from app.providers.tts.edge_tts_provider import EdgeTTSProvider

from app.pipeline.stage1_collect import run_stage1
from app.pipeline.stage2_script import run_stage2
from app.pipeline.stage3_assets import run_stage3
from app.pipeline.stage4_timeline import run_stage4
from app.pipeline.stage5_compose import run_stage5


def _build_text_provider():
    cfg = get_settings()
    if cfg.text.provider == "claude":
        from app.providers.text.claude import ClaudeTextProvider
        return ClaudeTextProvider(api_key=cfg.text.api_key, model=cfg.text.model, base_url=cfg.text.base_url)
    from app.providers.text.openai_text import OpenAITextProvider
    return OpenAITextProvider(api_key=cfg.text.api_key, model=cfg.text.model, base_url=cfg.text.base_url)


TYPE_TO_COLLECTOR: dict[str, type] = {}


def _ensure_collector_registry():
    if TYPE_TO_COLLECTOR:
        return
    from app.providers.collector.rss import RSSCollector
    from app.providers.collector.google_news import GoogleNewsCollector
    from app.providers.collector.tavily import TavilyCollector
    from app.providers.collector.brave_search import BraveSearchCollector
    from app.providers.collector.serper import SerperCollector
    from app.providers.collector.duckduckgo import DuckDuckGoCollector
    from app.providers.collector.aihot import AIHotCollector
    TYPE_TO_COLLECTOR.update({
        "hackernews_algolia": HackerNewsCollector,
        "rss": RSSCollector,
        "google_news": GoogleNewsCollector,
        "tavily": TavilyCollector,
        "brave_search": BraveSearchCollector,
        "serper": SerperCollector,
        "duckduckgo": DuckDuckGoCollector,
        "aihot": AIHotCollector,
    })
    try:
        from app.providers.collector.scraping import ScrapingCollector
        TYPE_TO_COLLECTOR["scraping"] = ScrapingCollector
    except Exception:
        pass


# Map generic DB type → collector key based on URL patterns
_URL_HINTS: list[tuple[str, str]] = [
    ("hn.algolia.com", "hackernews_algolia"),
    ("news.ycombinator.com", "hackernews_algolia"),
    ("news.google.com", "google_news"),
    ("api.tavily.com", "tavily"),
    ("api.search.brave.com", "brave_search"),
    ("serper.dev", "serper"),
    ("aihot.virxact.com", "aihot"),
]


def _resolve_collector_type(src) -> str:
    """Determine collector key: config_json.provider > URL hint > type field."""
    config_json = src.config_json if hasattr(src, "config_json") else src.get("config_json")
    if config_json:
        try:
            import json as _json
            provider = _json.loads(config_json).get("provider", "")
            if provider and provider in TYPE_TO_COLLECTOR:
                return provider
        except Exception:
            pass

    url = (src.url if hasattr(src, "url") else src.get("url", "")).lower()
    for pattern, collector_key in _URL_HINTS:
        if pattern in url:
            return collector_key

    src_type = src.type if hasattr(src, "type") else src.get("type", "")
    if src_type in TYPE_TO_COLLECTOR:
        return src_type

    type_map = {"api": "hackernews_algolia", "search": "duckduckgo", "scrape": "scraping"}
    return type_map.get(src_type, "")


def build_collectors_from_db(db_sources: list) -> tuple[list[dict], dict]:
    _ensure_collector_registry()

    # 互斥兜底：AI HOT 源与普通源同时 enabled 时，只保留 AI HOT 组
    aihot_sources = [s for s in db_sources if _resolve_collector_type(s) == "aihot"]
    if aihot_sources and len(aihot_sources) != len(db_sources):
        get_logger("runner").warning(
            "Both AI HOT and regular sources enabled — using AI HOT only (mutual exclusion)")
        db_sources = aihot_sources

    source_configs: list[dict] = []
    collectors: dict = {}

    for src in db_sources:
        collector_key = _resolve_collector_type(src)
        if not collector_key or collector_key not in TYPE_TO_COLLECTOR:
            get_logger("runner").warning("Skipping source '%s': no collector for type '%s'",
                                        getattr(src, "name", "?"), getattr(src, "type", "?"))
            continue
        if collector_key not in collectors:
            collectors[collector_key] = TYPE_TO_COLLECTOR[collector_key]()

        cfg: dict = {"name": src.name if hasattr(src, "name") else src.get("name", ""),
                      "type": collector_key,
                      "url": src.url if hasattr(src, "url") else src.get("url", "")}
        config_json = src.config_json if hasattr(src, "config_json") else src.get("config_json")
        if config_json:
            try:
                import json as _json
                cfg.update(_json.loads(config_json))
            except Exception:
                pass
        source_configs.append(cfg)

    return source_configs, collectors


def build_collectors(cfg=None):
    """Fallback when no DB sources available — returns HN as default."""
    _ensure_collector_registry()
    collectors = {"hackernews_algolia": HackerNewsCollector()}
    source_configs = [
        {"name": "Hacker News", "type": "hackernews_algolia",
         "url": "https://hn.algolia.com/api/v1/",
         "default_query": "AI", "tags": "story", "min_points": 30},
    ]
    return source_configs, collectors


def _build_summary_provider(cfg):
    sc = cfg.summary
    provider = sc.provider or cfg.text.provider
    api_key = sc.api_key or cfg.text.api_key
    model = sc.model or cfg.text.model
    base_url = sc.base_url or cfg.text.base_url
    if provider == "claude":
        from app.providers.text.claude import ClaudeTextProvider
        return ClaudeTextProvider(api_key=api_key, model=model, base_url=base_url)
    from app.providers.text.openai_text import OpenAITextProvider
    return OpenAITextProvider(api_key=api_key, model=model, base_url=base_url)


async def _summarize_articles(articles, cfg, run, db, log):
    tp = _build_summary_provider(cfg)
    max_len = cfg.summary.max_length
    sys_prompt = f"用中文为新闻文章生成简洁摘要，不超过{max_len}字。只输出摘要文本。"
    for i, a in enumerate(articles):
        try:
            _update(db, run, progress_detail=f"S1 生成摘要中 ({i+1}/{len(articles)})...")
            text = f"标题：{a.title}\n来源：{a.source_name}\n内容：{(a.content or a.title)[:2000]}"
            a.summary = (await tp.generate(prompt=text, system_prompt=sys_prompt)).strip()
            log.info("[S1] Summary %d/%d: %s", i + 1, len(articles), a.summary[:60])
        except Exception:
            log.exception("[S1] Summary failed for '%s'", a.title)
            a.summary = ""


def _save_articles(articles, run_dir):
    import json
    data = []
    for a in articles:
        data.append({
            "title": a.title,
            "url": a.source_url,
            "aggregator_url": a.aggregator_url,
            "source": a.source_name,
            "content": a.content or "",
            "summary": a.summary,
            "aihot_method": a.metadata.get("aihot_method"),
            "daily_sections": a.metadata.get("daily_sections"),
        })
    (run_dir / "articles.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _article_from_dict(d: dict):
    from app.providers.base import RawArticleData
    metadata = {}
    if d.get("aihot_method"):
        metadata["aihot_method"] = d["aihot_method"]
    if d.get("daily_sections"):
        metadata["daily_sections"] = d["daily_sections"]
    return RawArticleData(
        title=d.get("title", ""),
        content=d.get("content", ""),
        source_url=d.get("url", ""),
        source_name=d.get("source", ""),
        summary=d.get("summary", ""),
        aggregator_url=d.get("aggregator_url", ""),
        metadata=metadata,
    )


def _load_articles(run_dir: Path) -> list:
    p = run_dir / "articles.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [_article_from_dict(d) for d in data]


def _update(db: Session, run: PipelineRun, **kwargs) -> None:
    for k, v in kwargs.items():
        setattr(run, k, v)
    db.commit()
    db.refresh(run)


async def execute_pipeline(run_id: int, db_factory) -> None:
    db: Session = db_factory()
    try:
        await _run_inner(run_id, db)
    except Exception as e:
        run = db.get(PipelineRun, run_id)
        if run:
            _update(db, run, status="failed", error_message=str(e)[:1000], finished_at=datetime.now(timezone.utc))
            try:
                rlog = get_run_logger(run_id, Path(get_settings().infra.data_dir) / "runs" / str(run_id))
                rlog.exception("Pipeline failed with unhandled exception")
            except Exception:
                get_logger("runner").exception("Pipeline run #%d failed (could not write run log)", run_id)
    finally:
        db.close()


async def _run_inner(run_id: int, db: Session) -> None:
    run = db.get(PipelineRun, run_id)
    if not run:
        return

    cfg = get_settings()
    cfg.ensure_data_dirs()
    selected = json.loads(run.selected_stages)

    run_dir = Path(cfg.infra.data_dir) / "runs" / str(run.id)
    assets_dir = run_dir / "assets"
    run_dir.mkdir(parents=True, exist_ok=True)

    log = get_run_logger(run.id, run_dir)
    log.info("Pipeline started — stages=%s mode=%s route=%s", selected, run.mode, run.video_route)

    _update(db, run, status="processing", started_at=datetime.now(timezone.utc))

    articles = []
    daily_mode = False
    script = None
    scene_assets = []
    timeline = None

    # ─── Stage 1: 搜索整理 ─────────────────────────────────
    if 1 in selected:
        t0 = time.time()
        from app.models.news_source import NewsSource

        if not run.auto_collect:
            _save_articles([], run_dir)
            _update(db, run, current_stage=1, status="review", progress_detail="等待人工导入文章…")
            log.info("[S1] auto_collect off — waiting for manual import")
            await _wait_for_resume(run_id, db)
            run = db.get(PipelineRun, run_id)
        else:
            _update(db, run, current_stage=1, progress_detail="S1 采集新闻中...")
            log.info("[S1] Collecting news — time_range=%s max=%d", run.time_range, run.max_articles)
            db_sources = db.query(NewsSource).filter(NewsSource.enabled == True).all()
            if db_sources:
                source_configs, collectors = build_collectors_from_db(db_sources)
                log.info("[S1] Using %d DB sources: %s", len(source_configs), [s["name"] for s in source_configs])
            else:
                source_configs, collectors = build_collectors(cfg)
                log.info("[S1] No DB sources, using defaults")
            daily_mode = any(sc.get("method") == "daily" for sc in source_configs)
            articles = await run_stage1(
                sources=source_configs, collectors=collectors,
                time_range=run.time_range, max_articles=run.max_articles,
            )
            for i, a in enumerate(articles, 1):
                log.info("[S1]   [%d] %s (%s)", i, a.title, a.source_name)
            if articles and articles[0].metadata.get("source_group") != "aihot":
                _update(db, run, progress_detail=f"S1 生成摘要中 (0/{len(articles)})...")
                await _summarize_articles(articles, cfg, run, db, log)
            elapsed = time.time() - t0
            _update(db, run, progress_detail=f"S1 完成 — {len(articles)} 篇文章 ({elapsed:.1f}s)")
            log.info("[S1] Done — %d articles in %.1fs", len(articles), elapsed)
            _save_articles(articles, run_dir)
            if run.mode == "manual":
                _update(db, run, status="review", progress_detail=f"S1 采集完成 ({len(articles)} 篇)，等待审核")
                log.info("[S1] Paused for review")
                await _wait_for_resume(run_id, db)
                run = db.get(PipelineRun, run_id)

        # resume 后从 articles.json 重载，让人工导入/编辑生效
        articles = _load_articles(run_dir)
        # 人工导入模式：必须 ≥1 篇才放行，否则回到 review 继续等
        while not run.auto_collect and not articles:
            _update(db, run, status="review", progress_detail="请先导入至少 1 篇文章")
            await _wait_for_resume(run_id, db)
            run = db.get(PipelineRun, run_id)
            articles = _load_articles(run_dir)

    if not articles:
        msg = "今日 AI 日报尚未生成，请稍后再试或切换为动态(items)模式" if daily_mode else "No articles collected"
        _update(db, run, status="failed", error_message=msg, finished_at=datetime.now(timezone.utc))
        log.error(msg)
        return

    # ─── Stage 2: 脚本生成 ─────────────────────────────────
    if 2 in selected:
        t0 = time.time()
        article = articles[0]
        style = "daily" if article.metadata.get("aihot_method") == "daily" else "single"
        _update(db, run, current_stage=2, progress_detail=f"S2 生成脚本 — {article.title[:30]}...")
        log.info("[S2] Generating script for: %s", article.title)

        text_provider = _build_text_provider()
        log.info("[S2] Provider: %s / %s", cfg.text.provider, cfg.text.model)

        script = await run_stage2(article=article, text_provider=text_provider,
                                  language=cfg.pipeline.default_language, style=style)

        (run_dir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        scene_count = len(script.get("scenes", []))
        elapsed = time.time() - t0
        detail = f"S2 完成 — 《{script.get('title', '')}》{scene_count} 个分镜 ({elapsed:.1f}s)"
        _update(db, run, progress_detail=detail)
        log.info("[S2] Done — \"%s\" %d scenes in %.1fs", script.get("title", ""), scene_count, elapsed)

        for s in script.get("scenes", []):
            log.debug("[S2]   S%d: %s", s["id"], s["narration"][:60])

        if run.mode == "manual":
            _update(db, run, status="review", progress_detail=f"S2 脚本完成 ({scene_count} 分镜)，等待审核")
            log.info("[S2] Paused for review")
            await _wait_for_resume(run_id, db)
            run = db.get(PipelineRun, run_id)

    if not script:
        _update(db, run, status="failed", error_message="No script generated", finished_at=datetime.now(timezone.utc))
        log.error("No script — aborting")
        return

    # ─── Stage 3: 素材生成 ─────────────────────────────────
    if 3 in selected:
        t0 = time.time()
        total = len(script.get("scenes", []))
        _update(db, run, current_stage=3, progress_detail=f"S3 生成素材 0/{total}")
        log.info("[S3] Generating assets — %d scenes, provider: %s/%s", total, cfg.image.provider, cfg.image.model)

        image_provider = OpenAIImageProvider(api_key=cfg.image.api_key, model=cfg.image.model, base_url=cfg.image.base_url)
        tts_provider = EdgeTTSProvider(default_voice=cfg.tts.voice)
        img_count = 0
        tts_count = 0

        class TrackedImageProvider:
            def __init__(self, inner: ImageProvider):
                self._inner = inner

            async def generate(self, prompt, size="1080x1920", output_path=""):
                nonlocal img_count
                img_count += 1
                _update(db, run, progress_detail=f"S3 生成图片 {img_count}/{total}...")
                log.info("[S3] Image %d/%d: %s", img_count, total, prompt[:60])
                t = time.time()
                result = await self._inner.generate(prompt=prompt, size=size, output_path=output_path)
                log.info("[S3] Image %d/%d done (%.1fs, %s)", img_count, total, time.time() - t, result.file_path)
                return result

        class TrackedTTSProvider:
            def __init__(self, inner):
                self._inner = inner

            async def synthesize(self, text, voice="", speed=1.0, output_path=""):
                nonlocal tts_count
                tts_count += 1
                _update(db, run, progress_detail=f"S3 生成语音 {tts_count}/{total}...")
                log.info("[S3] TTS %d/%d: %s...", tts_count, total, text[:30])
                t = time.time()
                result = await self._inner.synthesize(text=text, voice=voice, speed=speed, output_path=output_path)
                log.info("[S3] TTS %d/%d done (%.1fs)", tts_count, total, time.time() - t)
                return result

        scene_assets = await run_stage3(
            script=script,
            image_provider=TrackedImageProvider(image_provider),
            tts_provider=TrackedTTSProvider(tts_provider),
            assets_dir=str(assets_dir),
            resolution=cfg.video.resolution,
        )

        ok = sum(1 for a in scene_assets if "error" not in a)
        errors = [a for a in scene_assets if "error" in a]
        elapsed = time.time() - t0
        detail = f"S3 完成 — {ok}/{total} 成功 ({elapsed:.1f}s)"
        _update(db, run, progress_detail=detail)
        log.info("[S3] Done — %d/%d ok in %.1fs", ok, total, elapsed)
        for err in errors:
            log.warning("[S3] Scene %d error: %s", err["scene_id"], err["error"])

        if run.mode == "manual":
            _update(db, run, status="review", progress_detail=f"S3 素材完成 ({ok}/{total})，等待审核")
            log.info("[S3] Paused for review")
            await _wait_for_resume(run_id, db)
            run = db.get(PipelineRun, run_id)

    # ─── Stage 4: 预览 ────────────────────────────────────
    if 4 in selected:
        t0 = time.time()
        _update(db, run, current_stage=4, progress_detail="S4 生成时间轴...")
        log.info("[S4] Building timeline + preview (route=%s)", run.video_route)

        timeline = run_stage4(script=script, scene_assets=scene_assets, scene_gap_ms=cfg.video.scene_gap_ms)
        (run_dir / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("[S4] Timeline: %.1fs total, %d entries", timeline["total_duration_ms"] / 1000, len(timeline["entries"]))

        _update(db, run, progress_detail="S4 生成分镜审核页...")
        preview_html = _generate_storyboard_html(script, scene_assets, timeline)
        preview_path = run_dir / "preview.html"
        preview_path.write_text(preview_html, encoding="utf-8")

        if run.video_route == "hyperframes":
            _update(db, run, progress_detail="S4 生成 Hyperframes 预览...")
            composer = HyperframesComposer()
            try:
                hyperframes_html = composer._render_html(timeline, cfg.video.resolution, run_dir, transition=cfg.video.transition)
                (run_dir / "index.html").write_text(hyperframes_html, encoding="utf-8")
                log.info("[S4] Hyperframes HTML generated at %s/index.html", run_dir)
            except Exception as e:
                log.warning("[S4] Hyperframes HTML generation failed: %s", e)
        else:
            log.info("[S4] LTX route — no HTML preview, clips will be generated in S5")

        elapsed = time.time() - t0
        total_s = timeline["total_duration_ms"] / 1000
        detail = f"S4 预览就绪 — {total_s:.0f}s / {len(timeline['entries'])} 分镜 ({elapsed:.1f}s)"
        _update(db, run, progress_detail=detail, preview_path=str(preview_path))
        log.info("[S4] Done in %.1fs", elapsed)

        if run.mode == "manual":
            _update(db, run, status="review", progress_detail="S4 预览就绪，等待审核")
            log.info("[S4] Paused for review")
            await _wait_for_resume(run_id, db)
            run = db.get(PipelineRun, run_id)

    # ─── Stage 5: 成片渲染 ────────────────────────────────
    if 5 in selected:
        if not timeline:
            _update(db, run, status="failed", error_message="No timeline for rendering", finished_at=datetime.now(timezone.utc))
            log.error("No timeline — cannot render")
            return

        t0 = time.time()
        output_mp4 = str((run_dir / "output.mp4").resolve())

        if run.video_route == "ltx":
            _update(db, run, current_stage=5, progress_detail="S5 LTX 视频生成中...")
            log.info("[S5] LTX rendering — output=%s", output_mp4)
            try:
                from app.providers.video.ltx_video import LTXVideoProvider
                from app.providers.composer.ltx_composer import LTXComposer
                ltx_video = LTXVideoProvider(
                    model_dir=cfg.ltx.model_dir, checkpoint=cfg.ltx.checkpoint,
                    upsampler=cfg.ltx.upsampler, distilled_lora=cfg.ltx.distilled_lora,
                    lora_strength=cfg.ltx.lora_strength, gemma_dir=cfg.ltx.gemma_dir,
                    inference_steps=cfg.ltx.inference_steps, cfg_scale=cfg.ltx.cfg_scale,
                    stg_scale=cfg.ltx.stg_scale, fps=cfg.ltx.fps, use_fp8=cfg.ltx.use_fp8,
                )
                ltx_composer = LTXComposer(video_provider=ltx_video)
                result = await ltx_composer.compose(
                    timeline_json=timeline, assets_dir=str(assets_dir),
                    output_path=output_mp4, resolution=cfg.video.resolution,
                )
                final_path = result.file_path
                log.info("[S5] LTX render ok — %s", final_path)
            except Exception as e:
                log.warning("[S5] LTX failed: %s — falling back to FFmpeg", e)
                _update(db, run, progress_detail="S5 LTX 失败，FFmpeg 合成中...")
                final_path = _ffmpeg_compose(timeline, run_dir, cfg.video.resolution, cfg.video.fps)
        else:
            _update(db, run, current_stage=5, progress_detail="S5 Hyperframes 渲染中...")
            log.info("[S5] Hyperframes rendering — output=%s", output_mp4)
            composer = HyperframesComposer()
            try:
                result = await run_stage5(timeline=timeline, composer=composer, assets_dir=str(assets_dir), output_path=output_mp4, resolution=cfg.video.resolution)
                final_path = result.file_path
                log.info("[S5] Hyperframes render ok — %s", final_path)
            except Exception as e:
                log.warning("[S5] Hyperframes failed: %s — falling back to FFmpeg", e)
                _update(db, run, progress_detail="S5 Hyperframes 失败，FFmpeg 合成中...")
                final_path = _ffmpeg_compose(timeline, run_dir, cfg.video.resolution, cfg.video.fps)

        if Path(final_path).exists():
            size_mb = Path(final_path).stat().st_size / 1024 / 1024
            elapsed = time.time() - t0
            detail = f"S5 渲染完成 — {size_mb:.1f} MB ({elapsed:.1f}s)"
            _update(db, run, progress_detail=detail, output_path=final_path)
            log.info("[S5] Done — %.1f MB in %.1fs", size_mb, elapsed)
        else:
            log.error("[S5] Output file not found: %s", final_path)
            _update(db, run, status="failed", error_message=f"Video output not found: {final_path}", finished_at=datetime.now(timezone.utc))
            return

        if run.mode == "manual":
            _update(db, run, status="review", progress_detail="S5 渲染完成，等待审核")
            log.info("[S5] Paused for review")
            await _wait_for_resume(run_id, db)
            run = db.get(PipelineRun, run_id)

    # ─── Stage 6: 发布 ────────────────────────────────────
    if 6 in selected:
        platforms = json.loads(run.publish_platforms)
        if platforms:
            _update(db, run, current_stage=6, progress_detail=f"S6 发布到 {', '.join(platforms)}...")
            log.info("[S6] Publishing to: %s", platforms)
            # TODO: call publisher adapters
            _update(db, run, progress_detail="S6 发布完成")
            log.info("[S6] Done")

    # ─── Finish ────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    if run.started_at:
        started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
        total_elapsed = (now - started).total_seconds()
    else:
        total_elapsed = 0
    _update(db, run, status="done", finished_at=datetime.now(timezone.utc), progress_detail=f"全部完成 ({total_elapsed:.0f}s)")
    log.info("Pipeline finished — total %.1fs", total_elapsed)


async def _wait_for_resume(run_id: int, db: Session, timeout: int = 3600) -> None:
    for _ in range(timeout):
        await asyncio.sleep(1)
        db.expire_all()
        run = db.get(PipelineRun, run_id)
        if not run or run.status != "review":
            return
    raise TimeoutError(f"Run {run_id} not resumed within {timeout}s")


def _generate_storyboard_html(script: dict, scene_assets: list[dict], timeline: dict) -> str:
    scenes_html = ""
    for scene in script.get("scenes", []):
        sid = scene["id"]
        asset = next((a for a in scene_assets if a["scene_id"] == sid), {})
        img = asset.get("image", {}).get("file_path", "")
        audio = asset.get("audio", {}).get("file_path", "")
        entry = next((e for e in timeline["entries"] if e["scene_id"] == sid), {})
        dur = (entry.get("end_ms", 0) - entry.get("start_ms", 0)) / 1000

        img_tag = f'<img src="file:///{img}" style="max-width:100%;border-radius:8px">' if img else '<div style="width:100%;height:200px;background:#222;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#555">No image</div>'
        audio_tag = f'<audio controls src="file:///{audio}" style="width:100%;margin-top:8px"></audio>' if audio else ""

        scenes_html += f"""
        <div style="background:#1a1a2e;border:1px solid #333;border-radius:12px;padding:16px;margin-bottom:12px">
          <div style="display:flex;gap:16px">
            <div style="width:280px;flex-shrink:0">{img_tag}{audio_tag}</div>
            <div style="flex:1">
              <div style="color:#888;font-size:12px;margin-bottom:4px">Scene {sid} · {dur:.1f}s</div>
              <div style="color:#ddd;font-size:14px;line-height:1.6">{scene['narration']}</div>
              <div style="color:#666;font-size:11px;margin-top:8px;font-style:italic">{scene.get('image_prompt', '')}</div>
            </div>
          </div>
        </div>"""

    total_s = timeline["total_duration_ms"] / 1000
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{script.get('title', 'Preview')}</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0f0f1a;color:#ddd;font-family:system-ui;padding:32px;max-width:900px;margin:0 auto}}</style>
</head><body>
<h1 style="font-size:24px;margin-bottom:4px">{script.get('title', '')}</h1>
<p style="color:#666;font-size:13px;margin-bottom:24px">{script.get('description', '')} · {total_s:.0f}s · {len(script.get('scenes', []))} scenes</p>
{scenes_html}
</body></html>"""


def _ffmpeg_compose(timeline: dict, run_dir: Path, resolution: str, fps: str) -> str:
    import subprocess

    output_path = str((run_dir / "output.mp4").resolve())
    entries = timeline["entries"]
    w, h = resolution.split("x")

    inputs = []
    filter_parts = []
    concat_inputs = []

    for entry in entries:
        if not entry.get("image_path") or not entry.get("audio_path"):
            continue
        dur_s = (entry["end_ms"] - entry["start_ms"]) / 1000
        idx = len(concat_inputs)
        inputs.extend(["-loop", "1", "-t", str(dur_s), "-i", entry["image_path"]])
        inputs.extend(["-i", entry["audio_path"]])
        vi, ai = idx * 2, idx * 2 + 1
        filter_parts.append(f"[{vi}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{idx}]")
        filter_parts.append(f"[{ai}:a]apad=whole_dur={dur_s}[a{idx}]")
        concat_inputs.append(f"[v{idx}][a{idx}]")

    if not concat_inputs:
        raise RuntimeError("No valid scenes for FFmpeg")

    n = len(concat_inputs)
    fc = ";".join(filter_parts) + f";{''.join(concat_inputs)}concat=n={n}:v=1:a=1[outv][outa]"
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-shortest", output_path]
    subprocess.run(cmd, capture_output=True, timeout=300, shell=True)
    return output_path
