"""테스트용 합성 영상 (ffmpeg lavfi). 외부 파일 없이 만든다.

luma_clip: 프레임 번호를 밝기로 새긴 영상 (밝기 = 프레임 번호 % 256). 결과 영상의 프레임을 읽어
           원본 몇 번째 프레임인지 알 수 있어 '프레임 단위로 정확히 잘렸는지' 확인할 수 있다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from vibecut.media.ffmpeg import ffmpeg_path


def make_clip(path: Path, duration: float, size: str = "320x180", fps: int = 30, audio: bool = True,
              gop: int = 150, luma: bool = True, tone: int = 440, bursts: bool = False) -> Path:
    """bursts=True면 '2초 소리, 1초 무음'이 반복되는 오디오 (말소리 구간 감지 테스트용)."""
    video = (f"nullsrc=s={size}:r={fps}:d={duration},geq=lum='mod(N,256)':cb=128:cr=128" if luma
             else f"testsrc=s={size}:r={fps}:d={duration}")
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", video]
    if audio and bursts:
        expr = f"if(lt(mod(t\\,3)\\,2)\\,0.5*sin(2*PI*{tone}*t)\\,0)"
        cmd += ["-f", "lavfi", "-i", f"aevalsrc={expr}:s=48000:d={duration}"]
    elif audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration={duration}"]
    cmd += ["-c:v", "libx264", "-qp", "0", "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
            "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


def frame_lumas(path: Path, times: list[float], fps: int) -> list[float]:
    """결과 영상의 time초 프레임 왼쪽 위 16x16의 Y(밝기) 평균.
    gray로 바꿔 읽으면 TV 범위(16~235)가 전체 범위로 늘어나 값이 달라지므로 yuv420p의 Y 평면을 그대로 읽는다."""
    out = []
    for t in times:
        r = subprocess.run([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.4f}", "-i", str(path),
                            "-frames:v", "1", "-vf", "crop=16:16:0:0", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
                           capture_output=True, check=True)
        out.append(float(np.frombuffer(r.stdout[:256], np.uint8).mean()))
    return out


def stream_durations(path: Path) -> tuple[float, float]:
    """(영상 프레임 수 / fps, 소리 샘플 수 / 샘플레이트) — 실제로 디코딩해서 센다."""
    v = subprocess.run([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:v",
                        "-f", "rawvideo", "-pix_fmt", "gray", "-vf", "scale=8:8", "-"], capture_output=True, check=True)
    a = subprocess.run([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:a",
                        "-f", "s16le", "-ac", "1", "-ar", "48000", "-"], capture_output=True, check=True)
    return len(v.stdout) / 64, len(a.stdout) / 2 / 48000
