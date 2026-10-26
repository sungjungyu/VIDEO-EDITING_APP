"""렌더 실행: 컴파일 → 작업 폴더 준비 → ffmpeg(진행률·취소) → 결과 길이 검증."""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from ..media import ffmpeg
from ..models import ClipInfo, EditPlan
from .compile import compile_render, prepare_workdir

log = logging.getLogger("vibecut.render")


def render_plan(plan: EditPlan, clips: dict[str, ClipInfo], files: dict[str, Path], quality: str, output: Path,
                workdir: Path, on_progress: Callable[[float], None] | None = None,
                cancel: threading.Event | None = None, keep_workdir: bool = False) -> dict:
    """결과 파일을 output에 만들고 측정값을 돌려준다.
    duration은 실제 결과 길이, error_ms는 계획 길이와의 차이 (1프레임 = 33ms 안쪽이어야 정상)."""
    if not plan.keep:
        raise ValueError("남길 구간이 없어 렌더할 수 없습니다.")
    started = time.time()
    output.parent.mkdir(parents=True, exist_ok=True)
    spec = compile_render(plan, clips, files, quality, "out.mp4")
    prepare_workdir(spec, workdir)
    log.info("렌더 시작: %s, 구간 %d개, 예상 %.1f초, %dx%d", quality, len(plan.keep), spec.duration,
             spec.width, spec.height)
    try:
        ffmpeg.run_with_progress(spec.args, spec.duration, on_progress, cancel, cwd=workdir)
        result = workdir / "out.mp4"
        info = ffmpeg.probe(result)
        shutil.move(str(result), str(output))
    finally:
        if not keep_workdir:
            shutil.rmtree(workdir, ignore_errors=True)
    error_ms = round((info.duration - spec.duration) * 1000, 1)
    elapsed = round(time.time() - started, 2)
    log.info("렌더 완료: %.2f초 (계획과 차이 %+.0fms), %.1f초 걸림", info.duration, error_ms, elapsed)
    return {
        "width": spec.width, "height": spec.height, "duration": info.duration, "plan_duration": spec.duration,
        "error_ms": error_ms, "elapsed_sec": elapsed, "size_bytes": output.stat().st_size,
    }
