"""작업 실행 맥락: 분석·렌더 같은 긴 작업이 진행률을 알리고, 취소를 확인하고, 단계별 시간과 AI 사용량을 남긴다.

작업 큐(services.jobs.JobContext)와 명령줄(ConsoleContext)이 같은 작업 함수를 그대로 쓸 수 있게
'알리는 방법'만 다르고 나머지는 같다.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager

from ..ai.client import Usage
from ..errors import Canceled


class RunContext:
    def __init__(self, job_id: str | None = None, cancel: threading.Event | None = None,
                 logger: logging.Logger | None = None):
        self.job_id = job_id or uuid.uuid4().hex[:12]
        self.cancel = cancel or threading.Event()
        self.log = logger or logging.getLogger("vibecut.run")
        self.usage = Usage()
        self.metrics: dict = {"stages": {}}

    def progress(self, percent: float, stage: str | None = None, message: str | None = None) -> None:
        """진행률(0~100)과 단계·메시지를 알린다. 알리는 방법은 하위 클래스가 정한다."""

    def sub(self, lo: float, hi: float, stage: str | None = None) -> Callable[[float], None]:
        """0~1 진행률을 lo~hi%로 옮겨 알리는 콜백 (ffmpeg 진행률 등)."""
        return lambda fraction: self.progress(lo + (hi - lo) * fraction, stage)

    def check(self) -> None:
        if self.cancel.is_set():
            raise Canceled()

    @contextmanager
    def stage(self, name: str):
        started = time.time()
        try:
            yield
        finally:
            self.metrics["stages"][name] = round(time.time() - started, 2)


class ConsoleContext(RunContext):
    """터미널 한 줄에 진행률을 덮어써 보여 준다 (명령줄)."""

    def __init__(self):
        super().__init__(logger=logging.getLogger("vibecut.cli"))
        self._last = ""

    def progress(self, percent: float, stage: str | None = None, message: str | None = None) -> None:
        line = f"{percent:5.1f}%  {stage or ''} {message or ''}".rstrip()
        if line != self._last:
            print(f"\r{line[:100]:<100}", end="", flush=True)
            self._last = line
