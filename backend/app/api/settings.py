from fastapi import APIRouter

from app.config import Settings, get_settings, save_settings
from app.logging import get_logger
from app.prompts import PROMPTS

log = get_logger("api.settings")
router = APIRouter(prefix="/api/settings", tags=["settings"])


def _redact(settings: Settings) -> dict:
    data = settings.model_dump()
    for group in ("text", "image", "tts"):
        key = data.get(group, {}).get("api_key", "")
        if key and len(key) > 8:
            data[group]["api_key"] = key[:4] + "..." + key[-4:]
    for field in ("tavily_key", "brave_key", "serper_key"):
        key = data.get("collectors", {}).get(field, "")
        if key and len(key) > 8:
            data["collectors"][field] = key[:4] + "..." + key[-4:]
    for field in ("client_id", "client_secret"):
        key = data.get("youtube", {}).get(field, "")
        if key and len(key) > 8:
            data["youtube"][field] = key[:4] + "..." + key[-4:]
    return data


@router.get("/")
async def read_settings():
    return _redact(get_settings())


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
        if isinstance(group_val, dict) and group_key in current:
            secret_group = group_key in ("text", "image", "tts", "collectors", "youtube")
            for k, v in group_val.items():
                if secret_group and isinstance(v, str) and "..." in v:
                    continue  # 跳过未改动的脱敏密钥
                current[group_key][k] = v
            changed_groups.append(group_key)
        else:
            current[group_key] = group_val
            changed_groups.append(group_key)
    updated = Settings(**current)
    save_settings(updated)
    log.info("Settings updated — groups: %s", changed_groups)
    return _redact(updated)


@router.get("/prompts/defaults")
async def prompt_defaults():
    return {p.key: {"label": p.label, "desc": p.desc, "default": p.default} for p in PROMPTS}
