"""자막 줄바꿈·단어 줄 맞추기 테스트. 결과는 화면 web/js/subtitle/wrap.js와 같아야 한다
(같은 사례 파일 tests/fixtures/wrap_cases.json을 tests/js/wrap.test.mjs도 읽는다)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibecut.domain.text import align_words_to_lines, wrap_text

# 화면(JS)과 같은 결과가 나와야 하는 사례 — tests/js/wrap.test.mjs도 같은 파일을 읽는다
WRAP_CASES = json.loads((Path(__file__).parents[2] / "fixtures" / "wrap_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", WRAP_CASES, ids=[c["text"][:12] or "빈 문자열" for c in WRAP_CASES])
def test_wrap_text(case):
    assert wrap_text(case["text"], case["width"]) == case["lines"]


def test_align_words_to_lines():
    text = "오늘은 카페에 왔어요 라떼가 맛있어요"
    words = ["오늘은", "카페에", "왔어요", "라떼가", "맛있어요"]
    assert align_words_to_lines(text, words, 10) == [0, 0, 1, 1, 2]
    assert align_words_to_lines("다른 글자", words, 10) is None
