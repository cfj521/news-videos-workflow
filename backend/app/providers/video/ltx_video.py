"""LTX-2.3 VideoClipProvider — generates video clips from image + prompt."""

import os
import time

from app.logging import get_logger
from app.providers.base import AssetResult, VideoClipProvider

log = get_logger("provider.video.ltx")


def _duration_to_frames(duration_sec: float, fps: float = 25.0) -> int:
    raw = duration_sec * fps
    n = max(1, round((raw - 1) / 8))
    return min(8 * n + 1, 257)


def _snap_to_32(value: int) -> int:
    return max(32, round(value / 32) * 32)


class LTXVideoProvider(VideoClipProvider):
    def __init__(
        self,
        model_dir: str = "",
        checkpoint: str = "ltx-2.3-22b-distilled-1.1.safetensors",
        upsampler: str = "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
        distilled_lora: str = "ltx-2.3-22b-distilled-lora-384.safetensors",
        lora_strength: float = 0.6,
        gemma_dir: str = "",
        inference_steps: int = 8,
        cfg_scale: float = 3.0,
        stg_scale: float = 1.0,
        fps: float = 25.0,
        use_fp8: bool = True,
    ):
        self._model_dir = model_dir
        self._checkpoint = checkpoint
        self._upsampler = upsampler
        self._distilled_lora = distilled_lora
        self._lora_strength = lora_strength
        self._gemma_dir = gemma_dir
        self._inference_steps = inference_steps
        self._cfg_scale = cfg_scale
        self._stg_scale = stg_scale
        self._fps = fps
        self._use_fp8 = use_fp8
        self._pipeline = None

    def _resolve(self, filename: str) -> str:
        if os.path.isabs(filename):
            return filename
        return os.path.join(self._model_dir, filename)

    def _ensure_pipeline(self):
        if self._pipeline is not None:
            return

        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

        from ltx_core.loader import LTXV_LORA_COMFY_RENAMING_MAP, LoraPathStrengthAndSDOps
        from ltx_pipelines.ti2vid_two_stages import TI2VidTwoStagesPipeline

        kwargs = dict(
            checkpoint_path=self._resolve(self._checkpoint),
            distilled_lora=[
                LoraPathStrengthAndSDOps(
                    self._resolve(self._distilled_lora),
                    self._lora_strength,
                    LTXV_LORA_COMFY_RENAMING_MAP,
                ),
            ],
            spatial_upsampler_path=self._resolve(self._upsampler),
            gemma_root=self._gemma_dir or os.path.join(self._model_dir, "gemma"),
        )

        if self._use_fp8:
            try:
                from ltx_core.quantization.policy import QuantizationPolicy
                kwargs["quantization"] = QuantizationPolicy.fp8_cast()
                log.info("FP8 quantization enabled")
            except Exception:
                log.warning("FP8 quantization not available, using full precision")

        log.info("Loading LTX pipeline from %s", self._model_dir)
        t0 = time.time()
        self._pipeline = TI2VidTwoStagesPipeline(**kwargs)
        log.info("LTX pipeline loaded in %.1fs", time.time() - t0)

    async def generate(
        self,
        image_path: str,
        prompt: str,
        duration: float,
        resolution: str = "768x512",
        output_path: str = "",
    ) -> AssetResult:
        self._ensure_pipeline()

        from ltx_core.components.guiders import MultiModalGuiderParams
        from ltx_pipelines.ti2vid_two_stages import ImageConditioningInput

        parts = resolution.split("x")
        width = _snap_to_32(int(parts[0])) if len(parts) >= 1 else 768
        height = _snap_to_32(int(parts[1])) if len(parts) >= 2 else 512
        num_frames = _duration_to_frames(duration, self._fps)

        video_guider = MultiModalGuiderParams(
            cfg_scale=self._cfg_scale, stg_scale=self._stg_scale, stg_blocks=[29],
            rescale_scale=0.7, modality_scale=3.0, skip_step=0,
        )
        audio_guider = MultiModalGuiderParams(
            cfg_scale=7.0, stg_scale=self._stg_scale, stg_blocks=[29],
            rescale_scale=0.7, modality_scale=3.0, skip_step=0,
        )

        images = []
        if image_path:
            images = [ImageConditioningInput(path=image_path, frame_index=0, strength=1.0, downsample_factor=33)]

        log.info("Generating clip: %dx%d %d frames (%.1fs) steps=%d prompt=%s",
                 width, height, num_frames, num_frames / self._fps, self._inference_steps, prompt[:60])
        t0 = time.time()

        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._pipeline(
            prompt=prompt,
            output_path=output_path,
            seed=42,
            height=height,
            width=width,
            num_frames=num_frames,
            frame_rate=self._fps,
            num_inference_steps=self._inference_steps,
            video_guider_params=video_guider,
            audio_guider_params=audio_guider,
            images=images,
        ))

        elapsed = time.time() - t0
        duration_ms = int((num_frames / self._fps) * 1000)
        log.info("Clip generated in %.1fs → %s", elapsed, output_path)

        return AssetResult(file_path=output_path, duration_ms=duration_ms)
