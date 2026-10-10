import unittest
from pathlib import Path
from unittest.mock import patch

import transcriber
import numpy as np

from transcriber import (auto_threshold, clean_segments, drop_hallucinations, find_silences, globalize,
                         hallucination_reason, order_clips, refine_with_silence, to_subtitles,
                         validate_transcript)


def build_transcript(clips, raw_by_clip):
    """main()과 같은 순서로 transcript dict를 만든다 (받아쓰기 엔진 없이)."""
    segments = []
    for c in clips:
        segments += globalize(clean_segments(raw_by_clip[c["id"]], c["duration"]), c)
    for i, s in enumerate(segments, 1):
        s["seg_id"] = f"t{i:04d}"
    return {
        "clips": [{"id": c["id"], "duration": c["duration"], "offset": round(c["offset"], 2)} for c in clips],
        "segments": segments,
    }


RAW_C01 = [
    {"start": 0.0, "end": 2.0, "text": " 안녕하세요 오늘은",
     "words": [{"word": " 안녕하세요", "start": 0.2, "end": 0.9, "probability": 0.98},
               {"word": " 오늘은", "start": 1.0, "end": 1.6, "probability": 0.91}]},
    {"start": 2.0, "end": 4.0, "text": " 카페에 왔어요.",
     "words": [{"word": " 카페에", "start": 2.1, "end": 2.6, "probability": 0.95},
               {"word": " 왔어요.", "start": 2.7, "end": 3.4, "probability": 0.42}]},
]
RAW_C02 = [
    {"start": 0.5, "end": 1.5, "text": " 맛있다",
     "words": [{"word": " 맛있다", "start": 0.5, "end": 1.2, "probability": 0.9}]},
]


class CleanSegmentsTests(unittest.TestCase):
    def test_strips_word_spaces_and_keeps_probability(self):
        segs = clean_segments(RAW_C01, duration=10.0)
        self.assertEqual([w["word"] for w in segs[0]["words"]], ["안녕하세요", "오늘은"])
        self.assertEqual(segs[1]["words"][1]["probability"], 0.42)
        self.assertEqual(segs[0]["text"], "안녕하세요 오늘은")

    def test_segment_bounds_follow_words(self):
        segs = clean_segments(RAW_C01, duration=10.0)
        self.assertEqual((segs[0]["start"], segs[0]["end"]), (0.2, 1.6))
        self.assertEqual((segs[1]["start"], segs[1]["end"]), (2.1, 3.4))

    def test_drops_empty_words_and_segments(self):
        raw = [
            {"start": 0, "end": 1, "text": "  ", "words": []},
            {"start": 1, "end": 2, "text": "네", "words": [{"word": " ", "start": 1, "end": 1.1},
                                                         {"word": "네", "start": 1.2, "end": 1.5},
                                                         {"word": "시각없음"}]},
        ]
        segs = clean_segments(raw, duration=5.0)
        self.assertEqual(len(segs), 1)
        self.assertEqual([w["word"] for w in segs[0]["words"]], ["네"])

    def test_clamps_to_duration(self):
        raw = [{"start": -1, "end": 9, "text": "끝", "words": [{"word": "끝", "start": 4.5, "end": 7.0}]}]
        segs = clean_segments(raw, duration=5.0)
        self.assertEqual(segs[0]["words"][0]["end"], 5.0)
        self.assertEqual(segs[0]["end"], 5.0)

    def test_word_times_never_go_backwards_across_segments(self):
        raw = [
            {"start": 0, "end": 2, "text": "가 나", "words": [{"word": "가", "start": 0.0, "end": 1.0},
                                                          {"word": "나", "start": 0.8, "end": 1.9}]},
            {"start": 1.5, "end": 3, "text": "다", "words": [{"word": "다", "start": 1.7, "end": 2.5}]},
        ]
        segs = clean_segments(raw, duration=5.0)
        words = [w for s in segs for w in s["words"]]
        for prev, cur in zip(words, words[1:]):
            self.assertGreaterEqual(cur["start"], prev["end"])
        self.assertGreaterEqual(segs[1]["start"], segs[0]["end"])

    def test_sorts_and_keeps_segments_without_words(self):
        raw = [{"start": 3, "end": 4, "text": "뒤"}, {"start": 0, "end": 1, "text": "앞"}]
        segs = clean_segments(raw, duration=5.0)
        self.assertEqual([s["text"] for s in segs], ["앞", "뒤"])
        self.assertEqual(segs[1]["words"], [])

    def test_bad_input_does_not_crash(self):
        self.assertEqual(clean_segments(None, 5.0), [])
        self.assertEqual(clean_segments([{"start": "x", "end": 1, "text": "a"}], 5.0), [])


