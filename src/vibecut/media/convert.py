"""ffmpeg 변환 작업: 오디오 추출·미리보기 사본·장면 분석용 저해상도·흑백 프레임·오디오 조각."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..errors import Canceled, FFmpegError
from .ffmpeg import ffmpeg_path, run, run_with_progress, spawn, tail
from .probe import MediaInfo

NO_AUDIO_MARKERS = ("does not contain any stream", "matches no streams", "Output file is empty",
                    "Output file does not contain any stream")


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


def make_lowres(src: str | Path, dst: str | Path, height: int) -> None:
    """초당 1장, 무음, 고압축 (장면 분석용 — Gemini에 보내는 크기를 줄인다). 이미 있으면 그대로 쓴다."""
    dst = Path(dst)
    if dst.exists() and dst.stat().st_size > 0:
        return
    run(["-loglevel", "error", "-i", str(src), "-vf", f"scale=-2:{height},fps=1", "-an",
         "-c:v", "libx264", "-crf", "32", "-preset", "veryfast", str(dst)])


def cut_audio(src: str | Path, dst: str | Path, start: float, end: float) -> None:
    """오디오 일부를 FLAC으로 잘라 낸다 (긴 오디오를 나눠 받아쓰기할 때)."""
    run(["-loglevel", "error", "-i", str(src), "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-c:a", "flac", str(dst)])


def gray_frames(src: str | Path, fps: float = 1.0, size: int = 64,
                cancel: threading.Event | None = None) -> np.ndarray:
    """장면 변화 감지용: 초당 fps장, size×size 흑백 프레임 배열 (N, size, size)."""
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(src), "-an",
           "-vf", f"fps={fps},scale={size}:{size},format=gray", "-f", "rawvideo", "-"]
    proc, stderr = spawn(cmd)
    frames, frame_bytes = [], size * size
    while True:
        if cancel is not None and cancel.is_set():
            proc.kill()
            raise Canceled()
        buf = proc.stdout.read(frame_bytes)
        if not buf or len(buf) < frame_bytes:
            break
        frames.append(np.frombuffer(buf, np.uint8).reshape(size, size))
    proc.wait()
    err = stderr()
    if proc.returncode != 0 and not frames:
        raise FFmpegError(tail(err))
    return np.stack(frames) if frames else np.zeros((0, size, size), np.uint8)
