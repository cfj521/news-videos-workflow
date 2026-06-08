"""publish_targets.yaml 读写：发布账号（slug 主键）+ YouTube OAuth client。

结构：
    youtube_oauth_client: {client_id, client_secret}
    targets:
      <slug>: {name, platform, enabled, created_at, config: {...}}
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from app.store import _io
from app.store._slug import slugify, unique_slug

TARGETS_PATH = Path(__file__).resolve().parents[3] / "publish_targets.yaml"

_DEFAULT_YT_CLIENT = {"client_id": "", "client_secret": ""}


class TargetData(BaseModel):
    """单个发布账号。slug 为主键（YAML key），config 为平台凭证内联 dict。"""

    slug: str
    name: str
    platform: str
    enabled: bool = True
    created_at: str = ""
    config: dict = {}


def _read() -> dict:
    return _io.load_yaml(TARGETS_PATH)


def list_targets() -> list[TargetData]:
    """返回所有发布账号列表，文件不存在时返回空列表。"""
    raw = _read().get("targets", {}) or {}
    return [TargetData(slug=slug, **(slot or {})) for slug, slot in raw.items()]


def get_target(slug: str) -> TargetData | None:
    """按 slug 查找发布账号，不存在返回 None。"""
    slot = (_read().get("targets", {}) or {}).get(slug)
    return TargetData(slug=slug, **slot) if slot else None


def create_target(
    *,
    name: str,
    platform: str,
    config: dict,
    enabled: bool = True,
    slug: str | None = None,
) -> TargetData:
    """新建发布账号。slug 未指定时从 name 生成，冲突自动追加数字后缀。"""
    with _io.file_lock(TARGETS_PATH):
        data = _read()
        targets = data.setdefault("targets", {})
        existing = set(targets.keys())
        # 优先用调用方指定的 slug，否则从 name 生成
        new_slug = slug or unique_slug(slugify(name), existing, platform)
        # 若指定 slug 已存在，仍走 unique_slug 产生唯一后缀
        if new_slug in existing:
            new_slug = unique_slug(new_slug, existing, platform)
        rec = {
            "name": name,
            "platform": platform,
            "enabled": enabled,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config": config or {},
        }
        targets[new_slug] = rec
        _io.save_yaml(TARGETS_PATH, data)
        return TargetData(slug=new_slug, **rec)


def update_target(slug: str, patch: dict) -> TargetData | None:
    """部分更新；patch 可含 name/platform/enabled/config。

    返回更新后的 TargetData，slug 不存在返回 None。
    """
    with _io.file_lock(TARGETS_PATH):
        data = _read()
        targets = data.get("targets", {}) or {}
        if slug not in targets:
            return None
        slot = targets[slug]
        for k in ("name", "platform", "enabled", "config"):
            if k in patch and patch[k] is not None:
                slot[k] = patch[k]
        targets[slug] = slot
        data["targets"] = targets
        _io.save_yaml(TARGETS_PATH, data)
        return TargetData(slug=slug, **slot)


def delete_target(slug: str) -> bool:
    """删除发布账号，存在返回 True，不存在返回 False。"""
    with _io.file_lock(TARGETS_PATH):
        data = _read()
        targets = data.get("targets", {}) or {}
        if slug not in targets:
            return False
        del targets[slug]
        data["targets"] = targets
        _io.save_yaml(TARGETS_PATH, data)
        return True


def load_youtube_client() -> dict:
    """读取 YouTube OAuth client 配置，缺失字段用空串兜底。"""
    yc = _read().get("youtube_oauth_client") or {}
    return {**_DEFAULT_YT_CLIENT, **yc}


def save_youtube_client(client: dict) -> None:
    """写入 YouTube OAuth client 配置。"""
    with _io.file_lock(TARGETS_PATH):
        data = _read()
        data["youtube_oauth_client"] = {**_DEFAULT_YT_CLIENT, **(client or {})}
        _io.save_yaml(TARGETS_PATH, data)
