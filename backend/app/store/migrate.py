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
from app.store import sources_store as ss
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
    """
    if ts.TARGETS_PATH.exists():
        return  # 幂等
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
    ts.ensure_file()  # 无 DB target 时也落空文件，保证幂等
    log.info("Migrated %d publish targets → %s", len(id_to_slug), ts.TARGETS_PATH)


def _rewrite_source_ids(conn, id_to_slug: dict[int, str]) -> None:
    """把 pipeline_runs.source_ids 里的旧 int id 改写为 slug；映射不到原样保留。"""
    try:
        rows = conn.execute("SELECT id, source_ids FROM pipeline_runs").fetchall()
    except sqlite3.Error:
        return
    for run_id, sids in rows:
        if not sids:
            continue
        try:
            items = json.loads(sids)
        except (ValueError, TypeError):
            continue
        new = []
        for x in items:
            try:
                new.append(id_to_slug.get(int(x), x))
            except (ValueError, TypeError):
                new.append(x)
        conn.execute("UPDATE pipeline_runs SET source_ids = ? WHERE id = ?",
                     (json.dumps(new), run_id))
    conn.commit()


_SRC_COLS = ("name", "type", "url", "category", "language", "priority", "enabled", "tier", "pinned")


def migrate_sources_to_yaml(*, config_path: Path, sqlite_path: Path) -> None:
    """把 DB news_sources 迁入 news_sources.yaml，同时改写历史 run.source_ids 为 slug。

    幂等：news_sources.yaml 已存在则整体跳过。
    collectors 搜索 key 从 config.yaml 的 collectors 节读取并写入 yaml。
    """
    if ss.NEWS_SOURCES_PATH.exists():
        return  # 幂等
    raw_cfg = (yaml.safe_load(config_path.read_text(encoding="utf-8"))
               if config_path.exists() else {})
    collectors = (raw_cfg or {}).get("collectors") or {}
    id_to_slug: dict[int, str] = {}
    if sqlite_path.exists():
        try:
            with contextlib.closing(sqlite3.connect(sqlite_path)) as conn:
                conn.row_factory = sqlite3.Row
                try:
                    rows = conn.execute("SELECT * FROM news_sources ORDER BY id").fetchall()
                except sqlite3.Error:
                    rows = []
                existing: set[str] = set()
                for row in rows:
                    keys = row.keys()
                    name = row["name"] or ""
                    stype = row["type"] or ""
                    slug = unique_slug(slugify(name), existing, stype or "source")
                    existing.add(slug)
                    id_to_slug[int(row["id"])] = slug
                    cj = row["config_json"] if "config_json" in keys else None
                    try:
                        config = json.loads(cj) if cj else {}
                    except (ValueError, TypeError):
                        config = {}
                    kw = {c: row[c] for c in _SRC_COLS if c in keys}
                    kw["enabled"] = bool(kw.get("enabled", True))
                    kw["pinned"] = bool(kw.get("pinned", False))
                    ss.create_source(config=config, slug=slug, **kw)
                if id_to_slug:
                    _rewrite_source_ids(conn, id_to_slug)
        except sqlite3.Error:
            pass
    ss.save_search_keys({
        "tavily_key": collectors.get("tavily_key", ""),
        "brave_key": collectors.get("brave_key", ""),
        "serper_key": collectors.get("serper_key", ""),
    })
    log.info("Migrated %d news sources + search_keys → %s", len(id_to_slug), ss.NEWS_SOURCES_PATH)
