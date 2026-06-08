"""news_sources.yaml 读写：信息源（slug 主键）+ 搜索 key。

结构：
    search_keys: {tavily_key, brave_key, serper_key}
    sources:
      <slug>: {name, type, url, category, language, priority, enabled, tier, pinned, config: {...}}
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from app.store import _io
from app.store._slug import slugify, unique_slug

NEWS_SOURCES_PATH = Path(__file__).resolve().parents[3] / "news_sources.yaml"

_DEFAULT_SEARCH_KEYS = {"tavily_key": "", "brave_key": "", "serper_key": ""}

_UPDATABLE = (
    "name", "type", "url", "category", "language",
    "priority", "enabled", "tier", "pinned", "config",
)


class SourceData(BaseModel):
    """单个信息源。slug 为主键（YAML key），config 为内联 dict（原 config_json）。"""
    slug: str
    name: str
    type: str
    url: str = ""
    category: str = "general"
    language: str = "en"
    priority: int = 5
    enabled: bool = True
    tier: str = "free"
    pinned: bool = False
    config: dict = {}


def _read() -> dict:
    return _io.load_yaml(NEWS_SOURCES_PATH)


def list_sources() -> list[SourceData]:
    raw = _read().get("sources", {}) or {}
    out = [SourceData(slug=slug, **(slot or {})) for slug, slot in raw.items()]
    out.sort(key=lambda s: s.priority)
    return out


def get_source(slug: str) -> SourceData | None:
    slot = (_read().get("sources", {}) or {}).get(slug)
    return SourceData(slug=slug, **slot) if slot else None


def create_source(*, name: str, type: str, url: str = "", category: str = "general",
                  language: str = "en", priority: int = 5, enabled: bool = True,
                  tier: str = "free", pinned: bool = False, config: dict | None = None,
                  slug: str | None = None) -> SourceData:
    with _io.file_lock(NEWS_SOURCES_PATH):
        data = _read()
        sources = data.setdefault("sources", {})
        existing = set(sources.keys())
        new_slug = slug or unique_slug(slugify(name), existing, type or "source")
        if new_slug in existing:
            new_slug = unique_slug(new_slug, existing, type or "source")
        rec = {"name": name, "type": type, "url": url, "category": category,
               "language": language, "priority": priority, "enabled": enabled,
               "tier": tier, "pinned": pinned, "config": config or {}}
        sources[new_slug] = rec
        _io.save_yaml(NEWS_SOURCES_PATH, data)
        return SourceData(slug=new_slug, **rec)


def update_source(slug: str, patch: dict) -> SourceData | None:
    with _io.file_lock(NEWS_SOURCES_PATH):
        data = _read()
        sources = data.get("sources", {}) or {}
        if slug not in sources:
            return None
        slot = sources[slug]
        for k in _UPDATABLE:
            if k in patch and patch[k] is not None:
                slot[k] = patch[k]
        sources[slug] = slot
        data["sources"] = sources
        _io.save_yaml(NEWS_SOURCES_PATH, data)
        return SourceData(slug=slug, **slot)


def delete_source(slug: str) -> bool:
    with _io.file_lock(NEWS_SOURCES_PATH):
        data = _read()
        sources = data.get("sources", {}) or {}
        if slug not in sources:
            return False
        del sources[slug]
        data["sources"] = sources
        _io.save_yaml(NEWS_SOURCES_PATH, data)
        return True


def batch_update(
    slugs: list[str], *,
    enabled: bool | None = None,
    pinned: bool | None = None,
    priority_map: dict[str, int] | None = None,
) -> list[SourceData]:
    with _io.file_lock(NEWS_SOURCES_PATH):
        data = _read()
        sources = data.get("sources", {}) or {}
        changed: list[SourceData] = []
        for slug in slugs:
            if slug not in sources:
                continue
            slot = sources[slug]
            if enabled is not None:
                slot["enabled"] = enabled
            if pinned is not None:
                slot["pinned"] = pinned
            if priority_map and slug in priority_map:
                slot["priority"] = priority_map[slug]
            sources[slug] = slot
            changed.append(SourceData(slug=slug, **slot))
        data["sources"] = sources
        _io.save_yaml(NEWS_SOURCES_PATH, data)
        return changed


def load_search_keys() -> dict:
    sk = _read().get("search_keys") or {}
    return {**_DEFAULT_SEARCH_KEYS, **sk}


def save_search_keys(keys: dict) -> None:
    with _io.file_lock(NEWS_SOURCES_PATH):
        data = _read()
        data["search_keys"] = {**_DEFAULT_SEARCH_KEYS, **(keys or {})}
        _io.save_yaml(NEWS_SOURCES_PATH, data)
