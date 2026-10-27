"""음량 기반 무음 감지 테스트 (배경 소음에 따라 기준이 자동으로 바뀌는지)."""

from __future__ import annotations

import numpy as np

from vibecut.analysis.audio import auto_threshold, detect_silences, find_silences


def levels(noise_db, speech_db, pattern):
    """pattern: 0.05초 프레임마다 '.'=무음(배경 소음), '#'=말소리"""
    return np.array([speech_db if ch == "#" else noise_db for ch in pattern], dtype=float)


def test_finds_pauses_in_clean_audio():
    db = levels(-80, -20, "......" + "#" * 10 + "....." + "#" * 10 + "...")   # 끝 쉼은 0.15초라 무시
    assert find_silences(db, 0.25, auto_threshold(db)) == [(0.0, 0.3), (0.8, 1.05)]


def test_threshold_follows_background_noise():
    # 같은 쉼 패턴이라도 배경 소음이 크면 기준이 따라 올라가서 쉼을 찾는다 (고정 -35dB면 하나도 못 찾음)
    loud = levels(-32, -17, "......" + "#" * 10 + "....." + "#" * 10 + "......")
    thr = auto_threshold(loud)
    assert thr > -32
    assert len(find_silences(loud, 0.25, thr)) == 3
    assert find_silences(loud, 0.25, -35.0) == []


def test_continuous_speech_is_not_treated_as_silence():
    # 쉬는 구간이 10% 미만으로 계속 말하는 경우: 전체가 무음으로 잡히면 단어가 모두 찌그러진다
    db = levels(-70, -20, "#" * 100 + "......" + "#" * 100)
    thr = auto_threshold(db)
    assert thr <= -30.0
    assert find_silences(db, 0.25, thr) == [(5.0, 5.3)]


def test_short_dips_are_ignored():
    db = levels(-60, -20, "#" * 10 + "..." + "#" * 10)   # 0.15초 쉼
    assert find_silences(db, 0.25, auto_threshold(db)) == []


def test_silence_until_end_is_closed():
    assert find_silences(levels(-60, -20, "#" * 10 + "......"), 0.25, -40.0) == [(0.5, 0.8)]


def test_detect_silences_accepts_measured_levels():
    """음량을 한 번만 재서 넘겨도(받아쓰기 최적화) 같은 결과."""
    db = levels(-80, -20, "......" + "#" * 10 + "....." + "#" * 10 + "...")
    silences, threshold = detect_silences(db, 0.25)
    assert silences == [(0.0, 0.3), (0.8, 1.05)] and threshold == round(auto_threshold(db), 1)
    assert detect_silences(np.zeros(0), 0.25) == ([], None)
