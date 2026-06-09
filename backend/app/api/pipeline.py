import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel
from pydantic import BaseModel as _PydBase
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_session_factory
from app.services.document_import import import_file, import_url
from app.config import get_settings, reload_settings
from app.logging import get_logger
from app.models.pipeline_run import PipelineRun
from app.pipeline.engine import PipelineEngine
from app.pipeline.runner import execute_pipeline, _collectors_for_run, _build_text_provider, _update, _article_from_dict, _humanize_error, export_final, run_pipeline_bg
from app.pipeline.serial_executor import submit as serial_submit
from app.schemas.pipeline import PipelineRunCreate, PipelineRunRead

log = get_logger("api.pipeline")
router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
# 公开的只读媒体端点（图片/音频/预览 HTML/视频）：浏览器的 <img>/<audio>/<video>
# 标签与 iframe 内的相对引用都无法携带 Authorization 头，故这些 GET 不挂登录守卫。
public_router = APIRouter(prefix="/api/pipeline", tags=["pipeline-public"])


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
def create_run(body: PipelineRunCreate, db: Session = Depends(get_db)):
    log.info("POST /runs — mode=%s stages=%s platforms=%s", body.mode, body.selected_stages, body.publish_platforms)
    cfg = get_settings()
    engine = PipelineEngine(db)
    run = engine.create_run(
        mode=body.mode, video_route=body.video_route, time_range=body.time_range,
        max_articles=body.max_articles, selected_stages=body.selected_stages,
        publish_platforms=body.publish_platforms,
        auto_collect=body.auto_collect,
        resolution=body.resolution or cfg.pipeline.resolution,
        language=body.language or cfg.pipeline.default_language,
        max_images=body.max_images if body.max_images is not None else cfg.pipeline.max_images,
        source_ids=body.source_ids,
        aihot_config=body.aihot_config,
    )
    session_factory = get_session_factory()
    serial_submit(_run_pipeline_bg, run.id, session_factory, label=f"run#{run.id}")
    log.info("Pipeline run #%d queued (serial)", run.id)
    return run


class _RunUpdate(BaseModel):
    resolution: str | None = None


@router.patch("/runs/{run_id}", response_model=PipelineRunRead)
def update_run(run_id: int, body: _RunUpdate, db: Session = Depends(get_db)):
    """更新任务级参数（目前仅分辨率）。图片阶段改分辨率会回写到这里，作为后续各阶段的权威值。"""
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if body.resolution is not None:
        run.resolution = body.resolution or None
    db.commit()
    db.refresh(run)
    log.info("Updated run #%d resolution=%s", run_id, run.resolution)
    return run


_run_pipeline_bg = run_pipeline_bg


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


class _TTSPreview(BaseModel):
    provider: str = ""
    model: str = ""
    voice: str = ""
    text: str = ""


@router.post("/tts/preview")
async def tts_preview(body: _TTSPreview):
    """试听：用所选供应商/模型/音色合成一小段示例音频，直接返回音频字节供前端播放。"""
    import os as _os
    import tempfile

    from app.providers.tts import build_tts_provider
    cfg = get_settings()
    prov = body.provider or cfg.pipeline.tts_provider or "edge-tts"
    # 前置校验：openai/dashscope 走真实接口，需对应供应商 key（与文本/图片共用）
    if prov in ("openai", "dashscope") and not cfg.provider_creds(prov).api_key:
        raise HTTPException(status_code=400, detail=f"未配置 {prov} 的 API Key，请在「模型配置」中填写（与文本/图片共用）")
    text = body.text or "你好，这是语音试听示例。Hello, this is a voice preview."
    fd, tmp = tempfile.mkstemp(suffix=".audio")
    _os.close(fd)
    try:
        provider = build_tts_provider(cfg, provider=body.provider, model=body.model, voice=body.voice)
        await provider.synthesize(text=text, voice=body.voice, output_path=tmp)
        data = Path(tmp).read_bytes()
    except ModuleNotFoundError as e:
        log.warning("TTS preview missing dep: %s", e)
        raise HTTPException(status_code=400, detail="阿里云语音需安装 dashscope 依赖（本机 pip install dashscope；容器重建）")
    except Exception as e:
        log.warning("TTS preview failed: %s", e)
        raise HTTPException(status_code=400, detail=f"试听失败: {e}")
    finally:
        try:
            _os.remove(tmp)
        except OSError:
            pass
    # qwen-tts 返回 wav，其余(openai/edge/cosyvoice)为 mp3
    is_qwen = prov == "dashscope" and not (body.model or cfg.pipeline.tts_model).startswith("cosyvoice")
    media = "audio/wav" if is_qwen else "audio/mpeg"
    return Response(content=data, media_type=media)


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: int, db: Session = Depends(get_db)):
    from datetime import datetime, timezone

    from app.pipeline.runner import request_cancel
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    request_cancel(run_id)  # 内存标记：运行中的后台任务会在下个检查点中止
    run.status = "cancelled"
    run.progress_detail = "已终止"
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    log.info("POST /runs/%d/stop — cancellation requested", run_id)
    return {"status": "cancelled", "run_id": run_id}


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

