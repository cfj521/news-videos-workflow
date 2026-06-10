"""ComfyUI 远程唤醒（Wake-on-LAN）+ 就绪等待。

部署形态：本 app 跑在无 GPU 的家庭服务器，ComfyUI 在另一台机器（WSL）上、平时休眠/关机省电。
流水线用到 ComfyUI 前调用 ensure_comfyui_ready()：
  1. 先探活（GET /system_stats）——在线直接返回；
  2. 不在线且启用唤醒：发 WoL 魔术包，轮询至就绪（期间隔一会儿补发一次，防丢包）；
  3. 超时仍不就绪 → 抛 ProviderError，由上层标记 run 失败（与「ComfyUI 不兜底」一致）。

进程自启（任务计划）与网络可达（mirrored 网络 / portproxy）由 ComfyUI 所在机器自行保证。
"""
from __future__ import annotations

import asyncio
import os
import socket

import httpx

from app.config import Settings
from app.logging import get_logger
from app.providers.base import ProviderError

log = get_logger("provider.comfyui.wake")

_REWAKE_EVERY = 15  # 轮询期间每隔约 N 秒补发一次魔术包（部分网卡会丢包）


def _parse_mac(mac: str) -> bytes:
    """把 AA:BB:CC:DD:EE:FF / AA-BB-.. / 纯 hex 统一解析成 6 字节。"""
    hexs = mac.replace(":", "").replace("-", "").replace(".", "").strip()
    if len(hexs) != 12:
        raise ValueError(f"非法 MAC 地址: {mac!r}")
    return bytes.fromhex(hexs)


def send_magic_packet(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """发送 Wake-on-LAN 魔术包：6×0xFF + 16×MAC，UDP 广播到 (broadcast, port)。"""
    payload = b"\xff" * 6 + _parse_mac(mac) * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(payload, (broadcast or "255.255.255.255", port or 9))


def _comfyui_url(cfg: Settings) -> str:
    # 与 ComfyUIClient 一致：NV_COMFYUI_URL 环境变量优先（docker 注入 host.docker.internal）
    return (os.getenv("NV_COMFYUI_URL") or cfg.comfyui.server_url).rstrip("/")


async def _probe(url: str, timeout: float = 3.0) -> bool:
    """探活：GET {url}/system_stats，2xx 视为在线；任何异常视为不可达。"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(f"{url}/system_stats")
            return r.status_code == 200
    except Exception:
        return False


async def ensure_comfyui_ready(cfg: Settings) -> None:
    """确保 ComfyUI 可用；不可用且启用唤醒则发 WoL 并轮询至就绪，超时抛 ProviderError。

    未启用唤醒（wake.enabled=False 或未填 mac）时本函数直接返回，保持原行为——
    由后续真正的 provider 调用去暴露不可达（不在此处提前报错）。
    """
    url = _comfyui_url(cfg)
    wake = cfg.comfyui.wake
    if not wake.enabled or not wake.mac:
        return
    if await _probe(url):
        return

    log.info("ComfyUI 不可达，发送 Wake-on-LAN 唤醒 %s（广播 %s:%d），最长等待 %ds",
             wake.mac, wake.broadcast, wake.port, wake.ready_timeout)
    try:
        send_magic_packet(wake.mac, wake.broadcast, wake.port)
    except ValueError as e:
        raise ProviderError(service="ComfyUI", provider="comfyui", base_url=url, cause=e) from e

    waited = 0.0
    last_rewake = 0.0
    interval = max(0.5, wake.poll_interval)
    while waited < wake.ready_timeout:
        await asyncio.sleep(interval)
        waited += interval
        if await _probe(url):
            log.info("ComfyUI 已就绪（等待 %.0fs）", waited)
            return
        if waited - last_rewake >= _REWAKE_EVERY:  # 期间补发魔术包，防首包丢失
            send_magic_packet(wake.mac, wake.broadcast, wake.port)
            last_rewake = waited

    raise ProviderError(
        service="ComfyUI", provider="comfyui", base_url=url,
        cause=RuntimeError(f"远程唤醒后 {wake.ready_timeout}s 内 ComfyUI 仍未就绪"),
    )
