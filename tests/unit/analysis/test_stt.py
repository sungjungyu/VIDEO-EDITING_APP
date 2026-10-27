"""받아쓰기 결과 정리(postprocess)와 Gemini 엔진 응답 처리(engines) 테스트."""

from __future__ import annotations

import numpy as np
import pytest

from vibecut.analysis.judge import rule_decisions
from vibecut.analysis.stt.engines import choose_split_points, offset_sec, parse_gemini_response, split_sentences
from vibecut.analysis.stt.postprocess import (
    clean_segments,
    drop_hallucinations,
    hallucination_reason,
    refine_with_silence,
    split_into_sentences,
)
from vibecut.analysis.stt.transcribe import cache_name
from vibecut.domain.models import Line

RAW_C01 = [
    {"start": 0.0, "end": 2.0, "text": " 안녕하세요 오늘은",
     "words": [{"word": " 안녕하세요", "start": 0.2, "end": 0.9, "probability": 0.98},
               {"word": " 오늘은", "start": 1.0, "end": 1.6, "probability": 0.91}]},
    {"start": 2.0, "end": 4.0, "text": " 카페에 왔어요.",
     "words": [{"word": " 카페에", "start": 2.1, "end": 2.6, "probability": 0.95},
               {"word": " 왔어요.", "start": 2.7, "end": 3.4, "probability": 0.42}]},
]


# ---------------------------------------------------------------- clean_segments

def test_strips_word_spaces_and_keeps_probability():
    segs = clean_segments(RAW_C01, duration=10.0)
    assert [w["word"] for w in segs[0]["words"]] == ["안녕하세요", "오늘은"]
    assert segs[1]["words"][1]["probability"] == 0.42
    assert segs[0]["text"] == "안녕하세요 오늘은"


def test_segment_bounds_follow_words():
    segs = clean_segments(RAW_C01, duration=10.0)
    assert (segs[0]["start"], segs[0]["end"]) == (0.2, 1.6)
    assert (segs[1]["start"], segs[1]["end"]) == (2.1, 3.4)


def test_drops_empty_words_and_segments():
    raw = [
        {"start": 0, "end": 1, "text": "  ", "words": []},
        {"start": 1, "end": 2, "text": "네", "words": [{"word": " ", "start": 1, "end": 1.1},
                                                     {"word": "네", "start": 1.2, "end": 1.5},
                                                     {"word": "시각없음"}]},
    ]
    segs = clean_segments(raw, duration=5.0)
    assert len(segs) == 1
    assert [w["word"] for w in segs[0]["words"]] == ["네"]


def test_clamps_to_duration():
    raw = [{"start": -1, "end": 9, "text": "끝", "words": [{"word": "끝", "start": 4.5, "end": 7.0}]}]
    segs = clean_segments(raw, duration=5.0)
    assert segs[0]["words"][0]["end"] == 5.0
    assert segs[0]["end"] == 5.0


def test_word_times_never_go_backwards_across_segments():
    raw = [
        {"start": 0, "end": 2, "text": "가 나", "words": [{"word": "가", "start": 0.0, "end": 1.0},
                                                      {"word": "나", "start": 0.8, "end": 1.9}]},
        {"start": 1.5, "end": 3, "text": "다", "words": [{"word": "다", "start": 1.7, "end": 2.5}]},
    ]
    segs = clean_segments(raw, duration=5.0)
    words = [w for s in segs for w in s["words"]]
    for prev, cur in zip(words, words[1:]):
        assert cur["start"] >= prev["end"]
    assert segs[1]["start"] >= segs[0]["end"]


def test_sorts_and_keeps_segments_without_words():
    raw = [{"start": 3, "end": 4, "text": "뒤"}, {"start": 0, "end": 1, "text": "앞"}]
    segs = clean_segments(raw, duration=5.0)
    assert [s["text"] for s in segs] == ["앞", "뒤"]
    assert segs[1]["words"] == []


