"""ffmpeg 실행 계층.

- 바이너리: FFMPEG_BIN 환경 변수 → PATH → imageio-ffmpeg 내장 바이너리 순서로 찾는다.
  (팀 PC 대부분은 시스템 ffmpeg가 없고, imageio-ffmpeg에는 ffprobe가 들어 있지 않다)
- 프로브: ffprobe 대신 `ffmpeg -hide_banner -i 파일`의 stderr를 읽는다. 출력 파일이 없어 종료 코드는 1이지만
  길이·해상도·fps·오디오 유무·촬영 시각·회전 정보가 모두 찍힌다. (영상을 디코딩하지 않아 긴 영상도 빠르다)
- 진행률: `-progress pipe:1`로 out_time을 읽어 콜백으로 넘기고, 취소 이벤트가 오면 프로세스를 끝낸다.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np

log = logging.getLogger("vibecut.media")

NO_AUDIO_MARKERS = ("does not contain any stream", "matches no streams", "Output file is empty",
                    "Output file does not contain any stream")


class FFmpegError(RuntimeError):
    pass


class Canceled(Exception):
    """작업 취소 요청으로 중단됨."""


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    env = os.getenv("FFMPEG_BIN")
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


def filter_script_args(script_name: str) -> list[str]:
    """필터 그래프를 파일로 넘기는 옵션. ffmpeg 7부터는 -/filter_complex, 그 전은 -filter_complex_script."""
    return ["-/filter_complex", script_name] if ffmpeg_version() >= (7, 0) else ["-filter_complex_script", script_name]


def run(args: list[str], cwd: str | Path | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    """ffmpeg 한 번 실행. 실패하면 stderr 끝부분을 담아 FFmpegError."""
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-y", *args]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise FFmpegError(_tail(result.stderr))
    return result


def _tail(stderr: bytes | str, n: int = 1500) -> str:
    text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
    return text[-n:].strip()


def run_with_progress(args: list[str], total_sec: float, on_progress: Callable[[float], None] | None = None,
                      cancel: threading.Event | None = None, cwd: str | Path | None = None) -> str:
    """진행률(0~1)을 콜백으로 알리며 실행한다. 취소되면 Canceled. 성공하면 stderr 끝부분을 돌려준다."""
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err_chunks: list[bytes] = []
    reader = threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True)
    reader.start()
    watcher = None
    if cancel is not None:
        def _watch():
            while proc.poll() is None:
                if cancel.wait(0.3):
                    proc.terminate()
                    return
        watcher = threading.Thread(target=_watch, daemon=True)
        watcher.start()
    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").strip()
        if line.startswith(("out_time_us=", "out_time_ms=")) and on_progress and total_sec > 0:
            try:
                sec = int(line.split("=", 1)[1]) / 1_000_000   # out_time_ms도 실제로는 마이크로초
            except ValueError:
                continue
            on_progress(max(0.0, min(1.0, sec / total_sec)))
    proc.wait()
    reader.join(timeout=5)
    stderr = b"".join(err_chunks)
    if cancel is not None and cancel.is_set():
        raise Canceled("사용자가 작업을 취소했습니다.")
    if proc.returncode != 0:
        raise FFmpegError(_tail(stderr))
    return _tail(stderr)


# ---------------------------------------------------------------- 프로브

@dataclass
class MediaInfo:
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    rotation: int = 0
    has_video: bool = False
    has_audio: bool = False
    created_at: float | None = None
    video_codec: str = ""
    audio_codec: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO = re.compile(r"Stream #\S+.*?: Video: (\w+).*?(\d{2,5})x(\d{2,5})")
_FPS = re.compile(r"(\d+(?:\.\d+)?) (?:fps|tbr)")
_AUDIO = re.compile(r"Stream #\S+.*?: Audio: (\w+)")
_ROTATE = re.compile(r"(?:rotate\s*:\s*(-?\d+))|(?:rotation of (-?\d+(?:\.\d+)?) degrees)")
_CREATED = re.compile(r"(com\.apple\.quicktime\.creationdate|creation_time)\s*:\s*(\S+)", re.IGNORECASE)


def parse_probe(stderr: str) -> MediaInfo:
    m = _DURATION.search(stderr)
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    info = MediaInfo(duration=round(duration, 3))
    v = _VIDEO.search(stderr)
    if v:
        info.has_video = True
        info.video_codec = v.group(1)
        info.width, info.height = int(v.group(2)), int(v.group(3))
        line = stderr[v.start():stderr.find("\n", v.start())]
        f = _FPS.search(line)
        info.fps = float(f.group(1)) if f else 0.0
    a = _AUDIO.search(stderr)
    if a:
        info.has_audio = True
        info.audio_codec = a.group(1)
    r = _ROTATE.search(stderr)
    if r:
        info.rotation = int(round(float(r.group(1) or r.group(2)))) % 360
        if info.rotation in (90, 270):          # ffmpeg는 기본으로 회전을 적용해 디코딩한다 → 보이는 크기
            info.width, info.height = info.height, info.width
    # 촬영 시각: QuickTime 생성 시각(현지 시각+오프셋)을 우선, 없으면 creation_time(UTC)
    found = {}
    for key, value in _CREATED.findall(stderr):
        found.setdefault(key.lower(), value)
    for key in ("com.apple.quicktime.creationdate", "creation_time"):
        if key in found:
            try:
                info.created_at = datetime.fromisoformat(found[key].replace("Z", "+00:00")).timestamp()
                break
            except ValueError:
                continue
    return info


def probe(path: str | Path) -> MediaInfo:
    result = subprocess.run([ffmpeg_path(), "-hide_banner", "-nostdin", "-i", str(path)],
                            capture_output=True, timeout=60)
    stderr = result.stderr.decode("utf-8", errors="replace")
    if "Invalid data found" in stderr or "No such file" in stderr:
        raise FFmpegError(f"영상 파일을 읽을 수 없습니다: {Path(path).name}")
    info = parse_probe(stderr)
    if info.duration <= 0 or not (info.has_video or info.has_audio):
        raise FFmpegError(f"영상 길이나 스트림 정보를 읽지 못했습니다: {Path(path).name}")
    return info


def file_sha1(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- 변환

def extract_audio(src: str | Path, dst: str | Path, sample_rate: int = 16000) -> bool:
    """16kHz 모노 PCM WAV로 뽑는다. 오디오 트랙이 없으면 False."""
    dst = Path(dst)
    if dst.exists() and dst.stat().st_size > 44:
        return True
    tmp = dst.with_suffix(".part.wav")
    try:
        run(["-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sample_rate),
             "-c:a", "pcm_s16le", str(tmp)])
    except FFmpegError as error:
        tmp.unlink(missing_ok=True)
        if any(m in str(error) for m in NO_AUDIO_MARKERS):
            return False
        raise
    os.replace(tmp, dst)
    return True


def make_proxy(src: str | Path, dst: str | Path, info: MediaInfo, short_side: int = 540,
               on_progress: Callable[[float], None] | None = None, cancel: threading.Event | None = None) -> None:
    """브라우저 미리보기용 가벼운 H.264 사본. 1초마다 키프레임이라 어디로 이동해도 바로 보인다."""
    fps = info.fps if 1 <= info.fps <= 120 else 30
    if info.width and info.height and min(info.width, info.height) <= short_side:
        scale = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    elif info.width >= info.height:
        scale = f"scale=-2:{short_side}"
    else:
        scale = f"scale={short_side}:-2"
    tmp = Path(dst).with_suffix(".part.mp4")
    args = ["-loglevel", "error", "-i", str(src)]
    if info.has_video:
        args += ["-vf", f"{scale},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                 "-g", str(round(fps)), "-keyint_min", str(round(fps)), "-sc_threshold", "0"]
    if info.has_audio:
        args += ["-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    args += ["-movflags", "+faststart", str(tmp)]
    try:
        run_with_progress(args, info.duration, on_progress, cancel)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, dst)


def gray_frames(src: str | Path, fps: float = 1.0, size: int = 64,
                cancel: threading.Event | None = None) -> np.ndarray:
    """장면 변화 감지용: 초당 fps장, size×size 흑백 프레임 배열 (N, size, size)."""
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(src), "-an",
           "-vf", f"fps={fps},scale={size}:{size},format=gray", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frames, frame_bytes = [], size * size
    err: list[bytes] = []
    reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    reader.start()
    while True:
        if cancel is not None and cancel.is_set():
            proc.kill()
            raise Canceled("사용자가 작업을 취소했습니다.")
        buf = proc.stdout.read(frame_bytes)
        if not buf or len(buf) < frame_bytes:
            break
        frames.append(np.frombuffer(buf, np.uint8).reshape(size, size))
    proc.wait()
    reader.join(timeout=5)
    if proc.returncode != 0 and not frames:
        raise FFmpegError(_tail(b"".join(err)))
    return np.stack(frames) if frames else np.zeros((0, size, size), np.uint8)