class RefineWithSilenceTests(unittest.TestCase):
    # 실제 실행값: TTS 클립(앞 무음 1초)을 Whisper medium으로 받아쓴 단어 시각과 silencedetect 결과
    RAW = [{"start": 0.0, "end": 9.22, "text": "안녕하세요. 오늘은 왔습니다. 아이스 주문했어요.",
            "words": [{"word": "안녕하세요.", "start": 0.0, "end": 1.82},
                      {"word": "오늘은", "start": 2.92, "end": 3.3},
                      {"word": "왔습니다.", "start": 5.16, "end": 6.08},
                      {"word": "아이스", "start": 6.8, "end": 7.16},
                      {"word": "주문했어요.", "start": 8.5, "end": 9.22}]}]
    SILENCES = [(0.0, 1.12), (1.97, 2.84), (5.68, 6.58), (9.26, 11.05)]

    def refined(self):
        segs = clean_segments(self.RAW, duration=13.17)
        return refine_with_silence(segs, self.SILENCES)

    def test_leading_silence_removed_from_first_word(self):
        self.assertEqual(self.refined()[0]["words"][0]["start"], 1.12)

    def test_word_end_inside_silence_pulled_back(self):
        self.assertEqual(self.refined()[0]["words"][2]["end"], 5.68)

    def test_late_start_moved_back_to_speech_onset(self):
        words = self.refined()[0]["words"]
        self.assertEqual(words[1]["start"], 2.84)
        self.assertEqual(words[3]["start"], 6.58)

    def test_early_end_extended_to_silence_start(self):
        words = self.refined()[0]["words"]
        self.assertEqual(words[0]["end"], 1.97)
        self.assertEqual(words[4]["end"], 9.26)

    def test_segment_bounds_and_order_kept(self):
        seg = self.refined()[0]
        self.assertEqual((seg["start"], seg["end"]), (1.12, 9.26))
        words = seg["words"]
        for prev, cur in zip(words, words[1:]):
            self.assertGreaterEqual(cur["start"], prev["end"])
            self.assertGreaterEqual(cur["end"], cur["start"])

    def test_no_silences_changes_nothing(self):
        segs = clean_segments(self.RAW, duration=13.17)
        before = [dict(w) for w in segs[0]["words"]]
        self.assertEqual(refine_with_silence(segs, [])[0]["words"], before)

class SilenceDetectionTests(unittest.TestCase):
    @staticmethod
    def levels(noise_db, speech_db, pattern):
        """pattern: 0.05초 프레임마다 '.'=무음(배경 소음), '#'=말소리"""
        return np.array([speech_db if ch == "#" else noise_db for ch in pattern], dtype=float)

    def test_finds_pauses_in_clean_audio(self):
        db = self.levels(-80, -20, "......" + "#" * 10 + "....." + "#" * 10 + "...")   # 끝 쉼은 0.15초라 무시
        thr = auto_threshold(db)
        self.assertEqual(find_silences(db, 0.25, thr), [(0.0, 0.3), (0.8, 1.05)])

    def test_threshold_follows_background_noise(self):
        # 같은 쉼 패턴이라도 배경 소음이 크면 기준이 따라 올라가서 쉼을 찾는다 (고정 -35dB면 하나도 못 찾음)
        pattern = "......" + "#" * 10 + "....." + "#" * 10 + "......"
        loud = self.levels(-32, -17, pattern)
        thr = auto_threshold(loud)
        self.assertGreater(thr, -32)
        self.assertEqual(len(find_silences(loud, 0.25, thr)), 3)
        self.assertEqual(find_silences(loud, 0.25, -35.0), [])

    def test_short_dips_are_ignored(self):
        db = self.levels(-60, -20, "#" * 10 + "..." + "#" * 10)   # 0.15초 쉼
        self.assertEqual(find_silences(db, 0.25, auto_threshold(db)), [])

    def test_silence_until_end_is_closed(self):
        db = self.levels(-60, -20, "#" * 10 + "......")
        self.assertEqual(find_silences(db, 0.25, -40.0), [(0.5, 0.8)])