def test_wrong_first_word_start_does_not_reorder_sentences():
    # 실제 Gemini 출력: "오후에는" 시작을 10초 앞당겨 앞 문장보다 먼저 시작하는 것처럼 나옴
    raw = [
        {"start": 105.28, "end": 108.48, "text": "이제 기다려 보겠습니다.",
         "words": [{"word": "이제", "start": 105.28, "end": 105.58},
                   {"word": "보겠습니다.", "start": 107.68, "end": 108.48}]},
        {"start": 103.98, "end": 117.68, "text": "오후에는 거예요.",
         "words": [{"word": "오후에는", "start": 103.98, "end": 114.58},
                   {"word": "거예요.", "start": 117.18, "end": 117.68}]},
    ]
    segs = clean_segments(raw, duration=130.0)
    assert [s["text"] for s in segs] == ["이제 기다려 보겠습니다.", "오후에는 거예요."]
    assert segs[0]["start"] == 105.28              # 앞 문장이 찌그러지지 않음
    assert segs[1]["words"][0]["start"] == 108.48   # 앞 문장 끝 뒤로 밀림


def test_bad_input_does_not_crash():
    assert clean_segments(None, 5.0) == []
    assert clean_segments([{"start": "x", "end": 1, "text": "a"}], 5.0) == []


# ---------------------------------------------------------------- refine_with_silence

# 실제 실행값: TTS 클립(앞 무음 1초)을 Whisper medium으로 받아쓴 단어 시각과 silencedetect 결과
REFINE_RAW = [{"start": 0.0, "end": 9.22, "text": "안녕하세요. 오늘은 왔습니다. 아이스 주문했어요.",
               "words": [{"word": "안녕하세요.", "start": 0.0, "end": 1.82},
                         {"word": "오늘은", "start": 2.92, "end": 3.3},
                         {"word": "왔습니다.", "start": 5.16, "end": 6.08},
                         {"word": "아이스", "start": 6.8, "end": 7.16},
                         {"word": "주문했어요.", "start": 8.5, "end": 9.22}]}]
REFINE_SILENCES = [(0.0, 1.12), (1.97, 2.84), (5.68, 6.58), (9.26, 11.05)]


@pytest.fixture
def refined():
    return refine_with_silence(clean_segments(REFINE_RAW, duration=13.17), REFINE_SILENCES)


def test_leading_silence_removed_from_first_word(refined):
    assert refined[0]["words"][0]["start"] == 1.12


def test_word_end_inside_silence_pulled_back(refined):
    assert refined[0]["words"][2]["end"] == 5.68


def test_late_start_moved_back_to_speech_onset(refined):
    words = refined[0]["words"]
    assert words[1]["start"] == 2.84
    assert words[3]["start"] == 6.58


def test_early_end_extended_to_silence_start(refined):
    words = refined[0]["words"]
    assert words[0]["end"] == 1.97
    assert words[4]["end"] == 9.26


def test_segment_bounds_and_order_kept(refined):
    seg = refined[0]
    assert (seg["start"], seg["end"]) == (1.12, 9.26)
    words = seg["words"]
    for prev, cur in zip(words, words[1:]):
        assert cur["start"] >= prev["end"]
        assert cur["end"] >= cur["start"]


def test_silence_swallowed_at_word_start_is_skipped():
    # 실제 Gemini 출력: 앞 문장 끝(113.08)에 붙어 시작해 0.8초 무음(113.15~113.95)까지 품은 단어
    segs = clean_segments([{"start": 113.08, "end": 114.58, "text": "오후에는",
                            "words": [{"word": "오후에는", "start": 113.08, "end": 114.58}]}], 130.0)
    refine_with_silence(segs, [(113.15, 113.95)])
    assert segs[0]["words"][0]["start"] == 113.95


