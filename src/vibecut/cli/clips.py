"""명령줄 공통: 영상 파일 모으기, 촬영 시각 순 정렬, 정렬 결과 표.

받아쓰기(transcribe)와 장면 분석(scenes) 결과의 clip_id·offset이 같아야 비트(편집 단위)로 합칠 수 있으므로
두 명령이 같은 정렬 규칙(촬영 시각 → 파일 이름)을 쓴다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..media.probe import VIDEO_EXTENSIONS
from ..media.probe import probe as media_probe


def collect_inputs(paths: list[str]) -> list[Path]:
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            files += [x for x in p.iterdir() if x.suffix.lower() in VIDEO_EXTENSIONS]
        elif p.suffix.lower() in VIDEO_EXTENSIONS:
            files.append(p)
    return files


def probe(path: Path) -> dict:
    """길이와 촬영 시각 (메타데이터에 촬영 시각이 없으면 파일 수정 시각)."""
    info = media_probe(path)
    created = info.created_at if info.created_at is not None else path.stat().st_mtime
    return {"duration": info.duration, "created": created}


def order_clips(files: list[Path]) -> list[dict]:
    """촬영 시각 → 파일명 순으로 정렬하고 c01, c02… id와 전체 타임라인 offset을 붙인다.
    받아쓰기·장면 분석이 같은 규칙을 쓴다."""
    clips = [{"file": p, **probe(p)} for p in files]
    clips.sort(key=lambda c: (c["created"], c["file"].name))
    offset = 0.0
    for i, c in enumerate(clips, 1):
        c["id"], c["offset"] = f"c{i:02d}", offset
        offset += c["duration"]
    return clips


def fmt_time(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def print_clip_table(clips: list[dict]) -> None:
    """정렬 순서 출력 (촬영 순서 확인용)."""
    print(f"\n{'─'*60}")
    print(f"{'ID':>4}  {'파일명':<30}  {'촬영시각':<22}  {'길이':>6}")
    print(f"{'─'*60}")
    for c in clips:
        ts = datetime.fromtimestamp(c["created"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{c['id']:>4}  {c['file'].name:<30}  {ts:<22}  {fmt_time(c['duration']):>6}")
    print(f"{'─'*60}")
    print(f"총 {len(clips)}개, {fmt_time(sum(c['duration'] for c in clips))}\n")
