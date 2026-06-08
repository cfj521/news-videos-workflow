"""model_providers.yaml 读写：providers 凭证（被 config.Settings 注入）+ oauth 订阅凭证。

文件结构：
    providers:
      openai:
        base_url, api_key, auth_mode, max_output_tokens
        models: {text: [], image: [], vision: [], tts: []}
        oauth: {access_token, refresh_token, ...}   # 仅订阅模式有意义
"""
from __future__ import annotations

from pathlib import Path

from app.config import ProviderCreds
from app.store import _io
from app.store.oauth_models import OAuthData

MODEL_PROVIDERS_PATH = Path(__file__).resolve().parents[3] / "model_providers.yaml"


def _read() -> dict:
    return _io.load_yaml(MODEL_PROVIDERS_PATH)


def _write(data: dict) -> None:
    _io.save_yaml(MODEL_PROVIDERS_PATH, data)


def load_providers() -> dict[str, ProviderCreds]:
    """返回 {name: ProviderCreds}（不含 oauth 子键）。"""
    raw = _read().get("providers", {}) or {}
    out: dict[str, ProviderCreds] = {}
    for name, slot in raw.items():
        slot = dict(slot or {})
        slot.pop("oauth", None)  # oauth 单独取
        out[name] = ProviderCreds(**slot)
    return out


def save_providers(creds_by_name: dict[str, ProviderCreds]) -> None:
    """整体替换 providers 的凭证部分；保留每个 provider 已有的 oauth 子键。"""
    with _io.file_lock(MODEL_PROVIDERS_PATH):
        data = _read()
        old = data.get("providers", {}) or {}
        new: dict[str, dict] = {}
        for name, creds in creds_by_name.items():
            slot = creds.model_dump()
            existing_oauth = (old.get(name) or {}).get("oauth")
            if existing_oauth:
                slot["oauth"] = existing_oauth
            new[name] = slot
        data["providers"] = new
        _write(data)


def load_oauth(provider: str) -> OAuthData:
    """读取指定 provider 的 oauth 凭证；未配置时返回空 OAuthData。"""
    slot = (_read().get("providers", {}) or {}).get(provider, {}) or {}
    return OAuthData(**(slot.get("oauth") or {}))


def save_oauth(provider: str, oauth: OAuthData) -> None:
    """写入指定 provider 的 oauth 凭证（原子操作，持文件锁）。"""
    with _io.file_lock(MODEL_PROVIDERS_PATH):
        data = _read()
        providers = data.setdefault("providers", {})
        slot = providers.setdefault(provider, {})
        slot["oauth"] = oauth.model_dump()
        _write(data)


def clear_oauth(provider: str) -> None:
    """清除指定 provider 的 oauth 凭证（provider 不存在则静默忽略）。"""
    with _io.file_lock(MODEL_PROVIDERS_PATH):
        data = _read()
        slot = (data.get("providers", {}) or {}).get(provider)
        if slot and "oauth" in slot:
            del slot["oauth"]
            _write(data)