def test_silence_swallowed_at_word_end_is_cut():
    segs = clean_segments([{"start": 10.0, "end": 12.0, "text": "끝",
                            "words": [{"word": "끝", "start": 10.0, "end": 12.0}]}], 20.0)
    refine_with_silence(segs, [(11.2, 11.9)])
    assert segs[0]["words"][0]["end"] == 11.2


def test_no_silences_changes_nothing():
    segs = clean_segments(REFINE_RAW, duration=13.17)
    before = [dict(w) for w in segs[0]["words"]]
    assert refine_with_silence(segs, [])[0]["words"] == before


# ---------------------------------------------------------------- 문장 재분할

def test_whisper_chunks_are_split_into_sentences():
    def w(word, s, e):
        return {"word": word, "start": s, "end": e}

    chunk = {"start": 0.0, "end": 6.0, "text": "음. 라떼가 유명하다고. 아 다시 할게.",
             "words": [w("음.", 0.0, 0.4), w("라떼가", 0.8, 1.3), w("유명하다고.", 1.3, 2.2), w("아", 2.6, 2.8),
                       w("다시", 2.8, 3.2), w("할게.", 3.2, 3.7)]}
    out = split_into_sentences([chunk, {"start": 7, "end": 8, "text": "네", "words": [w("네", 7, 8)]}])
    assert [s["text"] for s in out] == ["음.", "라떼가 유명하다고.", "아 다시 할게.", "네"]
    assert (out[1]["start"], out[1]["end"]) == (0.8, 2.2)
    lines = [Line(seg_id=f"t{i}", clip_id="c01", start=s["start"], end=s["end"], text=s["text"])
             for i, s in enumerate(out)]
    lines.append(Line(seg_id="t9", clip_id="c01", start=9, end=12, text="라떼가 정말 유명하다고 해서 와봤어요"))
    rules = rule_decisions(lines)
    assert [rules[f"t{i}"].reason for i in range(3)] == ["군더더기", "NG", "지시어"]


# ---------------------------------------------------------------- Gemini 받아쓰기 응답

# 실제 gemini-3.5-transcribe 응답 형식 (wordTimestamp + diarization)
GEMINI_RESP = {"candidates": [{"content": {"parts": [{
    "text": "안녕하세요. 오늘은 카페에 왔습니다.",
    "audioTranscription": {
        "text": "안녕하세요. 오늘은 카페에 왔습니다.", "speakerLabel": "spk:0",
        "words": [{"word": "안녕하세요.", "startOffset": "1.100s", "endOffset": "2s"},
                  {"word": "오늘은", "startOffset": "2.900s", "endOffset": "3.300s"},
                  {"word": "카페에", "startOffset": "4.500s", "endOffset": "5s"},
                  {"word": "왔습니다.", "startOffset": "5s", "endOffset": "5.700s"}]}}]}}]}


def test_offset_string():
    assert (offset_sec("1.100s"), offset_sec("2s"), offset_sec(None)) == (1.1, 2.0, None)


def test_split_sentences_by_punctuation_and_gap():
    def w(t, s, e):
        return {"word": t, "start": s, "end": e}

    groups = split_sentences([w("네.", 0, 0.5), w("그런데", 0.6, 1.0), w("음", 1.1, 1.3), w("다시", 3.5, 4.0)])
    assert [[x["word"] for x in g] for g in groups] == [["네."], ["그런데", "음"], ["다시"]]


def test_parse_response_makes_sentences_with_offset_and_speaker():
    segs = parse_gemini_response(GEMINI_RESP, offset=600.0, chunk_end=1200.0)
    assert [s["text"] for s in segs] == ["안녕하세요.", "오늘은 카페에 왔습니다."]
    assert (segs[1]["start"], segs[1]["end"]) == (602.9, 605.7)
    assert segs[0]["speaker"] == "spk:0"
    assert set(segs[0]["words"][0]) == {"word", "start", "end"}


