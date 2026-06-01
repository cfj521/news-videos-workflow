import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from pydantic import BaseModel as _PydBase
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_session_factory
from app.services.document_import import import_file, import_url
from app.config import get_settings, reload_settings
from app.logging import get_logger
from app.models.pipeline_run import PipelineRun
from app.pipeline.engine import PipelineEngine
from app.pipeline.runner import execute_pipeline, build_collectors, build_collectors_from_db, _build_text_provider, _update, _article_from_dict, _humanize_error, export_final
from app.providers.tts.edge_tts_provider import EdgeTTSProvider
from app.schemas.pipeline import PipelineRunCreate, PipelineRunRead

log = get_logger("api.pipeline")
router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


def _run_dir(run_id: int) -> Path:
    return get_settings().runs_root() / str(run_id)


# 本后端进程的启动时刻。pipeline 跑在进程内的 BackgroundTasks 里，
# 进程重启后这些后台协程就消失了——凡是仍处于 processing 但发起时间早于本进程启动的任务，
# 其协程必然已不存在，可确定性地判为「中断失败」（不会误伤本进程内真正在跑的任务）。
_PROCESS_STARTED_AT = datetime.now(timezone.utc)


def _reap_orphan(run: PipelineRun, db: Session) -> PipelineRun:
    """惰性回收僵尸任务：读取任务时若发现它是上一个进程发起且仍 processing，自动判失败。"""
    if run.status == "processing" and run.started_at:
        started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
        if started < _PROCESS_STARTED_AT:
            run.status = "failed"
            run.error_message = "后端重启导致任务中断，请重新发起"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(run)
            log.warning("Reaped orphan run #%d (started %s < process %s) → failed", run.id, started, _PROCESS_STARTED_AT)
    return run


@router.post("/runs", response_model=PipelineRunRead, status_code=201)
def create_run(body: PipelineRunCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    log.info("POST /runs — mode=%s stages=%s platforms=%s", body.mode, body.selected_stages, body.publish_platforms)
    engine = PipelineEngine(db)
    run = engine.create_run(
        mode=body.mode, video_route=body.video_route, time_range=body.time_range,
        max_articles=body.max_articles, selected_stages=body.selected_stages,
        publish_platforms=body.publish_platforms,
        auto_collect=body.auto_collect,
        resolution=body.resolution, aspect_ratio=body.aspect_ratio,
    )
    session_factory = get_session_factory()
    background_tasks.add_task(_run_pipeline_bg, run.id, session_factory)
    log.info("Pipeline run #%d queued", run.id)
    return run


def _run_pipeline_bg(run_id: int, session_factory):
    asyncio.run(execute_pipeline(run_id, session_factory))


@router.get("/runs", response_model=list[PipelineRunRead])
def list_runs(limit: int = 20, offset: int = 0, db: Session = Depends(get_db)):
    runs = db.query(PipelineRun).order_by(PipelineRun.created_at.desc()).offset(offset).limit(limit).all()
    return [_reap_orphan(r, db) for r in runs]


@router.get("/runs/{run_id}", response_model=PipelineRunRead)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _reap_orphan(run, db)


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    log.info("POST /runs/%d/resume", run_id)
    engine = PipelineEngine(db)
    resumed = engine.resume_run(run_id)
    return {"status": "resumed", "run_id": resumed.id}


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status == "processing":
        raise HTTPException(status_code=409, detail="任务正在运行，无法删除")
    db.delete(run)
    db.commit()
    run_dir = _run_dir(run_id)
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    log.info("DELETE /runs/%d — removed DB record and %s", run_id, run_dir)
    return {"status": "deleted", "run_id": run_id}


# ─── Asset serving ────────────────────────────────────────

@router.get("/runs/{run_id}/assets/{filename:path}")
def get_asset(run_id: int, filename: str):
    path = _run_dir(run_id) / "assets" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Asset not found")
    mime = "image/png" if path.suffix == ".png" else "audio/mpeg" if path.suffix == ".mp3" else "application/octet-stream"
    return FileResponse(path, media_type=mime)


# ─── Stage data ───────────────────────────────────────────

@router.get("/runs/{run_id}/articles")
def get_articles(run_id: int):
    path = _run_dir(run_id) / "articles.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write_articles(run_id: int, items: list) -> None:
    rd = _run_dir(run_id)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "articles.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_articles(run_id: int) -> list:
    path = _run_dir(run_id) / "articles.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


@router.put("/runs/{run_id}/articles")
def put_articles(run_id: int, items: list[dict]):
    for it in items:
        if not (str(it.get("title", "")).strip() or str(it.get("content", "")).strip()):
            raise HTTPException(status_code=400, detail="每篇文章至少需要标题或正文")
    _write_articles(run_id, items)
    return items


class _ImportUrlBody(_PydBase):
    url: str


@router.post("/runs/{run_id}/articles/import/url")
async def import_article_url(run_id: int, body: _ImportUrlBody):
    try:
        art = await import_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"URL 导入失败: {e}")
    items = _read_articles(run_id)
    items.append(art)
    _write_articles(run_id, items)
    return items


