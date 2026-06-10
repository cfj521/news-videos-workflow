"""登录子进程：在隔离进程内 import SAU 跑扫码登录，二维码 data URL 与结果以 JSON 行打到 stdout。

由 sau_runner.run_login 用 `python -m app.providers.publisher.sau_login_worker <platform> <account>` 启动，
PYTHONPATH 已注入 sau_conf（使 SAU 的 `import conf` 命中）。主进程不 import 本模块的 SAU 依赖。

stdout 协议（每行一个 JSON）：
  {"qr": "<data-url>"}                     # 二维码就绪/刷新
  {"result": "success|timeout|failed", "error": "<可选>"}   # 终态
"""
from __future__ import annotations

import asyncio
import json
import sys

_SETUP = {"douyin": "douyin_setup", "kuaishou": "ks_setup"}


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _setup_name(platform: str) -> str:
    if platform not in _SETUP:
        raise ValueError(f"unsupported platform: {platform}")
    return _SETUP[platform]


async def _run(platform: str, account: str) -> int:
    # 仅在子进程内 import，主进程永不触达
    if platform == "douyin":
        from uploader.douyin_uploader.main import douyin_setup as setup
    else:
        from uploader.ks_uploader.main import ks_setup as setup

    from sau_cli import resolve_account_file  # 用 SAU 自己的路径规则（受 conf.BASE_DIR 控制）
    account_file = str(resolve_account_file(platform, account))

    def on_qr(payload: dict) -> None:
        data_url = payload.get("image_data_url")
        if data_url:
            _emit({"qr": data_url})

    try:
        result = await setup(account_file, handle=True, return_detail=True,
                             qrcode_callback=on_qr, headless=True)
    except Exception as exc:  # noqa: BLE001
        _emit({"result": "failed", "error": str(exc)})
        return 1

    status = result.get("status") if isinstance(result, dict) else None
    if status == "success" or (isinstance(result, dict) and result.get("success")):
        _emit({"result": "success"})
        return 0
    if status == "timeout":
        _emit({"result": "timeout"})
        return 1
    _emit({"result": "failed", "error": (result.get("message") if isinstance(result, dict) else "登录失败")})
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 2:
        _emit({"result": "failed", "error": "usage: sau_login_worker <platform> <account>"})
        return 2
    platform, account = argv
    _setup_name(platform)  # 提前校验平台
    return asyncio.run(_run(platform, account))


if __name__ == "__main__":
    raise SystemExit(main())
