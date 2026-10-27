"""시간 기준 변환. 기준점이 셋이다 (domain.models 참고).

    클립 초  : 클립 파일 안의 시각
    원본 초  : 타임라인 순서대로 클립을 이어 붙인 '분석용 원본'의 시각 (트리 노드)
    결과 초  : 렌더된 영상 안의 시각
"""

from __future__ import annotations

from .models import ClipInfo, ClipSpan


def clip_spans(clips: list[ClipInfo]) -> list[ClipSpan]:
    """타임라인 순서의 클립들 → 원본 타임라인에서 각 클립이 차지하는 자리."""
    spans, offset = [], 0.0
    for c in clips:
        spans.append(ClipSpan(clip_id=c.clip_id, offset=round(offset, 4), duration=c.duration))
        offset += c.duration
    return spans


def global_to_clip(start: float, end: float, spans: list[ClipSpan]) -> list[tuple[str, float, float]]:
    """원본 초 구간 → 클립별 (clip_id, 클립 초 시작, 끝)."""
    out = []
    for span in spans:
        lo, hi = span.offset, span.offset + span.duration
        s, e = max(start, lo), min(end, hi)
        if e > s:
            out.append((span.clip_id, s - lo, e - lo))
    return out


def fmt_clock(sec: float) -> str:
    """mm:ss (초 아래는 버림). 장면 이름 '장면 00:00~00:16'에 쓴다."""
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"
