from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


class ProviderError(Exception):
    """带服务源头上下文的 AI provider 调用异常，便于失败时定位是哪个服务/模型/地址出错。"""

    def __init__(self, service: str, provider: str, model: str = "", base_url: str = "", cause: Exception | None = None):
        self.service = service      # 文本生成 / 图片生成 / 语音合成 ...
        self.provider = provider    # openai / claude / edge-tts ...
        self.model = model
        self.base_url = base_url
        self.cause = cause
        super().__init__(str(cause) if cause is not None else service)


@dataclass
class RawArticleData:
    title: str
    content: str
    source_url: str
    source_name: str
    published_at: datetime | None = None
    author: str | None = None
    category: str = "general"
    language: str = "en"
    aggregator_url: str = ""
    summary: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class SceneData:
    id: int
    narration: str
    image_prompt: str
    motion_prompt: str = ""
    duration_hint: float = 5.0


@dataclass
class AssetResult:
    file_path: str
    duration_ms: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class VideoResult:
    file_path: str
    thumbnail_path: str | None = None
    duration_ms: int = 0
    resolution: str = "1080x1920"
    file_size_bytes: int = 0


@dataclass
class PublishResult:
    platform: str
    status: str
    url: str | None = None
    error_message: str | None = None


class CollectorProvider(ABC):
    @abstractmethod
    async def collect(
        self,
        source_config: dict,
        time_range: str,
        max_items: int = 30,
    ) -> list[RawArticleData]: ...


class TextProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> str: ...


class ImageProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        size: str = "1080x1920",
        output_path: str = "",
    ) -> AssetResult: ...


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str = "",
        speed: float = 1.0,
        output_path: str = "",
    ) -> AssetResult: ...


class VideoClipProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        image_path: str,
        prompt: str,
        duration: float,
        resolution: str = "768x512",
        output_path: str = "",
    ) -> AssetResult: ...


class ComposerProvider(ABC):
    @abstractmethod
    async def compose(
        self,
        timeline_json: dict,
        assets_dir: str,
        output_path: str,
        resolution: str = "1080x1920",
    ) -> VideoResult: ...


class PublisherAdapter(ABC):
    @abstractmethod
    async def publish(
        self,
        video_path: str,
        thumbnail_path: str | None,
        title: str,
        description: str,
        tags: list[str],
    ) -> PublishResult: ...
