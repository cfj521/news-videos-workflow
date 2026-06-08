"""slug 生成：实体（信息源/发布账号）的 YAML 主键。

英文名转小写下划线；中文/全特殊字符名 slugify 得空串，由调用方用 fallback（platform/type）兜底。
"""
from __future__ import annotations

import re


def slugify(name: str) -> str:
    """转 [a-z0-9_]；非字母数字折叠为单个下划线，去首尾下划线。中文等无 ASCII 字母数字 → 空串。"""
    return re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")


def unique_slug(base: str, existing: set[str], fallback: str) -> str:
    """在 existing 内取唯一 slug。base 为空用 fallback；冲突则 base_1、base_2… 递增。"""
    base = base or fallback
    if base not in existing:
        return base
    i = 1
    while f"{base}_{i}" in existing:
        i += 1
    return f"{base}_{i}"
