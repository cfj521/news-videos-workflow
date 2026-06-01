from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "logs"
GLOBAL_LOG = LOG_DIR / "app.log"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5
FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
FMT_FILE = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_global_logger(level: str = "INFO") -> logging.Logger:
    root = logging.getLogger("nv")
    if root.handlers:
        return root
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter(FMT, datefmt=DATEFMT))
    root.addHandler(console)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(str(GLOBAL_LOG), maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(FMT_FILE, datefmt=DATEFMT))
    root.addHandler(fh)

    return root


def get_run_logger(run_id: int, run_dir: str | Path) -> logging.Logger:
    name = f"nv.run.{run_id}"
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    fh = logging.FileHandler(str(run_dir / "pipeline.log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(FMT_FILE, datefmt=DATEFMT))
    logger.addHandler(fh)
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"nv.{name}")
