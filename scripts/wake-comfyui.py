#!/usr/bin/env python3
"""ComfyUI 远程唤醒（Wake-on-LAN）测试脚本 —— 独立可跑，不依赖后端包。

用途：在部署机（无 GPU 家庭服务器）上手动验证能否唤醒 ComfyUI 所在机器并等到 :8188 就绪。

用法：
    # 读取仓库根 config.yaml 的 comfyui.wake / comfyui.server_url 作默认值，发包并等待就绪
    python scripts/wake-comfyui.py

    # 全部用命令行参数（无需 config.yaml）
    python scripts/wake-comfyui.py --mac AA:BB:CC:DD:EE:FF --broadcast 192.168.1.255 \
        --url http://192.168.1.50:8188 --timeout 180

    # 只发魔术包、不等待就绪
    python scripts/wake-comfyui.py --no-wait

注意：WoL 是二层广播，发包机与目标机须在同一局域网段；目标机需在 BIOS/网卡开启 WoL。
"""
from __future__ import annotations

import argparse
import socket
import sys
import time
import urllib.request
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


def load_defaults() -> dict:
    """尽力从 config.yaml 读取 comfyui.server_url 与 comfyui.wake 作为默认值；读不到返回空。"""
    try:
        import yaml  # PyYAML 是项目依赖；独立运行若没有则跳过
    except ImportError:
        return {}
    if not CONFIG_PATH.exists():
        return {}
    try:
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 读取 {CONFIG_PATH} 失败：{e}", file=sys.stderr)
        return {}
    comfy = raw.get("comfyui", {}) or {}
    wake = comfy.get("wake", {}) or {}
    return {
        "url": comfy.get("server_url", ""),
        "mac": wake.get("mac", ""),
        "broadcast": wake.get("broadcast", "255.255.255.255"),
        "port": wake.get("port", 9),
        "timeout": wake.get("ready_timeout", 180),
        "interval": wake.get("poll_interval", 3),
    }


def parse_mac(mac: str) -> bytes:
    hexs = mac.replace(":", "").replace("-", "").replace(".", "").strip()
    if len(hexs) != 12:
        raise ValueError(f"非法 MAC 地址: {mac!r}")
    return bytes.fromhex(hexs)


def send_magic_packet(mac: str, broadcast: str, port: int) -> None:
    payload = b"\xff" * 6 + parse_mac(mac) * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(payload, (broadcast or "255.255.255.255", port or 9))
    print(f"[wol] 已发送魔术包 → {mac}  (广播 {broadcast}:{port})")


def probe(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/system_stats", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    d = load_defaults()
    p = argparse.ArgumentParser(description="ComfyUI Wake-on-LAN 测试")
    p.add_argument("--mac", default=d.get("mac", ""), help="目标机网卡 MAC")
    p.add_argument("--broadcast", default=d.get("broadcast", "255.255.255.255"), help="子网广播地址")
    p.add_argument("--port", type=int, default=int(d.get("port", 9)), help="WoL 端口（9/7）")
    p.add_argument("--url", default=d.get("url", ""), help="ComfyUI 地址，如 http://192.168.1.50:8188")
    p.add_argument("--timeout", type=int, default=int(d.get("timeout", 180)), help="等待就绪最长秒数")
    p.add_argument("--interval", type=float, default=float(d.get("interval", 3)), help="就绪轮询间隔秒")
    p.add_argument("--no-wait", action="store_true", help="只发包，不等待就绪")
    args = p.parse_args()

    if not args.mac:
        print("[error] 未提供 MAC（命令行 --mac 或 config.yaml 的 comfyui.wake.mac）", file=sys.stderr)
        return 2

    # 已在线就不必唤醒
    if args.url and probe(args.url):
        print(f"[ok] ComfyUI 已在线：{args.url}")
        return 0

    try:
        send_magic_packet(args.mac, args.broadcast, args.port)
    except ValueError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    if args.no_wait or not args.url:
        if not args.url:
            print("[info] 未提供 --url，跳过就绪等待（仅发包）")
        return 0

    print(f"[wait] 轮询 {args.url}/system_stats，最长 {args.timeout}s …")
    waited = 0.0
    last_rewake = 0.0
    interval = max(0.5, args.interval)
    while waited < args.timeout:
        time.sleep(interval)
        waited += interval
        if probe(args.url):
            print(f"[ok] ComfyUI 已就绪（等待 {waited:.0f}s）")
            return 0
        print(f"  …{waited:.0f}s 仍未就绪", end="\r", flush=True)
        if waited - last_rewake >= 15:  # 期间补发，防丢包
            send_magic_packet(args.mac, args.broadcast, args.port)
            last_rewake = waited

    print(f"\n[fail] {args.timeout}s 内 ComfyUI 仍未就绪", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
