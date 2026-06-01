from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


class TimeRange(str, Enum):
    ONE_DAY = "1d"
    THREE_DAYS = "3d"
    SEVEN_DAYS = "7d"
    FIFTEEN_DAYS = "15d"
    ONE_MONTH = "1m"


class VideoRoute(str, Enum):
    HYPERFRAMES = "hyperframes"
    LTX = "ltx"


class ProviderCfg(BaseModel):
    provider: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str = ""


class TTSCfg(BaseModel):
    provider: str = "edge-tts"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    voice: str = "zh-CN-XiaoxiaoNeural"
    speed: float = 1.0


class CollectorsCfg(BaseModel):
    tavily_key: str = ""
    brave_key: str = ""
    serper_key: str = ""


class YouTubeCfg(BaseModel):
    client_id: str = ""
    client_secret: str = ""


class SummaryCfg(BaseModel):
    enabled: bool = True  # 历史字段：摘要现按信息源组自动决定，此开关已不再生效
    provider: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    max_length: int = 150


class PipelineCfg(BaseModel):
    default_time_range: str = "7d"
    default_max_articles: int = 5
    default_video_route: str = "hyperframes"
    default_language: str = "zh"
    dedup_lookback: str = "30d"


class LTXCfg(BaseModel):
    model_dir: str = ""
    checkpoint: str = "ltx-2.3-22b-distilled-1.1.safetensors"
    upsampler: str = "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
    distilled_lora: str = "ltx-2.3-22b-distilled-lora-384.safetensors"
    lora_strength: float = 0.6
    gemma_dir: str = ""
    inference_steps: int = 8
    cfg_scale: float = 3.0
    stg_scale: float = 1.0
    fps: float = 25.0
    use_fp8: bool = True


class VideoCfg(BaseModel):
    resolution: str = "1080x1920"
    aspect_ratio: str = "9:16"
    fps: str = "30"
    scene_gap_ms: int = 500
    transition: str = "crossfade"


class InfraCfg(BaseModel):
    database_url: str = "sqlite:///../data/news_videos.db"
    redis_url: str = "redis://localhost:6379/0"
    data_dir: str = "../data"


class StorageCfg(BaseModel):
    # 工作目录：每个任务的半成品与成品（articles/script/assets/output）的根目录，每个任务一个子目录。
    # 留空 = 使用 data_dir/runs（向后兼容）。
    work_dir: str = ""
    # 成品输出目录：渲染完成后把最终 mp4/mp3 额外复制一份到此处归档。留空 = 不额外导出。
    output_dir: str = ""


class PromptsCfg(BaseModel):
    roundup_article: str = ""
    daily_batch: str = ""
    summary_meta: str = ""
    weekly_digest: str = ""
    image_regen: str = ""
    article_summary: str = ""
    news_scoring: str = ""


class ComfyuiCfg(BaseModel):
    workflows_dir: str = "comfyui/workflows/api"
    default_negative: str = "模糊, 丑陋, 变形, 低质量, 水印"


class Settings(BaseModel):
    infra: InfraCfg = InfraCfg()
    storage: StorageCfg = StorageCfg()
    text: ProviderCfg = ProviderCfg(provider="claude", base_url="https://api.anthropic.com", model="claude-sonnet-4-6")
    image: ProviderCfg = ProviderCfg(provider="openai", base_url="https://api.openai.com/v1", model="gpt-image-1")
    vision: ProviderCfg = ProviderCfg(provider="openai", base_url="https://api.openai.com/v1", model="gpt-4o")
    tts: TTSCfg = TTSCfg()
    summary: SummaryCfg = SummaryCfg()
    collectors: CollectorsCfg = CollectorsCfg()
    youtube: YouTubeCfg = YouTubeCfg()
    pipeline: PipelineCfg = PipelineCfg()
    video: VideoCfg = VideoCfg()
    ltx: LTXCfg = LTXCfg()
    comfyui: ComfyuiCfg = ComfyuiCfg()
    prompts: PromptsCfg = PromptsCfg()

    def runs_root(self) -> Path:
        """任务工作目录的根：配置了 storage.work_dir 用它，否则回退 data_dir/runs。"""
        return Path(self.storage.work_dir) if self.storage.work_dir else Path(self.infra.data_dir) / "runs"

    def ensure_data_dirs(self) -> None:
        base = Path(self.infra.data_dir)
        self.runs_root().mkdir(parents=True, exist_ok=True)
        (base / "history").mkdir(parents=True, exist_ok=True)
        if self.storage.output_dir:
            Path(self.storage.output_dir).mkdir(parents=True, exist_ok=True)

    # --- 兼容旧属性 ---
    @property
    def DATABASE_URL(self) -> str:
        return self.infra.database_url

    @property
    def DATA_DIR(self) -> str:
        return self.infra.data_dir


def _load_yaml(path: Path) -> dict[str, Any]:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        raw = _load_yaml(CONFIG_PATH)
        _settings = Settings(**raw)
        import logging
        logging.getLogger("nv.config").info("Loaded config from %s", CONFIG_PATH)
    return _settings


def save_settings(settings: Settings) -> None:
    global _settings
    _settings = settings
    _save_yaml(CONFIG_PATH, settings.model_dump())
    import logging
    logging.getLogger("nv.config").info("Saved config to %s", CONFIG_PATH)


def reload_settings() -> Settings:
    global _settings
    _settings = None
    return get_settings()
