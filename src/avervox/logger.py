"""Logging for AverVOX — file log + in-memory ring buffer."""

from __future__ import annotations

import logging
import os
from collections import deque
from pathlib import Path
from typing import Deque, List

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "avervox"
LOG_FILE = DATA_DIR / "avervox.log"
RING_BUFFER_SIZE = 500

_ring_buffer: Deque[str] = deque(maxlen=RING_BUFFER_SIZE)


class RingBufferHandler(logging.Handler):
    """Logging handler that appends formatted records to an in-memory ring buffer."""

    def __init__(self, ring: Deque[str]) -> None:
        super().__init__()
        self._ring = ring

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._ring.append(msg)
        except Exception:
            self.handleError(record)


def get_log_lines() -> List[str]:
    """Return a snapshot of the current ring buffer contents."""
    return list(_ring_buffer)


def setup_logging(level: int = logging.DEBUG) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler.setLevel(level)

        ring_handler = RingBufferHandler(_ring_buffer)
        ring_handler.setFormatter(fmt)
        ring_handler.setLevel(level)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        stream_handler.setLevel(logging.WARNING)

        root.addHandler(file_handler)
        root.addHandler(ring_handler)
        root.addHandler(stream_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
