"""一次性迁移：把 config.yaml 的 providers 与 DB 的 oauth_credentials 导入 model_providers.yaml。

幂等：model_providers.yaml 已存在则整体跳过。用原生 sqlite3 读 oauth，不依赖 ORM
（OAuthCredential 模型将被删除）。
"""
from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from pathlib import Path

import yaml

from app.config import ProviderCreds
from app.store import providers_store as ps
from app.store import targets_store as ts
from app.store._slug import slugify, unique_slug
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


def _rewrite_publish_platforms(conn, id_to_slug: dict[int, str]) -> None:
    """把 pipeline_runs.publish_platforms 里的旧 int id 改写为 slug；映射不到的项原样保留。"""
    try:
        rows = conn.execute("SELECT id, publish_platforms FROM pipeline_runs").fetchall()
    except sqlite3.Error:
        return
    for run_id, pp in rows:
        if not pp:
            continue
        try:
            items = json.loads(pp)
        except (ValueError, TypeError):
            continue
        new = []
        for x in items:
            try:
                new.append(id_to_slug.get(int(x), x))
            except (ValueError, TypeError):
                new.append(x)
        conn.execute("UPDATE pipeline_runs SET publish_platforms = ? WHERE id = ?",
                     (json.dumps(new), run_id))
    conn.commit()


def migrate_targets_to_yaml(*, config_path: Path, sqlite_path: Path) -> None:
    """把 DB publish_targets 迁入 publish_targets.yaml，同时改写历史 run.publish_platforms 为 slug。

    幂等：publish_targets.yaml 已存在则整体跳过。
    YouTube OAuth client 从 config.yaml 的 youtube 节读取，
    若 config 不含 youtube 则写入空串兜底值。
    """
    if ts.TARGETS_PATH.exists():
        return  # 幂等
    raw_cfg = (
        yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    )
    yt = (raw_cfg or {}).get("youtube") or {}
    id_to_slug: dict[int, str] = {}
    if sqlite_path.exists():
        try:
            with contextlib.closing(sqlite3.connect(sqlite_path)) as conn:
                conn.row_factory = sqlite3.Row
                try:
                    rows = conn.execute("SELECT * FROM publish_targets ORDER BY id").fetchall()
                except sqlite3.Error:
                    rows = []
                existing: set[str] = set()
                for row in rows:
                    name = row["name"] or ""
                    platform = row["platform"] or ""
                    slug = unique_slug(slugify(name), existing, platform or "target")
                    existing.add(slug)
                    id_to_slug[int(row["id"])] = slug
                    try:
                        config = json.loads(row["config_json"]) if row["config_json"] else {}
                    except (ValueError, TypeError):
                        config = {}
                    ts.create_target(name=name, platform=platform, config=config,
                                     enabled=bool(row["enabled"]), slug=slug)
                if id_to_slug:
                    _rewrite_publish_platforms(conn, id_to_slug)
        except sqlite3.Error:
            pass
    ts.save_youtube_client({
        "client_id": yt.get("client_id", ""),
        "client_secret": yt.get("client_secret", ""),
    })
    log.info("Migrated %d publish targets + youtube → %s", len(id_to_slug), ts.TARGETS_PATH)
