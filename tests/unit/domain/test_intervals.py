"""구간 연산 테스트."""

from __future__ import annotations

from vibecut.domain.intervals import clamp, merge, subtract


def test_interval_helpers():
    assert merge([(3, 5), (0, 1), (0.9, 2)]) == [(0, 2), (3, 5)]
    assert merge([(0, 1), (1.2, 2)], gap=0.3) == [(0, 2)]
    assert subtract([(0, 10)], [(2, 3), (5, 6)]) == [(0, 2), (3, 5), (6, 10)]


def test_clamp_cuts_outside_and_drops_empty():
    assert clamp([(-1.0, 2.0), (3.0, 9.0), (9.5, 12.0)], 0.0, 9.0) == [(0.0, 2.0), (3.0, 9.0)]
