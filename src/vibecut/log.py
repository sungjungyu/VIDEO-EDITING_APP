"""로그 설정. print 대신 logging을 쓰고, 작업(job)마다 따로 로그 파일을 남긴다."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


def setup_logging(level: str = "INFO") -> None:
    """콘솔 로그를 한 번만 설정한다. Windows 한글 콘솔(cp949)에서도 깨지지 않게 UTF-8로 내보낸다."""
    global _configured
    if _configured:
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(FORMAT, datefmt="%H:%M:%S"))
    root = logging.getLogger("vibecut")
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True


def job_logger(job_id: str, log_path: Path) -> logging.Logger:
    """작업 하나의 로그를 log_path에도 남기는 로거. 작업이 끝나면 close_job_logger로 닫는다."""
    logger = logging.getLogger(f"vibecut.job.{job_id}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def close_job_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