@router.post("/runs/{run_id}/articles/import/file")
async def import_article_file(run_id: int, file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 20MB")
    cfg = get_settings()
    try:
        art = await import_file(data, file.filename or "", cfg.vision)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"解析失败: {e}")
    items = _read_articles(run_id)
    items.append(art)
    _write_articles(run_id, items)
    return items


@router.get("/runs/{run_id}/script")
def get_script(run_id: int):
    path = _run_dir(run_id) / "script.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Script not found")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/runs/{run_id}/timeline")
def get_timeline(run_id: int):
    path = _run_dir(run_id) / "timeline.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Timeline not found")
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("/runs/{run_id}/regen-script")
async def regen_script(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rd = _run_dir(run_id)
    articles_path = rd / "articles.json"
    if not articles_path.exists():
        raise HTTPException(status_code=400, detail="No articles")

    articles_raw = json.loads(articles_path.read_text(encoding="utf-8"))
    arts = [_article_from_dict(d) for d in articles_raw]

    cfg = get_settings()
    if cfg.text.provider == "claude":
        from app.providers.text.claude import ClaudeTextProvider
        tp = ClaudeTextProvider(api_key=cfg.text.api_key, model=cfg.text.model, base_url=cfg.text.base_url)
    else:
        from app.providers.text.openai_text import OpenAITextProvider
        tp = OpenAITextProvider(api_key=cfg.text.api_key, model=cfg.text.model, base_url=cfg.text.base_url)

    from app.pipeline.stage2_script import run_stage2_multi
    log.info("Regenerating multi-article script for run #%d (%d articles)", run_id, len(arts))
    script = await run_stage2_multi(arts, tp, language=cfg.pipeline.default_language)
    (rd / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    return script


# ─── Preview ──────────────────────────────────────────────

@router.get("/runs/{run_id}/preview")
def get_preview(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rd = _run_dir(run_id)
    script_path = rd / "script.json"
    timeline_path = rd / "timeline.json"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="Script not found")
    script = json.loads(script_path.read_text(encoding="utf-8"))
    timeline = json.loads(timeline_path.read_text(encoding="utf-8")) if timeline_path.exists() else None
    return _build_preview_html(run_id, script, timeline)


def _build_preview_html(run_id: int, script: dict, timeline: dict | None) -> HTMLResponse:
    scenes = script.get("scenes", [])
    entries_map = {}
    if timeline:
        for e in timeline.get("entries", []):
            entries_map[e["scene_id"]] = e

    api = f"/api/pipeline/runs/{run_id}"
    scenes_html = ""
    for scene in scenes:
        sid = scene["id"]
        entry = entries_map.get(sid, {})
        dur = (entry.get("end_ms", 0) - entry.get("start_ms", 0)) / 1000 if entry else 0
        img_src = f"{api}/assets/scene_{sid:02d}_image.png"
        audio_src = f"{api}/assets/scene_{sid:02d}_audio.mp3"
        narration = scene.get("narration", "").replace("&", "&amp;").replace("<", "&lt;")
        prompt = scene.get("image_prompt", "").replace("&", "&amp;").replace("<", "&lt;")

        scenes_html += f"""
        <div class="scene" data-scene-id="{sid}">
          <div class="scene-media">
            <img id="img{sid}" src="{img_src}" onerror="this.style.display='none'">
            <audio id="aud{sid}" controls src="{audio_src}"></audio>
          </div>
          <div class="scene-text">
            <div class="scene-meta">Scene {sid} · {dur:.1f}s</div>
            <label class="field-label">Narration</label>
            <textarea class="edit-field" id="narr{sid}" rows="3">{narration}</textarea>
            <button class="btn" onclick="regenAudio({sid})">Regen Audio</button>
            <label class="field-label">Image Prompt</label>
            <textarea class="edit-field prompt-field" id="prompt{sid}" rows="2">{prompt}</textarea>
            <button class="btn" onclick="regenImage({sid})">Regen Image</button>
          </div>
        </div>"""

    total_s = (timeline["total_duration_ms"] / 1000) if timeline else 0

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{script.get('title', 'Preview')}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f0f1a;color:#ddd;font-family:system-ui;padding:32px;max-width:960px;margin:0 auto}}
h1{{font-size:22px;margin-bottom:4px}}
.page-sub{{color:#666;font-size:13px;margin-bottom:24px}}
.scene{{background:#1a1a2e;border:1px solid #333;border-radius:12px;padding:16px;margin-bottom:14px;display:flex;gap:16px}}
.scene-media{{width:300px;flex-shrink:0}}
.scene-media img{{width:100%;border-radius:8px;display:block}}
.scene-media audio{{width:100%;margin-top:8px}}
.scene-text{{flex:1;display:flex;flex-direction:column;gap:4px}}
.scene-meta{{color:#888;font-size:12px;margin-bottom:2px}}
.field-label{{color:#666;font-size:11px;margin-top:8px}}
.edit-field{{width:100%;background:#12122a;border:1px solid #444;border-radius:6px;color:#ddd;padding:8px;font-size:13px;line-height:1.5;resize:vertical;font-family:inherit}}
.edit-field:focus{{border-color:#5580ff;outline:none}}
.prompt-field{{font-size:12px;color:#999}}
.btn{{margin-top:4px;padding:5px 14px;background:#2a2a4a;border:1px solid #444;border-radius:6px;color:#aaa;font-size:12px;cursor:pointer;align-self:flex-start;transition:all .15s}}
.btn:hover{{background:#3a3a5a;color:#ddd}}
.btn.loading{{opacity:0.5;pointer-events:none}}
.toast{{position:fixed;bottom:20px;right:20px;padding:10px 16px;border-radius:8px;font-size:13px;display:none;z-index:99}}
.toast.ok{{background:#2a4a2a;border:1px solid #4a6a4a;color:#8f8}}
.toast.err{{background:#4a2a2a;border:1px solid #6a4a4a;color:#f88}}
</style>
</head><body>
<h1>{script.get('title', '')}</h1>
<p class="page-sub">{script.get('description', '')} · {total_s:.0f}s · {len(scenes)} scenes</p>
{scenes_html}
<div class="toast" id="toast"></div>
<script>
const API = '{api}';

async function regenAudio(sid) {{
  const btn = event.target;
  const text = document.getElementById('narr'+sid).value;
  const audio = document.getElementById('aud'+sid);
  btn.classList.add('loading'); btn.textContent = 'Generating...';
  try {{
    const r = await fetch(`${{API}}/scenes/${{sid}}/audio`, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{narration:text}})}});
    if (!r.ok) throw new Error(await r.text());
    audio.src = `${{API}}/assets/scene_${{String(sid).padStart(2,'0')}}_audio.mp3?t=${{Date.now()}}`;
    toast('Audio regenerated','ok');
  }} catch(e) {{ toast('Failed: '+e.message,'err'); }}
  finally {{ btn.classList.remove('loading'); btn.textContent = 'Regen Audio'; }}
}}

async function regenImage(sid) {{
  const btn = event.target;
  const prompt = document.getElementById('prompt'+sid).value;
  const img = document.getElementById('img'+sid);
  btn.classList.add('loading'); btn.textContent = 'Generating...';
  try {{
    const r = await fetch(`${{API}}/scenes/${{sid}}/image`, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{image_prompt:prompt}})}});
    if (!r.ok) throw new Error(await r.text());
    img.src = `${{API}}/assets/scene_${{String(sid).padStart(2,'0')}}_image.png?t=${{Date.now()}}`;
    img.style.display = 'block';
    toast('Image regenerated','ok');
  }} catch(e) {{ toast('Failed: '+e.message,'err'); }}
  finally {{ btn.classList.remove('loading'); btn.textContent = 'Regen Image'; }}
}}

function toast(msg, type) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + (type||'ok');
  t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3000);
}}
</script>
</body></html>"""
    return HTMLResponse(html)


# ─── Scene editing ────────────────────────────────────────

class RegenAudioRequest(BaseModel):
    narration: str


@router.post("/runs/{run_id}/scenes/{scene_id}/audio")
async def regen_scene_audio(run_id: int, scene_id: int, body: RegenAudioRequest, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    rd = _run_dir(run_id)
    script_path = rd / "script.json"
    if not script_path.exists():
        raise HTTPException(status_code=400, detail="No script")

    script = json.loads(script_path.read_text(encoding="utf-8"))
    for scene in script.get("scenes", []):
        if scene["id"] == scene_id:
            scene["narration"] = body.narration
            break
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    cfg = get_settings()
    tts = EdgeTTSProvider(default_voice=cfg.tts.voice)
    audio_path = str(rd / "assets" / f"scene_{scene_id:02d}_audio.mp3")
    log.info("Regenerating audio for run #%d scene %d", run_id, scene_id)
    await tts.synthesize(text=body.narration, output_path=audio_path)

    return {"status": "ok", "scene_id": scene_id}


class RegenImageRequest(BaseModel):
    image_prompt: str
    size: str = ""


@router.post("/runs/{run_id}/scenes/{scene_id}/image")
async def regen_scene_image(run_id: int, scene_id: int, body: RegenImageRequest, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    rd = _run_dir(run_id)
    script_path = rd / "script.json"
    if not script_path.exists():
        raise HTTPException(status_code=400, detail="No script")

    script = json.loads(script_path.read_text(encoding="utf-8"))
    for scene in script.get("scenes", []):
        if scene["id"] == scene_id:
            scene["image_prompt"] = body.image_prompt
            break
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    cfg = get_settings()
    from app.providers.image import build_image_provider
    img_provider = build_image_provider(cfg)
    image_path = str(rd / "assets" / f"scene_{scene_id:02d}_image.png")
    log.info("Regenerating image for run #%d scene %d: %s", run_id, scene_id, body.image_prompt[:60])
    img_size = body.size or run.resolution or cfg.video.resolution
    await img_provider.generate(prompt=body.image_prompt, size=img_size, output_path=image_path)

    return {"status": "ok", "scene_id": scene_id}


# ─── Reroll articles ──────────────────────────────────────

@router.post("/runs/{run_id}/reroll-articles")
async def reroll_articles(run_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    # 按当前采集模式分流：daily 无意义→拒绝；weekly=重新总结；items/普通源=重新采集
    apath = _run_dir(run_id) / "articles.json"
    method = ""
    if apath.exists():
        try:
            arts = json.loads(apath.read_text(encoding="utf-8"))
            method = arts[0].get("aihot_method", "") if arts else ""
        except Exception:
            method = ""
    if method == "daily":
        # 前端也会禁用按钮，这里双保险防止直接打 API
        raise HTTPException(status_code=400, detail="日报模式无需重新采集")
    is_weekly = method == "weekly"
    run.progress_detail = "S1 重新总结中..." if is_weekly else "S1 重新采集中..."
    db.commit()
    session_factory = get_session_factory()
    background_tasks.add_task(_reroll_articles_bg, run_id, session_factory)
    return {"status": "resummarizing" if is_weekly else "rerolling"}


def _reroll_articles_bg(run_id: int, session_factory):
    asyncio.run(_reroll_articles_async(run_id, session_factory))


async def _reroll_articles_async(run_id: int, session_factory):
    from app.pipeline.stage1_collect import run_stage1
    from app.pipeline.runner import _summarize_articles, _save_articles, _update as runner_update, _distill_weekly_if_needed

    reload_settings()  # 重载配置，保证拿到最新提示词
    db = session_factory()
    try:
        run = db.get(PipelineRun, run_id)
        if not run:
            return
        cfg = get_settings()
        from app.models.news_source import NewsSource
        db_sources = db.query(NewsSource).filter(NewsSource.enabled == True).all()
        if db_sources:
            source_configs, collectors = build_collectors_from_db(db_sources)
        else:
            source_configs, collectors = build_collectors(cfg)
        articles = await run_stage1(
            sources=source_configs, collectors=collectors,
            time_range=run.time_range, max_articles=run.max_articles,
        )
        if articles and articles[0].metadata.get("source_group") != "aihot":
            runner_update(db, run, progress_detail="S1 生成摘要中...")
            await _summarize_articles(articles, cfg, run, db, log)
        elif articles and articles[0].metadata.get("aihot_method") == "weekly":
            runner_update(db, run, progress_detail="S1 提炼本周热点中...")
            await _distill_weekly_if_needed(articles, log)
        rd = _run_dir(run_id)
        rd.mkdir(parents=True, exist_ok=True)
        _save_articles(articles, rd)
        _update(db, run, progress_detail=f"S1 完成 — {len(articles)} 篇文章")
        log.info("Rerolled articles for run #%d — %d articles", run_id, len(articles))
    except Exception as e:
        log.exception("Reroll articles failed for run #%d", run_id)
        run = db.get(PipelineRun, run_id)
        if run:
            _update(db, run, progress_detail=f"采集失败: {_humanize_error(e)[:200]}")
    finally:
        db.close()


# ─── Regen prompt ─────────────────────────────────────────

class RegenPromptRequest(BaseModel):
    narration: str


@router.post("/runs/{run_id}/scenes/{scene_id}/regen-prompt")
async def regen_scene_prompt(run_id: int, scene_id: int, body: RegenPromptRequest):
    rd = _run_dir(run_id)
    script_path = rd / "script.json"
    if not script_path.exists():
        raise HTTPException(status_code=400, detail="No script")

    text_provider = _build_text_provider()
    from app.prompts import resolve_prompt
    system = resolve_prompt("image_regen")
    result = await text_provider.generate(prompt=body.narration, system_prompt=system)
    new_prompt = result.strip()

    script = json.loads(script_path.read_text(encoding="utf-8"))
    for scene in script.get("scenes", []):
        if scene["id"] == scene_id:
            scene["image_prompt"] = new_prompt
            break
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Regenerated prompt for run #%d scene %d", run_id, scene_id)
    return {"status": "ok", "image_prompt": new_prompt}


# ─── Scene add / delete ───────────────────────────────────

class _AddSceneBody(_PydBase):
    group_id: int
    requirement: str = ""


@router.post("/runs/{run_id}/scenes")
async def add_scene(run_id: int, body: _AddSceneBody):
    rd = _run_dir(run_id)
    script_path = rd / "script.json"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="Script not found")
    script = json.loads(script_path.read_text(encoding="utf-8"))
    group = next((g for g in script.get("groups", []) if g["id"] == body.group_id), None)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    articles = json.loads((rd / "articles.json").read_text(encoding="utf-8")) if (rd / "articles.json").exists() else []
    si = group.get("source_index", -1)
    src = articles[si] if 0 <= si < len(articles) else {}
    src_text = f"标题：{src.get('title', '')}\n内容：\n{(src.get('content') or '')[:2000]}"

    from app.pipeline.stage2_script import _parse_json
    from app.prompts import resolve_prompt
    tp = _build_text_provider()
    prompt = f"{src_text}\n\n额外要求：{body.requirement or '补充一个新分镜'}\n只输出 1 个分镜。"
    resp = await tp.generate(prompt=prompt, system_prompt=resolve_prompt("roundup_article"))
    try:
        gen = _parse_json(resp).get("scenes") or []
    except Exception:
        gen = []
    sc = gen[0] if gen else {"narration": "", "image_prompt": "", "motion_prompt": "", "duration_hint": 5}
    sc["id"] = max([s["id"] for s in script["scenes"]], default=0) + 1
    sc["group_id"] = body.group_id
    sc["group_title"] = group["title"]

    last = max((i for i, s in enumerate(script["scenes"]) if s["group_id"] == body.group_id), default=len(script["scenes"]) - 1)
    script["scenes"].insert(last + 1, sc)
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    return sc


@router.delete("/runs/{run_id}/scenes/{scene_id}")
def delete_scene(run_id: int, scene_id: int):
    rd = _run_dir(run_id)
    script_path = rd / "script.json"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="Script not found")
    script = json.loads(script_path.read_text(encoding="utf-8"))
    target = next((s for s in script["scenes"] if s["id"] == scene_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Scene not found")

    gid = target.get("group_id")
    same_group = [s for s in script["scenes"] if s.get("group_id") == gid]
    is_last_in_group = len(same_group) <= 1

    # 删除该分镜
    script["scenes"] = [s for s in script["scenes"] if s["id"] != scene_id]

    # 若删的是分组的最后一个分镜 → 连带删除该分组及其对应文章
    if is_last_in_group and gid is not None:
        group = next((g for g in script.get("groups", []) if g.get("id") == gid), None)
        script["groups"] = [g for g in script.get("groups", []) if g.get("id") != gid]
        si = group.get("source_index", -1) if group else -1
        if si >= 0:
            arts = _read_articles(run_id)
            if 0 <= si < len(arts):
                del arts[si]
                _write_articles(run_id, arts)
                # 删文章后其余分组指向的 source_index 若大于 si 需整体前移，维持对应关系
                for g in script.get("groups", []):
                    if g.get("source_index", -1) > si:
                        g["source_index"] -= 1
        log.info("Deleted last scene of group %s in run #%d → removed group + article[%s]", gid, run_id, si)

    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    return script


# ─── Preview HTML ─────────────────────────────────────────

@router.get("/runs/{run_id}/preview-html")
def get_preview_html(run_id: int, db: Session = Depends(get_db)):
    rd = _run_dir(run_id)
    timeline_path = rd / "timeline.json"
    if not timeline_path.exists():
        raise HTTPException(status_code=404, detail="No timeline — run stage 4 first")
    cfg = get_settings()
    run = db.get(PipelineRun, run_id)
    resolution = (run.resolution if run else None) or cfg.video.resolution
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    from app.providers.composer.hyperframes_composer import HyperframesComposer
    composer = HyperframesComposer()
    html = composer._render_html(timeline, resolution, rd, transition=cfg.video.transition)
    return HTMLResponse(html)


# ─── Trigger render ───────────────────────────────────────

@router.post("/runs/{run_id}/render")
async def trigger_render(run_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rd = _run_dir(run_id)
    is_audio = run.video_route == "audio"
    if is_audio:
        if not (rd / "script.json").exists():
            raise HTTPException(status_code=400, detail="No script — run stage 2 first")
    elif not (rd / "timeline.json").exists():
        raise HTTPException(status_code=400, detail="No timeline — run stage 4 first")
    run.current_stage = 5
    run.status = "processing"
    run.progress_detail = "S5 合成启动中..." if is_audio else "S5 渲染启动中..."
    run.output_path = None
    run.started_at = datetime.now(timezone.utc)  # 重新发起 → 刷新发起时间，避免被孤儿回收误判
    db.commit()
    session_factory = get_session_factory()
    background_tasks.add_task(_render_video_bg, run_id, session_factory)
    return {"status": "rendering"}


def _render_video_bg(run_id: int, session_factory):
    asyncio.run(_render_video_async(run_id, session_factory))


async def _render_video_async(run_id: int, session_factory):
    from app.pipeline.stage5_compose import run_stage5
    from app.pipeline.runner import _ffmpeg_compose

    reload_settings()  # 重载配置（视频/LTX 等），保证跨进程拿到最新值
    db = session_factory()
    try:
        run = db.get(PipelineRun, run_id)
        if not run:
            return
        cfg = get_settings()
        rd = _run_dir(run_id)

        if run.video_route == "audio":
            from app.pipeline.runner import _ffmpeg_merge_audio
            _update(db, run, progress_detail="S5 合成音频中...")
            try:
                script = json.loads((rd / "script.json").read_text(encoding="utf-8"))
                final_path = _ffmpeg_merge_audio(script, rd / "assets", rd)
            except Exception as e:
                _update(db, run, status="failed", error_message=f"音频合成失败: {e}", finished_at=datetime.now(timezone.utc))
                log.exception("Audio re-merge failed for run #%d", run_id)
                return
            if Path(final_path).exists():
                size_mb = Path(final_path).stat().st_size / 1024 / 1024
                _update(db, run, status="done", progress_detail=f"S5 合成完成 — {size_mb:.1f} MB", output_path=final_path, finished_at=datetime.now(timezone.utc))
                export_final(run_id, final_path)
            else:
                _update(db, run, status="failed", error_message="音频文件未生成", finished_at=datetime.now(timezone.utc))
            return

        timeline = json.loads((rd / "timeline.json").read_text(encoding="utf-8"))
        output_mp4 = str((rd / "output.mp4").resolve())
        resolution = run.resolution or cfg.video.resolution

        if run.video_route == "ltx":
            _update(db, run, progress_detail="S5 LTX 视频生成中...")
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
                result = await LTXComposer(ltx_video).compose(
                    timeline_json=timeline, assets_dir=str(rd / "assets"),
                    output_path=output_mp4, resolution=resolution,
                )
                final_path = result.file_path
            except Exception as e:
                log.warning("LTX render failed for run #%d: %s — trying FFmpeg", run_id, e)
                _update(db, run, progress_detail="S5 LTX 失败，FFmpeg 合成中...")
                final_path = _ffmpeg_compose(timeline, rd, resolution, cfg.video.fps)
        else:
            _update(db, run, progress_detail="S5 Hyperframes 渲染中...")
            from app.providers.composer.hyperframes_composer import HyperframesComposer
            composer = HyperframesComposer()
            try:
                result = await run_stage5(
                    timeline=timeline, composer=composer,
                    assets_dir=str(rd / "assets"), output_path=output_mp4,
                    resolution=resolution,
                )
                final_path = result.file_path
            except Exception as e:
                log.warning("Hyperframes render failed for run #%d: %s — trying FFmpeg", run_id, e)
                _update(db, run, progress_detail="S5 FFmpeg 合成中...")
                final_path = _ffmpeg_compose(timeline, rd, resolution, cfg.video.fps)

        if Path(final_path).exists():
            size_mb = Path(final_path).stat().st_size / 1024 / 1024
            _update(db, run, status="done", progress_detail=f"S5 渲染完成 — {size_mb:.1f} MB", output_path=final_path, finished_at=datetime.now(timezone.utc))
            export_final(run_id, final_path)
        else:
            _update(db, run, status="failed", error_message="Video file not found", finished_at=datetime.now(timezone.utc))
    except Exception as e:
        log.exception("Render failed for run #%d", run_id)
        run = db.get(PipelineRun, run_id)
        if run:
            _update(db, run, status="failed", error_message=_humanize_error(e, 5)[:500], finished_at=datetime.now(timezone.utc))
    finally:
        db.close()


# ─── Logs / Video ─────────────────────────────────────────

@router.get("/runs/{run_id}/logs")
def get_logs(run_id: int, tail: int = 200, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    log_path = _run_dir(run_id) / "pipeline.log"
    if not log_path.exists():
        return {"lines": []}
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return {"lines": lines[-tail:]}


def _output_media_meta(path: Path) -> tuple[str, str]:
    if path.suffix.lower() == ".mp3":
        return "audio/mpeg", "mp3"
    return "video/mp4", "mp4"


@router.get("/runs/{run_id}/video")
def get_video(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run or not run.output_path:
        raise HTTPException(status_code=404, detail="Output not available")
    path = Path(run.output_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")
    media_type, ext = _output_media_meta(path)
    return FileResponse(path, media_type=media_type, filename=f"run_{run_id}.{ext}")
