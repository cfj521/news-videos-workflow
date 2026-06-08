"""一次性迁移：把 config.yaml 的 providers 与 DB 的 oauth_credentials 导入 model_providers.yaml。

幂等：model_providers.yaml 已存在则整体跳过。用原生 sqlite3 读 oauth，不依赖 ORM
（OAuthCredential 模型将被删除）。
"""
from __future__ import annotations

import contextlib
import logging
import sqlite3
from pathlib import Path

import yaml

from app.config import ProviderCreds
from app.store import providers_store as ps
from app.store.oauth_models import OAuthData

log = logging.getLogger("nv.migrate")

_OAUTH_COLS = ("access_token", "refresh_token", "id_token", "account_id",
               "expires_at", "plan_type", "account_email", "last_refresh")


def _read_oauth_from_sqlite(sqlite_path: Path) -> OAuthData | None:
    if not sqlite_path.exists():
        return None
    try:
        with contextlib.closing(sqlite3.connect(sqlite_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM oauth_credentials WHERE provider = 'openai' LIMIT 1")
            row = cur.fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    keys = row.keys()
    return OAuthData(**{c: (row[c] or "") for c in _OAUTH_COLS if c in keys})


def migrate_providers_to_yaml(*, config_path: Path, sqlite_path: Path) -> None:
    if ps.MODEL_PROVIDERS_PATH.exists():
        return  # 幂等：已迁移
    raw_cfg = (
        yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    )
    raw_providers = (raw_cfg or {}).get("providers", {}) or {}
    creds = {name: ProviderCreds(**{k: v for k, v in (slot or {}).items() if k != "oauth"})
             for name, slot in raw_providers.items()}
    ps.save_providers(creds)
    oauth = _read_oauth_from_sqlite(sqlite_path)
    if oauth and oauth.access_token:
        ps.save_oauth("openai", oauth)
    log.info("Migrated %d providers + oauth=%s → %s",
             len(creds), bool(oauth and oauth.access_token), ps.MODEL_PROVIDERS_PATH)
