"""영상 정보 읽기: ffprobe 대신 `ffmpeg -hide_banner -i 파일`의 stderr를 읽는다.

출력 파일이 없어 종료 코드는 1이지만 길이·해상도·fps·오디오 유무·촬영 시각·회전 정보가 모두 찍힌다.
(영상을 디코딩하지 않아 긴 영상도 빠르다)
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from ..errors import FFmpegError
from .ffmpeg import ffmpeg_path

# 올릴 수 있는 영상 확장자 (화면에는 /api/config로 알려 준다)
VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp")


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
    """파일 sha1 (1MB씩 읽는다 — 큰 영상도 메모리를 쓰지 않는다). 캐시 키로 쓴다."""
    digest = hashlib.sha1()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            digest.update(block)
    return digest.hexdigest()
