"""ffmpeg 실행 계층: 바이너리 찾기·한 번 실행·진행률을 보며 실행.

- 바이너리: FFMPEG_BIN 환경 변수 → PATH → imageio-ffmpeg 내장 바이너리 순서로 찾는다.
  (팀 PC 대부분은 시스템 ffmpeg가 없고, imageio-ffmpeg에는 ffprobe가 들어 있지 않다)
- 진행률: `-progress pipe:1`로 out_time을 읽어 콜백으로 넘기고, 취소 이벤트가 오면 프로세스를 끝낸다.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from ..errors import Canceled, FFmpegError
from ..settings import get_settings

log = logging.getLogger("vibecut.media")

HDR_TONEMAP_FILTER = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
)
# Windows에서 콘솔 Ctrl+C가 하위 ffmpeg와 엉키지 않게 별도 프로세스 그룹으로 띄운다
_CREATIONFLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
_active_procs: set[subprocess.Popen] = set()
_procs_lock = threading.Lock()


@lru_cache(maxsize=4)
def ffmpeg_path(ffmpeg_bin: str | None = None) -> str:
    env = ffmpeg_bin if ffmpeg_bin is not None else get_settings().ffmpeg_bin
    if env and (Path(env).exists() or shutil.which(env)):
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as error:  # imageio-ffmpeg 없음 / 바이너리 다운로드 실패
        raise FFmpegError("ffmpeg를 찾지 못했습니다. "
                          "`pip install imageio-ffmpeg` 또는 ffmpeg 설치가 필요합니다.") from error


@lru_cache(maxsize=1)
def ffmpeg_version() -> tuple[int, int]:
    out = subprocess.run([ffmpeg_path(), "-hide_banner", "-version"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    m = re.search(r"ffmpeg version n?(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


@lru_cache(maxsize=1)
def supports_tonemap() -> bool:
    """ffmpeg 빌드에 HDR→SDR 변환용 zscale·tonemap 필터가 모두 있는지 확인한다."""
    try:
        out = subprocess.run([ffmpeg_path(), "-hide_banner", "-filters"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=10).stdout
        return " zscale " in out and " tonemap " in out
    except Exception:
        return False


def filter_script_args(script_name: str) -> list[str]:
    """필터 그래프를 파일로 넘기는 옵션. ffmpeg 7부터는 -/filter_complex, 그 전은 -filter_complex_script."""
    return ["-/filter_complex", script_name] if ffmpeg_version() >= (7, 0) else ["-filter_complex_script", script_name]


def run(args: list[str], cwd: str | Path | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    """ffmpeg 한 번 실행. 실패하면 stderr 끝부분을 담아 FFmpegError."""
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-y", *args]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout, creationflags=_CREATIONFLAGS)
    if result.returncode != 0:
        raise FFmpegError(tail(result.stderr))
    return result


def tail(stderr: bytes | str, n: int = 1500) -> str:
    text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
    return text[-n:].strip()


def kill_active_processes() -> None:
    """서버 종료 시 아직 돌고 있는 하위 ffmpeg 프로세스를 모두 즉시 종료한다."""
    with _procs_lock:
        procs = list(_active_procs)
        _active_procs.clear()
    for proc in procs:
        try:
            proc.kill()
        except Exception:
            pass


def spawn(cmd: list[str], cwd: str | Path | None = None) -> tuple[subprocess.Popen, Callable[[], bytes]]:
    """stdout을 읽으며 실행할 프로세스를 띄운다. stderr는 따로 모아 두었다가 두 번째 반환값으로 꺼낸다
    (두 파이프를 한 스레드에서 읽으면 버퍼가 차서 멈출 수 있다)."""
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=_CREATIONFLAGS)
    with _procs_lock:
        _active_procs.add(proc)
    chunks: list[bytes] = []
    reader = threading.Thread(target=lambda: chunks.append(proc.stderr.read()), daemon=True)
    reader.start()

    def collected() -> bytes:
        with _procs_lock:
            _active_procs.discard(proc)
        reader.join(timeout=5)
        return b"".join(chunks)

    return proc, collected


def run_with_progress(args: list[str], total_sec: float, on_progress: Callable[[float], None] | None = None,
                      cancel: threading.Event | None = None, cwd: str | Path | None = None) -> str:
    """진행률(0~1)을 콜백으로 알리며 실행한다. 취소되면 Canceled. 성공하면 stderr 끝부분을 돌려준다."""
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    proc, stderr = spawn(cmd, cwd)
    if cancel is not None:
        def _watch():
            while proc.poll() is None:
                if cancel.wait(0.2):
                    proc.kill()
                    return
        threading.Thread(target=_watch, daemon=True).start()
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if line.startswith(("out_time_us=", "out_time_ms=")) and on_progress and total_sec > 0:
                try:
                    sec = int(line.split("=", 1)[1]) / 1_000_000   # out_time_ms도 실제로는 마이크로초
                except ValueError:
                    continue
                on_progress(max(0.0, min(1.0, sec / total_sec)))
        proc.wait()
    finally:
        err = stderr()
    if cancel is not None and cancel.is_set():
        raise Canceled()
    if proc.returncode != 0:
        raise FFmpegError(tail(err))
    return tail(err)
