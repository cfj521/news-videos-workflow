from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"  # 仓库根目录


class TimeRange(str, Enum):
    ONE_DAY = "1d"
    THREE_DAYS = "3d"
    SEVEN_DAYS = "7d"
    FIFTEEN_DAYS = "15d"
    ONE_MONTH = "1m"


class VideoRoute(str, Enum):
    HYPERFRAMES = "hyperframes"
    COMFYUI = "comfyui"


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
    provider: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    max_length: int = 150


class PipelineCfg(BaseModel):
    default_time_range: str = "7d"
    default_max_articles: int = 5
    default_video_route: str = "comfyui"
    default_language: str = "zh"
    dedup_lookback: str = "30d"


class VideoCfg(BaseModel):
    fps: str = "30"
    scene_gap_ms: int = 500
    transition: str = "crossfade"
    subtitle_font_size: int = 48  # 字幕字号（px，按渲染分辨率计）
    subtitle_max_lines: int = 2  # 单条字幕最多显示行数，用于自动切分长句


class InfraCfg(BaseModel):
    database_url: str = "sqlite:///../data/news_videos.db"
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


class WorkflowParams(BaseModel):
    steps: int
    cfg: float


class ComfyuiCfg(BaseModel):
    workflows_dir: str = "comfyui/workflows/api"
    default_negative: str = "模糊, 丑陋, 变形, 低质量, 水印"
    server_url: str = "http://127.0.0.1:8188"  # 图片与视频生成共用一个 ComfyUI 地址
    # ---- 图片生成（图片 provider 选 comfyui 时生效）----
    image_workflow: str = "z_image"
    image_params: dict[str, WorkflowParams] = {
        "z_image": WorkflowParams(steps=9, cfg=1.0),   # turbo 蒸馏，低步数
        "qwen": WorkflowParams(steps=20, cfg=2.5),
    }
    # ---- 视频生成 ----
    video_workflow: str = "wan5b"
    video_fps: int = 24
    # 每种视频 workflow 一组生成参数。wan5b/wan14b 的 steps、cfg 均可调；
    # wan14b_lightx2v 锁死（加速 LoRA 固定 4 步）、ltx 仅 cfg 生效（蒸馏固定 sigmas）。
    video_params: dict[str, WorkflowParams] = {
        "wan5b": WorkflowParams(steps=30, cfg=5.0),
        "wan14b": WorkflowParams(steps=20, cfg=3.5),
        "wan14b_lightx2v": WorkflowParams(steps=4, cfg=1.0),
        "ltx": WorkflowParams(steps=4, cfg=1.0),
    }


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
    # Docker bind 挂载 ./config.yaml 时，若宿主机缺少该文件，Docker 会自动建一个
    # 空目录顶替，导致这里 open() 抛 IsADirectoryError 且报错难懂。提前给出可操作的提示。
    if path.is_dir():
        raise RuntimeError(
            f"配置文件 {path} 是一个目录，通常是 Docker 在宿主机缺少 config.yaml 时"
            f"自动创建了挂载目录。请在项目根目录执行 `cp config.yaml.example config.yaml` "
            f"生成配置文件，再用 `docker compose up -d --force-recreate backend` 重建容器。"
        )
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