class HallucinationTests(unittest.TestCase):
    PROMPT = "다음은 자연스러운 한국어 영상 자막입니다. 고유명사, 제품명, 숫자와 단위를 정확히 표기하세요."

    @staticmethod
    def seg(text, probs, no_speech):
        return {"start": 0, "end": 1, "text": text, "no_speech_prob": no_speech,
                "words": [{"word": "w", "start": 0, "end": 1, "probability": p} for p in probs]}

    def test_prompt_echo_is_dropped(self):
        # 실제 출력: 소음만 있는 클립에서 나온 문장
        s = self.seg(" 한국어 자막은 제품명과 단위를 정확히 표기하세요.", [0.05, 0.46, 0.26, 0.08, 0.1, 0.1], 0.59)
        self.assertIn("안내 문구", hallucination_reason(s, self.PROMPT))

    def test_low_confidence_non_speech_is_dropped(self):
        s = self.seg(" 감사합니다.", [0.12, 0.2], 0.7)
        self.assertIn("말소리 아님", hallucination_reason(s, self.PROMPT))

    def test_real_speech_is_kept_even_with_noise(self):
        # 실제 출력: 센 배경 소음 클립 (평균 단어 확률 0.93, 무음 확률 0.16)
        s = self.seg(" 안녕하세요. 오늘은 친구들과 함께 카페에 왔습니다.", [0.86, 0.96, 0.99, 0.99, 0.97, 0.99], 0.16)
        self.assertIsNone(hallucination_reason(s, self.PROMPT))

    def test_quiet_but_confident_speech_is_kept(self):
        self.assertIsNone(hallucination_reason(self.seg(" 네", [0.9], 0.55), self.PROMPT))

    def test_drop_hallucinations_splits_and_records_reason(self):
        real = self.seg(" 맛있다", [0.9], 0.1)
        fake = self.seg(" 한국어 자막은 제품명과 단위를 정확히 표기하세요.", [0.1] * 6, 0.59)
        kept, dropped = drop_hallucinations([real, fake], self.PROMPT)
        self.assertEqual(kept, [real])
        self.assertEqual(len(dropped), 1)
        self.assertEqual(set(dropped[0]), {"start", "end", "text", "reason"})


class OrderClipsTests(unittest.TestCase):
    def test_sorts_by_created_then_name_and_sets_offsets(self):
        info = {"b.mp4": {"duration": 10.0, "created": 100.0},
                "a.mp4": {"duration": 20.0, "created": 200.0},
                "c.mp4": {"duration": 5.0, "created": 100.0}}
        with patch.object(transcriber, "probe", side_effect=lambda p: info[p.name]):
            clips = order_clips([Path("a.mp4"), Path("c.mp4"), Path("b.mp4")])
        self.assertEqual([(c["id"], c["file"].name, c["offset"]) for c in clips],
                         [("c01", "b.mp4", 0.0), ("c02", "c.mp4", 10.0), ("c03", "a.mp4", 15.0)])


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        clips = [{"id": "c01", "duration": 10.0, "offset": 0.0},
                 {"id": "c02", "duration": 8.0, "offset": 10.0}]
        self.t = build_transcript(clips, {"c01": RAW_C01, "c02": RAW_C02})

    def test_global_times_and_clip_times(self):
        s = self.t["segments"][2]
        self.assertEqual((s["seg_id"], s["clip_id"]), ("t0003", "c02"))
        self.assertEqual((s["start"], s["end"]), (10.5, 11.2))
        self.assertEqual((s["clip_start"], s["clip_end"]), (0.5, 1.2))
        self.assertEqual(s["words"][0]["start"], 10.5)

    def test_valid_transcript_has_no_problems(self):
        self.assertEqual(validate_transcript(self.t), [])

    def test_detects_text_words_mismatch_after_edit(self):
        self.t["segments"][1]["text"] = "카페에 갔어요."   # 교정 등으로 text만 바뀐 경우
        problems = validate_transcript(self.t)
        self.assertTrue(any("t0002" in p and "불일치" in p for p in problems))

    def test_detects_overlap_and_unknown_clip(self):
        self.t["segments"][1]["start"] = 1.0
        self.t["segments"][2]["clip_id"] = "c99"
        problems = validate_transcript(self.t)
        self.assertTrue(any("겹침" in p for p in problems))
        self.assertTrue(any("c99" in p for p in problems))

    def test_to_subtitles_matches_media_engine_format(self):
        subs = to_subtitles(self.t)
        self.assertEqual(len(subs), 3)
        self.assertEqual(set(subs[0]), {"start", "end", "text", "words"})
        self.assertEqual(set(subs[0]["words"][0]), {"word", "start", "end"})   # probability는 빠짐

    def test_to_subtitles_single_clip_uses_clip_time(self):
        subs = to_subtitles(self.t, clip_id="c02")
        self.assertEqual(len(subs), 1)
        self.assertEqual((subs[0]["start"], subs[0]["words"][0]["start"]), (0.5, 0.5))

    def test_media_engine_accepts_output(self):
        from media_engine.ass_generator import _build_karaoke_text
        from media_engine.timestamp_mapper import remap

        subs = to_subtitles(self.t, clip_id="c01")
        remapped = remap([{"start": 2.0, "end": 4.0}], subs)   # 두 번째 문장만 남기는 컷
        self.assertEqual(len(remapped), 1)
        self.assertEqual(remapped[0]["text"], "카페에 왔어요.")
        self.assertEqual(remapped[0]["words"][0]["start"], 0.1)
        karaoke = _build_karaoke_text(remapped[0]["words"], remapped[0]["start"])
        self.assertIn("카페에", karaoke)
        self.assertIn("\\k", karaoke)


if __name__ == "__main__":
    unittest.main()
