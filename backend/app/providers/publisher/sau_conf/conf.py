"""自带的 social-auto-upload `conf` 模块。

SAU 的 sau_cli/uploader 在 import 期 `from conf import BASE_DIR, ...`，但其包未附带可用 conf。
本文件随仓库走，由 sau_runner 注入子进程 PYTHONPATH，使 SAU 把 cookie/二维码落到仓库根
publish_cookies/ 下（cookies/{platform}_{account}.json）。
"""
from pathlib import Path

# 本文件: backend/app/providers/publisher/sau_conf/conf.py
# parents[5] = 仓库根
BASE_DIR = Path(__file__).resolve().parents[5] / "publish_cookies"

# 不使用小红书，但 sau_cli 启动会 import 其模块，提供占位避免 ImportError
XHS_SERVER = "http://127.0.0.1:11901"

# 空字符串 → uploader 走 channel="chrome"（需系统 Google Chrome）；
# 也可填 chrome/chromium 可执行路径覆盖
LOCAL_CHROME_PATH = ""
LOCAL_CHROME_HEADLESS = True
DEBUG_MODE = False
