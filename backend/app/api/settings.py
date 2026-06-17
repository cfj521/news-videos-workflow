import shutil
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import Settings, get_settings, save_settings
from app.logging import get_logger
from app.prompts import PROMPTS

log = get_logger("api.settings")
router = APIRouter(prefix="/api/settings", tags=["settings"])

# 封面图存储目录（仓库根 data/cover/）
_COVER_DIR = Path(__file__).resolve().parents[3] / "data" / "cover"


def _deep_merge(dst: dict, src: dict) -> None:
    """递归合并 src 到 dst：嵌套 dict（如 providers.<name>、comfyui.image_params）逐键合并，
    其余整体替换。供 PUT 局部更新使用，避免漏发字段导致丢失。"""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


@router.get("/")
async def read_settings():
    # 内部管理工具：直接返回完整内容（含 api_key），便于前端展示与编辑
    return get_settings().model_dump()


@router.get("/raw")
async def read_settings_raw():
    return get_settings().model_dump()


@router.put("/")
async def update_settings(payload: dict):
    current = get_settings().model_dump()
    changed_groups = []
    for group_key, group_val in payload.items():
        if group_key == "infra":
            continue
        if group_key == "providers":
            current["providers"] = group_val  # 整体替换：支持删除自定义供应商（前端发全量）
        elif isinstance(group_val, dict) and isinstance(current.get(group_key), dict):
            _deep_merge(current[group_key], group_val)
        else:
            current[group_key] = group_val
        changed_groups.append(group_key)
    updated = Settings(**current)
    save_settings(updated)
    log.info("Settings updated — groups: %s", changed_groups)
    return updated.model_dump()


@router.get("/prompts/defaults")
async def prompt_defaults():
    return {p.key: {"label": p.label, "desc": p.desc, "default": p.default, "default_en": p.default_en or p.default} for p in PROMPTS}


@router.get("/comfyui/health")
async def comfyui_health(url: str = ""):
    """探测 ComfyUI 是否在线：GET {url}/system_stats（ComfyUI 自带），3s 超时。
    url 取前端输入框当前值（含未保存），留空用已存配置；测的就是填的地址，不套 NV_COMFYUI_URL。"""
    target = (url or get_settings().comfyui.server_url).rstrip("/")
    if not target:
        return {"ok": False, "url": target, "error": "未填写 ComfyUI 地址"}
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{target}/system_stats")
            r.raise_for_status()
            data = r.json()
    except Exception as e:  # noqa: BLE001 — 探活只需区分「可达/不可达」，任何异常都算不可达
        return {"ok": False, "url": target, "error": str(e) or e.__class__.__name__}
    sysinfo = data.get("system", {}) if isinstance(data, dict) else {}
    devices = data.get("devices", []) if isinstance(data, dict) else []
    version = sysinfo.get("comfyui_version") or sysinfo.get("version") or ""
    device = (devices[0].get("name") if devices else "") or ""
    detail = " · ".join(x for x in (f"ComfyUI {version}" if version else "", device) if x)
    return {"ok": True, "url": target, "detail": detail or "在线"}


@router.post("/cover-image")
async def upload_cover_image(file: UploadFile = File(...)):
    """上传封面图：保存到 data/cover/cover.<ext>（同名覆盖旧文件），返回相对路径。"""
    _COVER_DIR.mkdir(parents=True, exist_ok=True)
    ext = (Path(file.filename or "").suffix or ".png").lower()
    # 删除旧封面（不同扩展名也清除）
    for old in _COVER_DIR.glob("cover.*"):
        old.unlink(missing_ok=True)
    dst = _COVER_DIR / f"cover{ext}"
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    log.info("封面图已上传：%s", dst)
    return {"path": f"data/cover/{dst.name}"}


@router.get("/cover-image")
def get_cover_image():
    """回显当前封面图文件（二进制流）；无封面时返回 404。"""
    files = sorted(_COVER_DIR.glob("cover.*")) if _COVER_DIR.is_dir() else []
    if not files:
        raise HTTPException(status_code=404, detail="no cover image")
    return FileResponse(files[0])
