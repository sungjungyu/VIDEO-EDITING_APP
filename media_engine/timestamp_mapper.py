"""
컷 편집 후 기준으로 자막 타임스탬프를 재계산한다.

cuts = [{"start": float, "end": float}, ...]  → 유지할 구간 목록 (오름차순 정렬 보장)

자막의 원본 start/end가 cuts 구간에 걸치는 경우:
  - 구간 내에 완전히 포함되면 → 새 타임라인 기준으로 이동
  - 구간 경계에 걸쳐있으면 → 구간 내 겹치는 부분만 남김
  - 완전히 삭제된 구간이면 → 제거
"""
from typing import Any


def remap(
    cuts: list[dict],
    subtitles: list[dict],
) -> list[dict]:
    """
    cuts, subtitles 모두 이미 정렬되어 있다고 가정한다.
    반환값: 타임스탬프가 재계산된 자막 리스트 (순서 유지)
    """
    # 각 cut 구간의 새 타임라인 기준 시작점을 미리 계산
    offsets: list[tuple[float, float, float]] = []  # (orig_start, orig_end, new_start)
    cursor = 0.0
    for cut in cuts:
        offsets.append((cut["start"], cut["end"], cursor))
        cursor += cut["end"] - cut["start"]

    result = []
    for sub in subtitles:
        remapped = _remap_subtitle(sub, offsets)
        if remapped is not None:
            result.append(remapped)
    return result


def _remap_subtitle(
    sub: dict,
    offsets: list[tuple[float, float, float]],
) -> dict | None:
    orig_start: float = sub["start"]
    orig_end: float = sub["end"]

    new_start: float | None = None
    new_end: float | None = None

    for o_start, o_end, n_start in offsets:
        overlap_start = max(orig_start, o_start)
        overlap_end = min(orig_end, o_end)
        if overlap_start >= overlap_end:
            continue

        mapped_start = n_start + (overlap_start - o_start)
        mapped_end = n_start + (overlap_end - o_start)

        if new_start is None or mapped_start < new_start:
            new_start = mapped_start
        if new_end is None or mapped_end > new_end:
            new_end = mapped_end

    if new_start is None:
        return None

    remapped = dict(sub)
    remapped["start"] = round(new_start, 3)
    remapped["end"] = round(new_end, 3)

    if "words" in sub:
        remapped["words"] = _remap_words(sub["words"], offsets)

    return remapped


def _remap_words(
    words: list[dict],
    offsets: list[tuple[float, float, float]],
) -> list[dict]:
    result = []
    for w in words:
        remapped = _remap_subtitle(w, offsets)
        if remapped is not None:
            result.append(remapped)
    return result
