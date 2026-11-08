"""시간 기준 변환. 기준점이 셋이다 (domain.models 참고).

    클립 초  : 클립 파일 안의 시각
    원본 초  : 타임라인 순서대로 클립을 이어 붙인 '분석용 원본'의 시각 (ClipSpan.offset)
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
