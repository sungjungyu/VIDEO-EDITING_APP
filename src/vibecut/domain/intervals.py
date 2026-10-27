"""구간 연산 (초 단위 (시작, 끝) 목록). 편집 계획 계산의 바탕."""

from __future__ import annotations

Interval = tuple[float, float]


def merge(intervals: list[Interval], gap: float = 0.0) -> list[Interval]:
    """정렬해서 겹치거나 gap보다 가까운 구간을 합친다."""
    out: list[Interval] = []
    for s, e in sorted(intervals):
        if e <= s:
            continue
        if out and s <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def subtract(base: list[Interval], cuts: list[Interval]) -> list[Interval]:
    """base에서 cuts를 뺀다."""
    cuts = merge(cuts)
    out: list[Interval] = []
    for s, e in base:
        cur = s
        for cs, ce in cuts:
            if ce <= cur or cs >= e:
                continue
            if cs > cur:
                out.append((cur, cs))
            cur = max(cur, ce)
            if cur >= e:
                break
        if cur < e:
            out.append((cur, e))
    return out


def clamp(intervals: list[Interval], lo: float, hi: float) -> list[Interval]:
    """lo~hi 밖은 잘라 낸다."""
    return [(max(s, lo), min(e, hi)) for s, e in intervals if min(e, hi) > max(s, lo)]
