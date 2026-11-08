"""배경음악 크기 규칙: 말 전에 미리 줄이고, 말이 끝나면 천천히 키우고, 처음·끝은 서서히."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibecut.domain.mix import FADE_IN, LEAD, RELEASE, gain_at, merge_spans

CASES = Path(__file__).parents[2] / "fixtures" / "mix_cases.json"


def test_merge_spans_joins_close_speech():
    assert merge_spans([(5.0, 6.0), (1.0, 2.0), (2.5, 3.0)]) == [(1.0, 3.0), (5.0, 6.0)]   # 0.5초 틈 < LEAD+RELEASE


def test_gain_ducks_before_speech_and_recovers_after():
    spans = [(10.0, 12.0)]
    g = lambda t: gain_at(t, spans, 0.5, 0.2, True, 30.0)  # noqa: E731
    assert g(5.0) == pytest.approx(0.5)                             # 말 없음
    assert g(10.0 - LEAD) == pytest.approx(0.5)                     # 줄이기 시작
    assert g(10.0) == pytest.approx(0.1)                            # 말 시작 때 이미 다 줄임
    assert g(11.0) == pytest.approx(0.1)
    assert 0.1 < g(12.0 + RELEASE / 2) < 0.5                        # 다시 키우는 중
    assert g(12.0 + RELEASE) == pytest.approx(0.5)
    assert g(0.0) == 0 and g(FADE_IN / 2) == pytest.approx(0.25)    # 처음은 서서히
    assert g(30.0) == 0
    assert gain_at(11.0, spans, 0.5, 0.2, False, 30.0) == pytest.approx(0.5)   # 줄이기를 끄면 그대로


def test_shared_cases_match_python_rule():
    """화면(web/js/core/mix.js)도 같은 파일로 검사한다 (tests/js/mix.test.mjs)."""
    data = json.loads(CASES.read_text(encoding="utf-8"))
    for case in data["cases"]:
        got = gain_at(case["t"], [tuple(s) for s in data["spans"]], data["volume"], data["duck_level"], True,
                      data["duration"])
        assert got == pytest.approx(case["gain"], abs=1e-6), case