def test_parse_empty_response():
    # 실제: 소음만 있는 클립은 parts 없이 돌아옴
    assert parse_gemini_response({"candidates": [{"content": {"role": "model"}}]}, 0, 10) == []
    assert parse_gemini_response({}, 0, 10) == []


def test_parse_text_without_word_times():
    resp = {"candidates": [{"content": {"parts": [{"audioTranscription": {"text": "네"}}]}}]}
    assert parse_gemini_response(resp, 60, 120) == [{"start": 60, "end": 120, "text": "네", "words": []}]


def test_split_points_never_exceed_chunk_and_prefer_silence():
    # 0.05초 프레임, 말소리(-20dB) 사이사이 쉼(-70dB). 40초짜리 오디오를 15초 단위로
    db = np.full(800, -20.0)
    for start in (180, 230, 520):              # 9초, 11.5초, 26초 지점에 0.5초 쉼
        db[start:start + 10] = -70.0
    points = choose_split_points(db, chunk_sec=15, search_sec=5)
    bounds = [0.0] + points + [40.0]
    assert all(b - a <= 15 + 1e-6 for a, b in zip(bounds, bounds[1:]))
    assert points[0] == pytest.approx(11.75)    # 15초 앞 5초 안의 쉼 가운데
    assert choose_split_points(db[:200], chunk_sec=15) == []


def test_cache_name_format_is_stable():
    """받아쓰기 캐시 파일 이름이 바뀌면 저장해 둔 받아쓰기를 못 쓴다."""
    sha1 = "0123456789abcdef0123456789abcdef01234567"
    assert cache_name(sha1, "gemini", "gemini-3.5-transcribe", "ko", []) == \
        "0123456789abcdef0123_gemini_gemini-3.5-transcribe_ko_da39a3ee.json"
    assert cache_name(sha1, "whisper-local", "small", "ko", ["성수동", "라떼"]).startswith(
        "0123456789abcdef0123_whisper-local_small_ko_")


# ---------------------------------------------------------------- 환각 의심

PROMPT = "다음은 자연스러운 한국어 영상 자막입니다. 고유명사, 제품명, 숫자와 단위를 정확히 표기하세요."


def seg(text, probs, no_speech):
    return {"start": 0, "end": 1, "text": text, "no_speech_prob": no_speech,
            "words": [{"word": "w", "start": 0, "end": 1, "probability": p} for p in probs]}


def test_prompt_echo_is_dropped():
    # 실제 출력: 소음만 있는 클립에서 나온 문장
    s = seg(" 한국어 자막은 제품명과 단위를 정확히 표기하세요.", [0.05, 0.46, 0.26, 0.08, 0.1, 0.1], 0.59)
    assert "안내 문구" in hallucination_reason(s, PROMPT)


def test_low_confidence_non_speech_is_dropped():
    assert "말소리 아님" in hallucination_reason(seg(" 감사합니다.", [0.12, 0.2], 0.7), PROMPT)


def test_real_speech_is_kept_even_with_noise():
    # 실제 출력: 센 배경 소음 클립 (평균 단어 확률 0.93, 무음 확률 0.16)
    s = seg(" 안녕하세요. 오늘은 친구들과 함께 카페에 왔습니다.", [0.86, 0.96, 0.99, 0.99, 0.97, 0.99], 0.16)
    assert hallucination_reason(s, PROMPT) is None


def test_quiet_but_confident_speech_is_kept():
    assert hallucination_reason(seg(" 네", [0.9], 0.55), PROMPT) is None


def test_drop_hallucinations_splits_and_records_reason():
    real = seg(" 맛있다", [0.9], 0.1)
    fake = seg(" 한국어 자막은 제품명과 단위를 정확히 표기하세요.", [0.1] * 6, 0.59)
    kept, dropped = drop_hallucinations([real, fake], PROMPT)
    assert kept == [real]
    assert len(dropped) == 1
    assert set(dropped[0]) == {"start", "end", "text", "reason"}