@public_router.get("/runs/{run_id}/assets/{filename:path}")
def get_asset(run_id: int, filename: str):
    # 防路径穿越：解析后必须仍落在该任务的 assets/ 目录内，否则视为不存在。
    assets_root = (_run_dir(run_id) / "assets").resolve()
    path = (assets_root / filename).resolve()
    if not path.is_relative_to(assets_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    mime = "image/png" if path.suffix == ".png" else "audio/mpeg" if path.suffix == ".mp3" else "application/octet-stream"
    return FileResponse(path, media_type=mime)


@public_router.get("/runs/{run_id}/events")
async def run_events(run_id: int):
    """SSE 事件流：S3 每生成一张图/一段音频，推一条 {type:asset, kind, scene}。
    前端据此只刷新对应场景的素材。EventSource 无法带鉴权头，故放在 public_router。"""
    import asyncio
    import json as _json

    from app.api.dependencies import get_session_factory
    from app.pipeline.events import subscribe, unsubscribe

    def _status() -> str | None:
        s = get_session_factory()()
        try:
            r = s.get(PipelineRun, run_id)
            return r.status if r else None
        finally:
            s.close()

    async def gen():
        q = subscribe(run_id)
        try:
            yield ": connected\n\n"
            if _status() in ("done", "failed", "cancelled", None):
                yield f"data: {_json.dumps({'type': 'end'})}\n\n"
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {_json.dumps(ev)}\n\n"
                    if ev.get("type") == "progress" and ev.get("status") in ("done", "failed", "cancelled"):
                        yield f"data: {_json.dumps({'type': 'end'})}\n\n"
                        break
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # 心跳保活 + 顺带探测是否已结束
                    if _status() in ("done", "failed", "cancelled", None):
                        yield f"data: {_json.dumps({'type': 'end'})}\n\n"
                        break
        finally:
            unsubscribe(run_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


# ─── Stage data ───────────────────────────────────────────

@router.get("/runs/{run_id}/scoring")
def get_scoring(run_id: int):
    p = _run_dir(run_id) / "scoring.json"
    if not p.exists():
        return {"candidates": []}
    return json.loads(p.read_text(encoding="utf-8"))


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
    from app.config import ProviderCfg, resolve
    vp, vb, vk, vm = resolve(cfg, "vision")
    v_auth = cfg.provider_creds("openai").auth_mode if vp == "openai" else "api_key"
    if vp == "openai" and v_auth == "subscription":
        vm = "gpt-5.5"  # 订阅解析端点支持的模型
    vcfg = ProviderCfg(provider=vp, base_url=vb, model=vm, api_key=vk, auth_mode=v_auth)
    try:
        art = await import_file(data, file.filename or "", vcfg)
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
    tp = _build_text_provider()

    from app.pipeline.stage2_script import run_stage2_multi
    log.info("Regenerating multi-article script for run #%d (%d articles)", run_id, len(arts))
    script = await run_stage2_multi(arts, tp, language=(run.language or cfg.pipeline.default_language))
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
    from app.providers.tts import build_tts_provider
    tts = build_tts_provider(cfg)  # 按流水线选型（edge-tts|openai|dashscope）
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

    reload_settings()  # 拿最新图片 provider 配置
    cfg = get_settings()
    from app.providers.image import build_image_provider
    img_provider = build_image_provider(cfg)
    image_path = str(rd / "assets" / f"scene_{scene_id:02d}_image.png")
    log.info("Regenerating image for run #%d scene %d: %s", run_id, scene_id, body.image_prompt[:60])
    img_size = body.size or run.resolution or "1080x1920"
    await img_provider.generate(prompt=body.image_prompt, size=img_size, output_path=image_path)

    return {"status": "ok", "scene_id": scene_id}


# ─── Reroll articles ──────────────────────────────────────

@router.post("/runs/{run_id}/reroll-articles")
async def reroll_articles(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    # 按当前采集模式分流：daily 无意义→拒绝；weekly=重新总结；items/普通源=重新采集
    method = ""
    if run.aihot_config:
        try:
            method = (json.loads(run.aihot_config) or {}).get("method", "")
        except Exception:
            method = ""
    if method == "daily":
        # 前端也会禁用按钮，这里双保险防止直接打 API
        raise HTTPException(status_code=400, detail="日报模式无需重新采集")
    is_weekly = method == "weekly"
    run.progress_detail = "S1 重新总结中..." if is_weekly else "S1 重新采集中..."
    db.commit()
    session_factory = get_session_factory()
    serial_submit(_reroll_articles_bg, run_id, session_factory, label=f"reroll#{run_id}")
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
        source_configs, collectors = _collectors_for_run(db, run, get_settings())
        articles = await run_stage1(
            sources=source_configs, collectors=collectors,
            time_range=run.time_range, max_articles=run.max_articles,
        )
        if not articles:
            # 没采到任何文章（如周报当周无日报）：保留原有 articles.json，不静默清空，并给明确提示
            from app.pipeline.runner import _no_article_message
            method = next((sc.get("method") for sc in source_configs if sc.get("method") in ("daily", "weekly")), None)
            _update(db, run, progress_detail=f"重新采集未获得文章（保留原列表）：{_no_article_message(method)}")
            log.warning("Reroll for run #%d collected 0 articles — keeping existing list", run_id)
            return
        if articles[0].metadata.get("source_group") != "aihot":
            runner_update(db, run, progress_detail="S1 生成摘要中...")
            await _summarize_articles(articles, cfg, run, db, log)
        elif articles[0].metadata.get("aihot_method") == "weekly":
            runner_update(db, run, progress_detail="S1 提炼本周热点中...")
            await _distill_weekly_if_needed(articles, log, run.language or cfg.pipeline.default_language)
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
async def regen_scene_prompt(run_id: int, scene_id: int, body: RegenPromptRequest, db: Session = Depends(get_db)):
    rd = _run_dir(run_id)
    script_path = rd / "script.json"
    if not script_path.exists():
        raise HTTPException(status_code=400, detail="No script")

    reload_settings()  # 拿最新提示词（跨进程 worker 也生效）
    run = db.get(PipelineRun, run_id)
    lang = (run.language if run else None) or get_settings().pipeline.default_language
    text_provider = _build_text_provider()
    from app.prompts import resolve_prompt
    system = resolve_prompt("image_regen", lang)
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
async def add_scene(run_id: int, body: _AddSceneBody, db: Session = Depends(get_db)):
    reload_settings()  # 拿最新提示词
    run = db.get(PipelineRun, run_id)
    lang = (run.language if run else None) or get_settings().pipeline.default_language
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
    resp = await tp.generate(prompt=prompt, system_prompt=resolve_prompt("roundup_article", lang))
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
        # 仅当没有其它分组再引用这篇文章时才删它（日报/周报是多分组共享同一篇汇总文章，不能删）
        still_used = any(g.get("source_index") == si for g in script["groups"])
        if si >= 0 and not still_used:
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

@public_router.get("/runs/{run_id}/preview-html")
def get_preview_html(run_id: int, db: Session = Depends(get_db)):
    rd = _run_dir(run_id)
    timeline_path = rd / "timeline.json"
    if not timeline_path.exists():
        raise HTTPException(status_code=404, detail="No timeline — run stage 4 first")
    cfg = get_settings()
    run = db.get(PipelineRun, run_id)
    resolution = (run.resolution if run else None) or "1080x1920"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    from app.providers.composer.hyperframes_composer import HyperframesComposer
    composer = HyperframesComposer()
    html = composer._render_html(timeline, resolution, rd, transition=cfg.hyperframes.transition,
                                 subtitle_font_size=cfg.hyperframes.subtitle_font_size)
    return HTMLResponse(html)


# ─── Trigger render ───────────────────────────────────────

@router.post("/runs/{run_id}/render")
async def trigger_render(run_id: int, db: Session = Depends(get_db)):
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
    run.error_message = None  # 重新渲染 → 清掉上次失败残留的报错
    run.finished_at = None
    run.started_at = datetime.now(timezone.utc)  # 重新发起 → 刷新发起时间，避免被孤儿回收误判
    db.commit()
    session_factory = get_session_factory()
    serial_submit(_render_video_bg, run_id, session_factory, label=f"render#{run_id}")
    return {"status": "rendering"}


def _render_video_bg(run_id: int, session_factory):
    asyncio.run(_render_video_async(run_id, session_factory))


async def _render_video_async(run_id: int, session_factory):
    from app.pipeline.stage5_compose import run_stage5
    from app.pipeline.runner import _ffmpeg_compose

    reload_settings()  # 重载配置（视频等），保证跨进程拿到最新值
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
                _update(db, run, status="done", progress_detail=f"S5 合成完成 — {size_mb:.1f} MB", output_path=final_path, error_message=None, finished_at=datetime.now(timezone.utc))
                export_final(run_id, final_path)
            else:
                _update(db, run, status="failed", error_message="音频文件未生成", finished_at=datetime.now(timezone.utc))
            return

        timeline = json.loads((rd / "timeline.json").read_text(encoding="utf-8"))
        output_mp4 = str((rd / "output.mp4").resolve())
        resolution = run.resolution or "1080x1920"

        if run.video_route == "comfyui":
            _update(db, run, progress_detail="S5 ComfyUI 视频生成中...")
            try:
                from app.providers.video import build_video_provider
                from app.providers.composer.comfyui_composer import ComfyUIVideoComposer
                vp = build_video_provider(cfg)
                result = await ComfyUIVideoComposer(vp, fps=cfg.pipeline.video_fps).compose(
                    timeline_json=timeline, assets_dir=str(rd / "assets"),
                    output_path=output_mp4, resolution=resolution,
                )
                final_path = result.file_path
            except Exception as e:
                log.warning("ComfyUI render failed for run #%d: %s — trying FFmpeg", run_id, e)
                _update(db, run, progress_detail="S5 ComfyUI 失败，FFmpeg 合成中...")
                final_path = _ffmpeg_compose(timeline, rd, resolution, cfg.hyperframes.fps)
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
                final_path = _ffmpeg_compose(timeline, rd, resolution, cfg.hyperframes.fps)

        if Path(final_path).exists():
            size_mb = Path(final_path).stat().st_size / 1024 / 1024
            _update(db, run, status="done", progress_detail=f"S5 渲染完成 — {size_mb:.1f} MB", output_path=final_path, error_message=None, finished_at=datetime.now(timezone.utc))
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


# ─── Publish (re)trigger ──────────────────────────────────

def _parse_target_slugs(publish_platforms: str | None) -> set[str]:
    """从 run.publish_platforms（账号 slug 列表，JSON）解析 slug 集合；容错非字符串项跳过。"""
    out: set[str] = set()
    for x in json.loads(publish_platforms or "[]"):
        if isinstance(x, str) and x:
            out.add(x)
    return out


@router.post("/runs/{run_id}/publish")
def trigger_publish(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not (run.output_path and Path(run.output_path).exists()):
        raise HTTPException(status_code=400, detail="尚无成片，请先完成渲染（S5）再发布")
    if not _parse_target_slugs(run.publish_platforms):
        raise HTTPException(status_code=400, detail="未选择发布账号")
    run.current_stage = 6
    run.status = "processing"
    run.progress_detail = "S6 发布启动中..."
    run.error_message = None  # 重新发布 → 清掉上次失败残留的报错
    run.finished_at = None
    run.started_at = datetime.now(timezone.utc)  # 刷新发起时间，避免被孤儿回收误判
    db.commit()
    serial_submit(_publish_bg, run_id, get_session_factory(), label=f"publish#{run_id}")
    return {"status": "publishing"}


def _publish_bg(run_id: int, session_factory):
    asyncio.run(_publish_async(run_id, session_factory))


async def _publish_async(run_id: int, session_factory):
    from dataclasses import asdict

    from app.pipeline.stage6_publish import run_stage6
    from app.providers.publisher import build_publishers
    from app.store import targets_store

    reload_settings()
    db = session_factory()
    try:
        run = db.get(PipelineRun, run_id)
        if not run:
            return
        rd = _run_dir(run_id)
        slugs = _parse_target_slugs(run.publish_platforms)
        targets = [t for t in targets_store.list_targets() if t.enabled and t.slug in slugs]
        if not targets:
            _update(db, run, status="failed", error_message="无可用发布账号（可能已被禁用）",
                    finished_at=datetime.now(timezone.utc))
            return

        meta: dict = {}
        sj = rd / "script.json"
        if sj.exists():
            meta = json.loads(sj.read_text(encoding="utf-8"))
        srt = rd / "output.srt"

        _update(db, run, progress_detail=f"S6 发布到 {', '.join(t.name for t in targets)}...")
        results = await run_stage6(
            video_path=run.output_path, thumbnail_path=None,
            title=meta.get("title", ""), description=meta.get("description", ""),
            tags=meta.get("tags", []), publishers=build_publishers(targets),
            subtitle_path=str(srt) if srt.exists() else None,
        )

        def _label(r):
            return r.target_name or r.platform

        ok = [_label(r) for r in results if r.status == "success"]
        fail = [f"{_label(r)}({r.error_message})" for r in results if r.status != "success"]
        summary = "S6 发布完成 — 成功: " + (", ".join(ok) or "无")
        if fail:
            summary += " | 失败: " + ", ".join(fail)
        (rd / "publish_results.json").write_text(
            json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8")
        # 有任一失败也标记 done（结果在面板逐条展示），失败账号可单独再发
        _update(db, run, status="done", progress_detail=summary[:500],
                error_message=None, finished_at=datetime.now(timezone.utc))
        from app.pipeline.events import publish as _pub
        _pub(run_id, {"type": "publish"})  # 通知前端刷新发布结果
        log.info("[publish] run #%d — %s", run_id, summary)
    except Exception as e:
        log.exception("Publish failed for run #%d", run_id)
        run = db.get(PipelineRun, run_id)
        if run:
            _update(db, run, status="failed", error_message=_humanize_error(e, 6)[:500],
                    finished_at=datetime.now(timezone.utc))
    finally:
        db.close()


@router.get("/runs/{run_id}/publish-results")
def get_publish_results(run_id: int):
    p = _run_dir(run_id) / "publish_results.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


# ─── Logs / Video ─────────────────────────────────────────

@router.get("/runs/{run_id}/logs")
def get_logs(run_id: int, tail: int = 200, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    # 日志已统一汇入 data/logs/app.log（不再写 per-run pipeline.log）；
    # 每行带 [run=N] 标记，这里按标记切出本 run 的日志。
    from app.logging import GLOBAL_LOG
    if not GLOBAL_LOG.exists():
        return {"lines": []}
    marker = f"[run={run_id}]"
    lines = [ln for ln in GLOBAL_LOG.read_text(encoding="utf-8").splitlines() if marker in ln]
    return {"lines": lines[-tail:]}


def _output_media_meta(path: Path) -> tuple[str, str]:
    if path.suffix.lower() == ".mp3":
        return "audio/mpeg", "mp3"
    return "video/mp4", "mp4"


@public_router.get("/runs/{run_id}/subtitles")
def get_subtitles(run_id: int):
    path = _run_dir(run_id) / "output.srt"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No subtitles — run stage 4 first")
    return FileResponse(path, media_type="application/x-subrip", filename=f"run_{run_id}.srt")


@public_router.get("/runs/{run_id}/video")
def get_video(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PipelineRun, run_id)
    if not run or not run.output_path:
        raise HTTPException(status_code=404, detail="Output not available")
    path = Path(run.output_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")
    media_type, ext = _output_media_meta(path)
    return FileResponse(path, media_type=media_type, filename=f"run_{run_id}.{ext}")
