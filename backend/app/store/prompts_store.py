"""prompts.yaml 读写：提示词预设库（被 config.Settings.prompt_presets 注入）。

文件结构：
    active: 0            # 当前生效预设下标（0~4）
    presets:             # 固定 5 个
      - name: 预设 1
        values: {roundup_article: '...', roundup_article_en: '...', ...}
      - name: 预设 2
        values: {}
      ...
"""
from __future__ import annotations

from pathlib import Path

from app.config import PromptPresetsCfg
from app.store import _io

PROMPTS_PATH = Path(__file__).resolve().parents[3] / "prompts.yaml"


def load_presets() -> PromptPresetsCfg | None:
    """读取预设库；文件不存在返回 None（交由调用方迁移生成）。"""
    if not PROMPTS_PATH.exists():
        return None
    raw = _io.load_yaml(PROMPTS_PATH)
    return PromptPresetsCfg(**raw).normalized() if raw else PromptPresetsCfg()


def save_presets(presets: PromptPresetsCfg) -> None:
    """整体写入预设库（补足到 5 个、夹 active 后落盘）。"""
    with _io.file_lock(PROMPTS_PATH):
        _io.save_yaml(PROMPTS_PATH, presets.normalized().model_dump())
