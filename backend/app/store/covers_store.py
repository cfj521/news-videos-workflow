"""covers.yaml 读写：视频封面预设库（被 config.Settings.cover_presets 注入）。

文件结构：
    active: 0            # 当前生效预设下标（0~2）
    presets:             # 固定 3 个
      - name: 封面 1
        values: {enabled: false, image: '...', title_template: '...', ...}
      - name: 封面 2
        values: {}
      - name: 封面 3
        values: {}
"""
from __future__ import annotations

from pathlib import Path

from app.config import CoverPresetsCfg
from app.store import _io

COVERS_PATH = Path(__file__).resolve().parents[3] / "covers.yaml"


def load_presets() -> CoverPresetsCfg | None:
    """读取预设库；文件不存在返回 None（交由调用方迁移生成）。"""
    if not COVERS_PATH.exists():
        return None
    raw = _io.load_yaml(COVERS_PATH)
    return CoverPresetsCfg(**raw).normalized() if raw else CoverPresetsCfg()


def save_presets(presets: CoverPresetsCfg) -> None:
    """整体写入预设库（补足到 3 个、夹 active 后落盘）。"""
    with _io.file_lock(COVERS_PATH):
        _io.save_yaml(COVERS_PATH, presets.normalized().model_dump())
