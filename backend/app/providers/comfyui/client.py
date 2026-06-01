import asyncio
import json
import time
import uuid

import httpx

from app.logging import get_logger
from app.providers.base import ProviderError

log = get_logger("provider.comfyui.client")


class ComfyUIClient:
    def __init__(self, server_url: str = "http://127.0.0.1:8188", timeout: float = 600.0, poll_interval: float = 1.5):
        self._url = server_url.rstrip("/")
        self._timeout = timeout
        self._poll = poll_interval

    def _err(self, cause):
        return ProviderError(service="ComfyUI", provider="comfyui", base_url=self._url, cause=cause)

    async def submit(self, prompt_graph: dict) -> str:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self._url}/prompt", json={"prompt": prompt_graph, "client_id": uuid.uuid4().hex})
                r.raise_for_status()
                pid = r.json().get("prompt_id")
        except ProviderError:
            raise
        except Exception as e:
            raise self._err(e) from e
        if not pid:
            raise self._err(RuntimeError("no prompt_id in /prompt response"))
        return pid

    async def wait(self, prompt_id: str) -> dict:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=30) as c:
            while time.time() - t0 < self._timeout:
                r = await c.get(f"{self._url}/history/{prompt_id}")
                r.raise_for_status()
                hist = r.json()
                if prompt_id in hist:
                    entry = hist[prompt_id]
                    if entry.get("status", {}).get("status_str") == "error":
                        msgs = entry.get("status", {}).get("messages", [])
                        raise self._err(RuntimeError(json.dumps(msgs, ensure_ascii=False)[:500]))
                    return entry.get("outputs", {})
                await asyncio.sleep(self._poll)
        raise self._err(RuntimeError(f"timeout {self._timeout}s waiting prompt {prompt_id}"))

    async def fetch(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.get(f"{self._url}/view", params={"filename": filename, "subfolder": subfolder, "type": folder_type})
                r.raise_for_status()
                return r.content
        except ProviderError:
            raise
        except Exception as e:
            raise self._err(e) from e

    async def upload_image(self, image_path: str) -> str:
        import os
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                with open(image_path, "rb") as fh:
                    files = {"image": (os.path.basename(image_path), fh, "image/png")}
                    r = await c.post(f"{self._url}/upload/image", files=files, data={"overwrite": "true"})
                    r.raise_for_status()
                    j = r.json()
        except ProviderError:
            raise
        except Exception as e:
            raise self._err(e) from e
        name = j.get("name")
        if not name:
            raise self._err(RuntimeError(f"upload no name: {j}"))
        sub = j.get("subfolder") or ""
        return f"{sub}/{name}" if sub else name

    async def run(self, prompt_graph: dict) -> list[dict]:
        outputs = await self.wait(await self.submit(prompt_graph))
        files: list[dict] = []
        for node_out in outputs.values():
            for kind in ("images", "gifs", "videos"):
                for f in node_out.get(kind, []):
                    files.append({"kind": kind, "filename": f.get("filename"),
                                  "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")})
        return files
