"""共通ロガー。全モジュールはこの get_logger() を通してログを出す。"""

import logging
import sys
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        # 二重にハンドラを付けない
        return logger

    logger.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(_LOG_DIR / "pipeline.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger
