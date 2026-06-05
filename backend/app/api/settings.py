from fastapi import APIRouter

from app.config import Settings, get_settings, save_settings
from app.logging import get_logger
from app.prompts import PROMPTS

log = get_logger("api.settings")
router = APIRouter(prefix="/api/settings", tags=["settings"])


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
