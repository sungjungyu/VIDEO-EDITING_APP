"""배경음악 추천: 장면 분위기 낱말 → 잔잔·경쾌·감성."""

from __future__ import annotations

from vibecut.domain.models import Scene
from vibecut.editing.music import recommend_mood, scene_mood


def S(start, end, mood="", summary=""):
    return Scene(scene_id="s", clip_id="c01", start=start, end=end, mood=mood, summary=summary)


def test_scene_mood_words():
    assert scene_mood("신나는 분위기") == "경쾌"
    assert scene_mood("노을 지는 강변") == "감성"
    assert scene_mood("여유로운 오후") == "잔잔"
    assert scene_mood("카페에 들어간다") is None
    assert scene_mood("황당한 상황에 웃음이 터짐") == "웃김"                  # 예능
    assert scene_mood("유쾌한 대화") == "웃김"


def test_recommend_mood_weighs_by_scene_length_and_defaults_to_calm():
    assert recommend_mood([S(0, 5, "설렘"), S(5, 60, "평화로운")]) == "잔잔"
    assert recommend_mood([S(0, 40, "즐거움"), S(40, 50, "차분")]) == "경쾌"
    assert recommend_mood([S(0, 10, summary="걷는다")]) == "잔잔"
    assert recommend_mood([S(0, 30, "장난스러움"), S(30, 40, "신남")]) == "웃김"
