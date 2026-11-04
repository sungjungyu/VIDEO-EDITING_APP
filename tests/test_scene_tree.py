import unittest

from prompt_builder import calc_duration, normalize_tree
from scene_tree import (UNIT_MIN_SEC, UNIT_MAX_SEC, SESSION_MIN_SEC,
                        _merge_short_sessions, _place_of, _renumber_visits,
                        apply_corrections, ask_tree, attach_lines, build_scene_tree, build_units, combine_parts,
                        fallback_structure,
                        lines_to_segments, mark_cut_suggestions, merge_short_units, normalize_clips, normalize_lines,
                        normalize_shots, parse_structure, scene_context, session_breaks, snap_to_lines,
                        sound_similarity, split_points, validate_tree)
from shot_analyzer import merge_short
from transcriber import validate_transcript

QUIET = {"log": lambda *a: None}


def seg(st, en, text, **extra):
    """단어 시각이 고르게 들어간 받아쓰기 문장 (앱 segments 형식)."""
    words = text.split()
    step = (en - st) / len(words)
    return {"start": st, "end": en, "text": text, **extra,
            "words": [{"word": w, "start": round(st + i * step, 3), "end": round(st + (i + 1) * step - 0.05, 3)}
                      for i, w in enumerate(words)]}


def shot(st, en, desc, place="카페", action="", **extra):
    return {"start": st, "end": en, "desc": desc, "place": place, "action": action, "people": [],
            "visible_text": "", "event": "", "mood": "", **extra}


CLIP = [{"id": "c01", "duration": 45.0, "offset": 0.0}]
SEGMENTS = [seg(1.0, 3.0, "뭐 먹지 진짜"), seg(4.5, 7.5, "아이스 아메리카노 두 잔이요"),   # 6초 화면 경계에 걸침
            seg(9.0, 10.5, "카드 되죠?"), seg(30.0, 33.0, "와 바다 말라서 좋다"), seg(40.0, 41.5, "가자")]
SHOTS = [shot(0, 6, "카운터 앞에서 메뉴판을 올려다본다", action="메뉴 보기", visible_text="BLUE CAFE"),
         shot(6, 12, "직원에게 주문한다", action="주문"),
         shot(12, 13, "짧은 흔들림", action="주문"),                     # 2초 미만 → 합쳐짐
         shot(13, 25, "카드를 꽂고 영수증을 받는다", action="결제"),
         shot(25, 45, "해변에서 바다를 바라본다", place="해변", action="바다 구경")]


def walk(nodes, depth=1):
    for n in nodes:
        yield n, depth
        yield from walk(n["children"], depth + 1)


def fake_ai(sessions, corrections=()):
    calls = []

    def ask(prompt, schema):
        calls.append(prompt)
        return {"corrections": list(corrections), "sessions": sessions}
    return ask, calls


def step(start, title, summary="", tags=()):
    return {"start": start, "title": title, "summary": summary, "tags": list(tags)}


# UNIT_MIN_SEC=10 이후 SHOTS → 3개 L4 단위로 합쳐짐:
#   s0001(0~13s 카페 메뉴+주문), s0002(13~25s 카페 결제), s0003(25~45s 해변)
AI_SESSIONS = [
    {"title": "카페 (1차 방문)", "summary": "카페에서 주문한다", "flows": [
        {"title": "주문 흐름", "summary": "메뉴를 보고 주문·결제", "steps": [
            step("s0001", "메뉴판 보기", "메뉴를 고민하고 주문한다", ["고민"]),
            step("s0002", "결제")]}]},
    {"title": "해변 (1차 방문)", "summary": "", "flows": [
        {"title": "해변 산책 흐름", "summary": "", "steps": [step("s0003", "바다 구경", "", ["풍경"])]}]},
]


class NormalizeTests(unittest.TestCase):
    def test_app_segments_get_ids_and_clip(self):
        lines = normalize_lines([seg(5, 6, "나"), seg(1, 2, "가")], normalize_clips(CLIP))
        self.assertEqual([(x["id"], x["text"], x["clip_id"]) for x in lines], [("t0001", "가", "c01"), ("t0002", "나", "c01")])

    def test_transcript_segments_keep_seg_id(self):
        lines = normalize_lines([{**seg(1, 2, "가"), "seg_id": "t0007", "clip_id": "c02"}], normalize_clips(CLIP))
        self.assertEqual((lines[0]["id"], lines[0]["clip_id"]), ("t0007", "c02"))

    def test_shots_json_and_app_shots_cover_each_clip(self):
        clips = normalize_clips([{"id": "c01", "duration": 10, "offset": 0}, {"id": "c02", "duration": 8, "offset": 10},
                                 {"id": "c03", "duration": 5, "offset": 18}])
        shots = [{**shot(10, 14, "가"), "clip_id": "c02", "clip_start": 0, "clip_end": 4},
                 {**shot(14, 18, "나"), "clip_id": "c02", "clip_start": 4, "clip_end": 8},
                 {**shot(0, 10, "다"), "clip_id": "c01"}]
        out = normalize_shots(shots, clips)
        self.assertEqual([(s["clip_id"], s["start"], s["end"], s["desc"]) for s in out],
                         [("c01", 0.0, 10.0, "다"), ("c02", 10.0, 14.0, "가"), ("c02", 14.0, 18.0, "나"),
                          ("c03", 18.0, 23.0, "(영상분석 없음)")])

    def test_speaker_carried_through_normalize_and_attach(self):
        segs = [
            {**seg(1.0, 3.0, "안녕하세요"), "speaker": "SPEAKER_01"},
            {**seg(4.0, 6.0, "반갑습니다"), "speaker": "SPEAKER_02"},
            seg(7.0, 9.0, "화자 없음"),
        ]
        lines = normalize_lines(segs, normalize_clips(CLIP))
        self.assertEqual(lines[0].get("speaker"), "SPEAKER_01")
        self.assertEqual(lines[1].get("speaker"), "SPEAKER_02")
        self.assertNotIn("speaker", lines[2])

        units = [{"id": "s0001", "start": 0.0, "end": 10.0, "lines": []}]
        attach_lines(units, lines)
        speakers = [x.get("speaker") for x in units[0]["lines"]]
        self.assertEqual(speakers, ["SPEAKER_01", "SPEAKER_02", None])

    def test_speaker_survives_sentence_split_across_units(self):
        segs = [{**seg(3.0, 7.0, "앞 뒤 반반"), "speaker": "SPEAKER_01"}]
        lines = normalize_lines(segs, normalize_clips(CLIP))
        units = [{"id": "s0001", "start": 0.0, "end": 5.0, "lines": []},
                 {"id": "s0002", "start": 5.0, "end": 10.0, "lines": []}]
        attach_lines(units, lines)
        # 두 조각 모두 speaker 가짐
        for u in units:
            if u["lines"]:
                self.assertEqual(u["lines"][0].get("speaker"), "SPEAKER_01")

    def test_zero_duration_segment_recovered_from_words(self):
        # end==start지만 words에 유효한 범위가 있으면 복구 → 버리지 않음
        segs = [{"start": 5.0, "end": 5.0, "text": "안녕",
                 "words": [{"word": "안녕", "start": 5.0, "end": 6.0}]}]
        warns = []
        lines = normalize_lines(segs, normalize_clips(CLIP), warns)
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(lines[0]["start"], 5.0)
        self.assertAlmostEqual(lines[0]["end"], 6.0)
        self.assertEqual(warns, [])

    def test_zero_duration_segment_no_valid_words_dropped_with_warning(self):
        # end==start, words도 end==start → 버리고 warnings에 id 기록
        segs = [{"id": "t0566", "start": 2850.8, "end": 2850.8, "text": "네.",
                 "words": [{"word": "네.", "start": 2850.8, "end": 2850.8}]}]
        warns = []
        lines = normalize_lines(segs, normalize_clips(CLIP), warns)
        self.assertEqual(len(lines), 0)
        self.assertEqual(len(warns), 1)
        self.assertIn("t0566", warns[0])


class UnitTests(unittest.TestCase):
    def test_boundary_inside_sentence_moves_to_its_edge(self):
        lines = normalize_lines(SEGMENTS, normalize_clips(CLIP))
        pieces = snap_to_lines([shot(0, 6, "a"), shot(6, 12, "b")], lines)
        self.assertAlmostEqual(pieces[0]["end"], 4.2)          # "두 잔이요"(4.5~7.5) 앞 쉼으로, 문장에서 0.3초
        self.assertEqual(pieces[0]["end"], pieces[1]["start"])

    def test_sentence_longer_than_neighbor_merges_shots(self):
        lines = normalize_lines([seg(1.0, 9.0, "아주 긴 문장 하나 끝까지")], normalize_clips(CLIP))
        pieces = snap_to_lines([shot(0, 4, "a"), shot(4, 6, "b"), shot(6, 10, "c")], lines)
        self.assertEqual([(p["start"], p["end"]) for p in pieces], [(0, 0.7), (0.7, 9.3), (9.3, 10)])
        self.assertEqual([(p["start"], p["end"]) for p in merge_short(pieces, 2.0)], [(0, 10)])

    def test_long_talking_scene_splits_between_sentences(self):
        # 60초 장면 + 4개 문장 → 문장 사이에서 나뉨, 각 조각 UNIT_MIN_SEC~UNIT_MAX_SEC
        long_clip = normalize_clips([{"id": "c01", "duration": 100.0, "offset": 0.0}])
        lines = normalize_lines([seg(1.0, 12.0, "하나 둘"), seg(15.0, 26.0, "셋 넷"),
                                 seg(30.0, 41.0, "다섯 여섯"), seg(45.0, 56.0, "일곱 여덟")], long_clip)
        cuts = split_points(0.0, 60.0, lines)
        gaps = [(12.0 + 15.0) / 2, (26.0 + 30.0) / 2, (41.0 + 45.0) / 2]
        self.assertTrue(cuts and all(any(abs(c - g) < 1e-6 for g in gaps) for c in cuts), cuts)
        bounds = [0.0] + cuts + [60.0]
        self.assertTrue(all(UNIT_MIN_SEC <= b - a <= UNIT_MAX_SEC for a, b in zip(bounds, bounds[1:])), bounds)

    def test_silent_scene_splits_evenly_and_short_ones_stay(self):
        # 70초 무음 → 각 조각이 UNIT_MIN_SEC~UNIT_MAX_SEC 범위
        bounds = [0.0] + split_points(0.0, 70.0, []) + [70.0]
        self.assertGreater(len(bounds) - 1, 1)
        self.assertTrue(all(UNIT_MIN_SEC <= b - a <= UNIT_MAX_SEC for a, b in zip(bounds, bounds[1:])), bounds)
        # UNIT_MAX_SEC - 1 초는 그대로 (범위 이내)
        self.assertEqual(split_points(0.0, UNIT_MAX_SEC - 1, []), [])
        # UNIT_MAX_SEC + 2 초는 나눠짐
        cuts = split_points(0.0, UNIT_MAX_SEC + 2, [])
        self.assertGreater(len(cuts), 0)
        b32 = [0.0] + cuts + [UNIT_MAX_SEC + 2]
        self.assertTrue(all(UNIT_MIN_SEC <= b - a <= UNIT_MAX_SEC for a, b in zip(b32, b32[1:])), b32)

    def test_long_sentence_kept_unless_very_long(self):
        clips = normalize_clips(CLIP)
        # UNIT_MAX_SEC 이내 → early return, 분리 없음
        at_max = normalize_lines([seg(0.0, UNIT_MAX_SEC, "가 나 다 라 마 바 사 아")], clips)
        self.assertEqual(split_points(0.0, UNIT_MAX_SEC, at_max), [])
        # UNIT_MAX_SEC + 10 초 문장 → 단어 사이에서 1회 분리
        long = normalize_lines([seg(0.0, UNIT_MAX_SEC + 10, "가 나 다 라 마 바 사 아")], clips)
        self.assertEqual(len(split_points(0.0, UNIT_MAX_SEC + 10, long)), 1)

    def test_units_tile_clips_and_never_cut_sentences(self):
        clips = normalize_clips([{"id": "c01", "duration": 20, "offset": 0}, {"id": "c02", "duration": 15, "offset": 20}])
        segs = [seg(2, 5, "첫 클립 문장"), seg(9, 12.5, "경계를 넘는 문장"), {**seg(21, 24, "두 번째 클립"), "clip_id": "c02"}]
        shots = [{**shot(0, 10, "가"), "clip_id": "c01"}, {**shot(10, 20, "나"), "clip_id": "c01"},
                 {**shot(20, 35, "다"), "clip_id": "c02"}]
        lines = normalize_lines(segs, clips)
        units = build_units(normalize_shots(shots, clips), lines, clips)
        self.assertEqual(units[0]["start"], 0.0)
        self.assertEqual(units[-1]["end"], 35.0)
        for a, b in zip(units, units[1:]):
            self.assertAlmostEqual(a["end"], b["start"])
        self.assertTrue(any(u["start"] == 20.0 for u in units))        # 클립 경계에서 반드시 나뉨
        for u in units:
            for x in lines:
                self.assertFalse(x["start"] + 0.05 < u["start"] < x["end"] - 0.05, (u["id"], x["text"]))
        self.assertEqual([u["id"] for u in units], [f"s{i:04d}" for i in range(1, len(units) + 1)])
        self.assertEqual(sum(len(u["lines"]) for u in units), 3)

    def test_sentence_split_by_unit_boundary_becomes_two_parts(self):
        units = [{"id": "s0001", "start": 0.0, "end": 5.0}, {"id": "s0002", "start": 5.0, "end": 10.0}]
        line = normalize_lines([seg(3.0, 7.0, "앞 뒤 반반 문장")], normalize_clips(CLIP))
        attach_lines(units, line)
        self.assertEqual([x["text"] for x in units[0]["lines"]], ["앞 뒤"])
        self.assertEqual([x["text"] for x in units[1]["lines"]], ["반반 문장"])
        self.assertTrue(units[0]["lines"][0]["part"])


class ShortUnitMergeTests(unittest.TestCase):
    """merge_short_units: UNIT_MIN_SEC 미만 조각을 이웃과 합친다."""

    def test_same_place_pieces_merge_to_min_length(self):
        """같은 장소 5초 조각 4개 → 모두 UNIT_MIN_SEC 이상으로 합쳐짐"""
        pieces = [shot(0, 5, "a", place="카페"), shot(5, 10, "b", place="카페"),
                  shot(10, 15, "c", place="카페"), shot(15, 20, "d", place="카페")]
        result = merge_short_units(pieces, UNIT_MIN_SEC)
        self.assertTrue(all(p["end"] - p["start"] >= UNIT_MIN_SEC for p in result))
        self.assertAlmostEqual(result[0]["start"], 0.0)
        self.assertAlmostEqual(result[-1]["end"], 20.0)

    def test_different_place_short_pieces_stay_separate(self):
        """장소가 다른 5초 조각 두 개 → 같은 장소 이웃이 없으므로 합쳐지지 않고 둘 다 남음"""
        pieces = [shot(0, 5, "카페", place="카페"), shot(5, 10, "해변", place="해변")]
        result = merge_short_units(pieces, UNIT_MIN_SEC)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0]["end"] - result[0]["start"], 5.0)
        self.assertAlmostEqual(result[1]["end"] - result[1]["start"], 5.0)

    def test_no_same_place_neighbor_stays_short(self):
        """UNIT_MIN_SEC 미만이어도 같은 장소 이웃이 없으면 그대로 둔다 (장소 순서: 카페·해변·카페)"""
        # 인접 이웃이 모두 다른 장소이면 해변 조각은 합쳐지지 않는다
        pieces = [shot(0, 5, "카페A", place="카페"), shot(5, 10, "해변", place="해변"),
                  shot(10, 15, "카페B", place="카페")]
        result = merge_short_units(pieces, UNIT_MIN_SEC)
        self.assertEqual(len(result), 3)
        places = [p.get("place") for p in result]
        self.assertIn("해변", places)

    def test_already_long_pieces_untouched(self):
        """이미 UNIT_MIN_SEC 이상인 조각은 건드리지 않음"""
        pieces = [shot(0, UNIT_MIN_SEC, "충분히 긴 장면", place="카페"),
                  shot(UNIT_MIN_SEC, UNIT_MIN_SEC * 2, "두 번째", place="카페")]
        result = merge_short_units(pieces, UNIT_MIN_SEC)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0]["end"] - result[0]["start"], UNIT_MIN_SEC)

    def test_clip_boundary_not_crossed(self):
        """build_units를 통해: 클립 경계를 넘어 합치지 않음"""
        clips = normalize_clips([{"id": "c01", "duration": 8, "offset": 0},
                                 {"id": "c02", "duration": 8, "offset": 8}])
        shots_data = [{**shot(0, 8, "가"), "clip_id": "c01"},
                      {**shot(8, 16, "나"), "clip_id": "c02"}]
        units = build_units(normalize_shots(shots_data, clips), [], clips)
        c01_units = [u for u in units if u["clip_id"] == "c01"]
        c02_units = [u for u in units if u["clip_id"] == "c02"]
        self.assertTrue(c01_units and c02_units)
        self.assertLessEqual(max(u["end"] for u in c01_units), 8.0 + 1e-6)
        self.assertGreaterEqual(min(u["start"] for u in c02_units), 8.0 - 1e-6)

    def test_merged_piece_over_max_gets_split_by_split_points(self):
        """합쳐서 UNIT_MAX_SEC 넘으면 split_points가 다시 나눔"""
        clips = normalize_clips([{"id": "c01", "duration": 200.0, "offset": 0.0}])
        # 5초짜리 8개 같은 장소 → 합쳐서 40초 → split_points가 10~30초로 나눔
        shots_data = [{**shot(i * 5, (i + 1) * 5, f"장면{i}", place="카페"), "clip_id": "c01"}
                      for i in range(8)]
        units = build_units(normalize_shots(shots_data, clips), [], clips)
        durs = [u["end"] - u["start"] for u in units]
        self.assertTrue(all(UNIT_MIN_SEC <= d <= UNIT_MAX_SEC for d in durs), durs)


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.lines = normalize_lines([seg(0, 3, "오늘 날씨가 말라서, 좋다"), seg(4, 6, "성수 똥 가자"),
                                      seg(7, 9, "아메리카노 두 잔이요")], normalize_clips(CLIP))

    def test_sound_alike_fix_keeps_word_times_and_punctuation(self):
        before = self.lines[0]["words"][2]
        out, applied, rejected = apply_corrections(self.lines, [
            {"line": "t0001", "wrong": "말라서", "right": "맑아서", "reason": "화면이 맑은 하늘"}])
        self.assertEqual(out[0]["text"], "오늘 날씨가 맑아서, 좋다")
        self.assertEqual(out[0]["text_raw"], "오늘 날씨가 말라서, 좋다")
        self.assertEqual((out[0]["words"][2]["start"], out[0]["words"][2]["end"]), (before["start"], before["end"]))
        self.assertEqual((len(applied), rejected), (1, []))
        self.assertEqual(self.lines[0]["text"], "오늘 날씨가 말라서, 좋다")      # 원본은 그대로

    def test_same_word_count_keeps_each_word_time(self):
        lines = normalize_lines([seg(0, 3, "파마다 이거 파다.")], normalize_clips(CLIP))
        out, applied, _ = apply_corrections(lines, [{"line": "t0001", "wrong": "파마다 이거 파다", "right": "파도다 이거 파도다",
                                                     "reason": "해변에서 파도를 보며"}])
        self.assertEqual([w["word"] for w in out[0]["words"]], ["파도다", "이거", "파도다."])
        self.assertEqual([(w["start"], w["end"]) for w in out[0]["words"]],
                         [(w["start"], w["end"]) for w in lines[0]["words"]])
        self.assertEqual(len(applied), 1)

    def test_multi_word_span_becomes_one_word(self):
        out, applied, _ = apply_corrections(self.lines, [{"line": "t0002", "wrong": "성수 똥", "right": "성수동", "reason": ""}])
        self.assertEqual([w["word"] for w in out[1]["words"]], ["성수동", "가자"])
        self.assertEqual(out[1]["words"][0]["start"], self.lines[1]["words"][0]["start"])
        self.assertEqual(out[1]["words"][0]["end"], self.lines[1]["words"][1]["end"])

    def test_rejects_unsafe_corrections(self):
        _, applied, rejected = apply_corrections(self.lines, [
            {"line": "t0003", "wrong": "두 잔이요", "right": "세 잔이요", "reason": "내용이 바뀜"},
            {"line": "t0001", "wrong": "날씨가", "right": "식당이", "reason": "발음 다름"},
            {"line": "t0002", "wrong": "성수 똥", "right": "성수똥", "reason": "띄어쓰기만"},
            {"line": "t0009", "wrong": "가", "right": "카", "reason": "없는 대사"},
            {"line": "t0002", "wrong": "망원똥", "right": "망원동", "reason": "대사에 없음"},
            {"line": "t0001", "wrong": "좋다", "right": "좋다가", "reason": "말을 더함"},
        ])
        self.assertEqual(applied, [])
        self.assertEqual([r["why"][:4] for r in rejected],
                         ["발음이 ", "발음이 ", "바뀌는 ", "없는 대", "대사에서", "발음이 "])

    def test_corrected_lines_still_pass_transcript_rules(self):
        out, _, _ = apply_corrections(self.lines, [{"line": "t0001", "wrong": "말라서", "right": "맑아서", "reason": ""}])
        transcript = {"clips": [{"id": "c01", "offset": 0.0, "duration": 45.0}],
                      "segments": [{"seg_id": x["id"], **x} for x in out]}
        self.assertEqual(validate_transcript(transcript), [])

    def test_similarity_looks_only_at_changed_part(self):
        self.assertGreaterEqual(sound_similarity("광한리", "광안리"), 0.5)
        self.assertEqual(sound_similarity("두 잔이요", "세 잔이요"), 0.0)


class StructureTests(unittest.TestCase):
    UNITS = [{"id": f"s{i:04d}", "lines": []} for i in range(1, 7)]

    def test_drops_bad_ids_and_forces_first_step_to_start(self):
        resp = {"sessions": [{"title": "A", "summary": "", "flows": [{"title": "F", "summary": "", "steps": [
            step("s0002", "첫"), step("s0099", "없음"), step("s0004", "둘"), step("s0003", "역순"), step("s0005", "셋")]}]}]}
        out, warnings = parse_structure(resp, self.UNITS, 0, 6)
        self.assertEqual([s["start"] for s in out["steps"]], [0, 3, 4])
        self.assertEqual([(x["start"], x["title"]) for x in out["sessions"]], [(0, "A")])
        self.assertEqual(len(warnings), 2)

    def test_nothing_usable_is_none(self):
        out, _ = parse_structure({"sessions": [{"title": "A", "flows": []}]}, self.UNITS, 0, 6)
        self.assertIsNone(out)

    def test_invalid_answer_is_retried_with_feedback_then_falls_back(self):
        prompts = []

        def ask(prompt, schema):
            prompts.append(prompt)
            return {"corrections": [], "sessions": []}
        units = [{"id": "s0001", "start": 0, "end": 4, "lines": [], "place": "카페", "action": "주문"}]
        result = ask_tree(units, {}, ask, **QUIET)
        self.assertEqual(len(prompts), 2)
        self.assertIn("[이전 응답의 문제]", prompts[1])
        self.assertIsNone(result["parts"][0][2])

    def test_long_video_is_sent_in_parts_and_seams_merge(self):
        # 6유닛 × 4초 = 24초 → max_sec=12로 2회 호출
        units = [{"id": f"s{i:04d}", "start": i * 4.0, "end": i * 4.0 + 4, "lines": [], "place": "카페",
                  "action": "주문"} for i in range(1, 7)]
        answers = iter([
            {"corrections": [], "sessions": [{"title": "카페 (1차 방문)", "summary": "", "flows": [
                {"title": "주문 흐름", "summary": "", "steps": [step("s0001", "가"), step("s0002", "나")]}]}]},
            {"corrections": [], "sessions": [{"title": "카페 (1차 방문)", "summary": "", "flows": [
                {"title": "주문 흐름", "summary": "", "steps": [step("s0004", "다")]}]}]},
        ])
        prompts = []

        def ask(prompt, schema):
            prompts.append(prompt)
            return next(answers)
        parts = ask_tree(units, {}, ask, max_sec=12, **QUIET)["parts"]
        self.assertEqual([(lo, hi) for lo, hi, _ in parts], [(0, 3), (3, 6)])
        self.assertIn("[앞부분 이어서]", prompts[1])
        structure, failed = combine_parts(units, parts, {})
        self.assertEqual((len(structure["sessions"]), len(structure["flows"]), failed), (1, 1, []))
        self.assertEqual([s["start"] for s in structure["steps"]], [0, 1, 3])
        self.assertIn("지금까지 나온 세션 목록", prompts[1])

    def test_seam_merges_same_place_different_visit_number(self):
        """이음매에서 방문 번호가 달라도 같은 장소면 합쳐짐 (1차+2차→1차로 재번호)"""
        units = [{"id": f"s{i:04d}", "start": i * 4.0, "end": i * 4.0 + 4, "lines": [], "place": "카페"}
                 for i in range(1, 7)]
        parts = [
            (0, 3, {"sessions": [{"start": 0, "title": "카페 (1차 방문)", "summary": ""}],
                    "flows": [{"start": 0, "title": "주문 흐름", "summary": ""}],
                    "steps": [{"start": 0, "title": "a", "summary": "", "tags": []}]}),
            (3, 6, {"sessions": [{"start": 3, "title": "카페 (2차 방문)", "summary": ""}],
                    "flows": [{"start": 3, "title": "착석 흐름", "summary": ""}],
                    "steps": [{"start": 3, "title": "b", "summary": "", "tags": []}]}),
        ]
        structure, failed = combine_parts(units, parts, {})
        self.assertEqual(len(structure["sessions"]), 1)
        self.assertEqual(_place_of(structure["sessions"][0]["title"]), "카페")
        self.assertEqual(failed, [])

    def test_short_session_merges_with_neighbor(self):
        """SESSION_MIN_SEC 미만 세션은 이웃 세션에 흡수됨 (촬영 끊김 없을 때)"""
        # 10개 × 20s = 200s  |  3개 × 20s = 60s  |  10개 × 20s = 200s
        units = [{"id": f"s{i:04d}", "start": i * 20.0, "end": i * 20.0 + 20, "lines": []}
                 for i in range(23)]
        merged = {
            "sessions": [{"start": 0,  "title": "카페 (1차 방문)", "summary": ""},
                          {"start": 10, "title": "거리 (1차 방문)", "summary": ""},
                          {"start": 13, "title": "카페 (2차 방문)", "summary": ""}],
            "flows":    [{"start": 0,  "title": "F1", "summary": ""},
                          {"start": 10, "title": "F2", "summary": ""},
                          {"start": 13, "title": "F3", "summary": ""}],
            "steps":    [{"start": 0,  "title": "a", "summary": "", "tags": []},
                          {"start": 10, "title": "b", "summary": "", "tags": []},
                          {"start": 13, "title": "c", "summary": "", "tags": []}],
        }
        _merge_short_sessions(merged, units, {}, hi=23)
        self.assertEqual(len(merged["sessions"]), 2)

    def test_renumber_visits_resets_after_merge(self):
        """_renumber_visits: 합친 뒤 방문 번호를 처음부터 다시 매김"""
        sessions = [
            {"title": "카페 (1차 방문)", "summary": ""},
            {"title": "해변 (1차 방문)", "summary": ""},
            {"title": "카페 (1차 방문)", "summary": ""},   # 중복 1차 → 2차로 재번호
            {"title": "해변 (3차 방문)", "summary": ""},   # 잘못된 3차 → 2차로 재번호
        ]
        _renumber_visits(sessions)
        self.assertEqual([s["title"] for s in sessions],
                         ["카페 (1차 방문)", "해변 (1차 방문)", "카페 (2차 방문)", "해변 (2차 방문)"])


class BuildTreeTests(unittest.TestCase):
    def setUp(self):
        ask, self.prompts = fake_ai(AI_SESSIONS, [{"line": "t0004", "wrong": "말라서", "right": "맑아서",
                                                   "reason": "화면에 맑은 바다"}])
        self.result = build_scene_tree(CLIP, SHOTS, SEGMENTS, ask=ask, **QUIET)
        self.tree = self.result["tree"]

    def test_tree_passes_rules_and_has_four_levels(self):
        self.assertEqual(self.result["warnings"], [])
        self.assertEqual(validate_tree(self.tree), [])
        self.assertEqual({d for n, d in walk(self.tree) if not n["children"]}, {4})
        self.assertEqual((self.tree[0]["start"], self.tree[-1]["end"]), (0.0, 45.0))
        self.assertEqual(self.result["source"], "ai")

    def test_titles_and_levels_follow_ai_structure(self):
        self.assertEqual([s["title"] for s in self.tree], ["카페 (1차 방문)", "해변 (1차 방문)"])
        cafe_steps = self.tree[0]["children"][0]["children"]
        self.assertEqual([a["title"] for a in cafe_steps], ["메뉴판 보기", "결제"])
        self.assertEqual([n["level"] for n, _ in walk(self.tree[:1])][:4], [1, 2, 3, 4])
        self.assertEqual(self.tree[0]["children"][0]["children"][0]["id"], "p01-f01-a01")
        self.assertIn("말 없음", cafe_steps[1]["tags"])   # s0002(13~25s)는 대사 없음

    def test_prompt_shows_scenes_with_screen_text_and_lines(self):
        prompt = self.prompts[0]
        self.assertIn("[s0001]", prompt)
        self.assertIn("화면 글자: BLUE CAFE", prompt)
        self.assertIn("[t0002] 아이스 아메리카노 두 잔이요", prompt)

    def test_correction_flows_into_lines_and_l4(self):
        self.assertEqual(self.result["lines"][3]["text"], "와 바다 맑아서 좋다")
        l4 = [n for n, d in walk(self.tree) if d == 4 and n["lines"] and n["lines"][0]["id"] == "t0004"][0]
        self.assertTrue(l4["lines"][0]["fixed"])
        self.assertIn("AI 보정", l4["tags"])
        segs = lines_to_segments(self.result["lines"])
        self.assertEqual(segs[3]["text"], "와 바다 맑아서 좋다")
        self.assertEqual(set(segs[3]), {"start", "end", "text", "words"})

    def test_works_with_prompt_builder(self):
        norm = normalize_tree(self.tree)
        self.assertAlmostEqual(calc_duration(["p01", "p02"], norm), 45.0)
        self.assertAlmostEqual(calc_duration(["p01", "p01-f01-a01"], norm), self.tree[0]["end"])   # 자식은 안 셈

    def test_scene_context_and_cut_marks(self):
        ctx = scene_context(self.tree)
        self.assertEqual(ctx[0]["place"], "카페 (1차 방문)")
        self.assertEqual(ctx[0]["event"], "메뉴판 보기")
        mark_cut_suggestions(self.tree, [{"start": 1.0, "end": 3.0, "cut": True}])
        first = self.tree[0]["children"][0]["children"][0]["children"][0]
        self.assertIn("AI 컷 제안", first["tags"])

    def test_ai_failure_falls_back_to_rules(self):
        def broken(prompt, schema):
            raise RuntimeError("503 UNAVAILABLE")
        result = build_scene_tree(CLIP, SHOTS, SEGMENTS, ask=broken, **QUIET)
        self.assertEqual(result["source"], "rules")
        self.assertTrue(result["notes"] and "규칙" in result["notes"][0])
        self.assertEqual(validate_tree(result["tree"]), [])
        self.assertEqual([s["title"] for s in result["tree"]], ["카페 (1차 방문)", "해변 (1차 방문)"])
        self.assertEqual(result["lines"][3]["text"], "와 바다 말라서 좋다")    # 보정 없음

    def test_no_video_analysis_and_no_speech_still_four_levels(self):
        result = build_scene_tree([{"id": "c01", "duration": 50.0, "offset": 0}], [], [], use_ai=False, **QUIET)
        self.assertEqual(validate_tree(result["tree"]), [])
        leaves = [n for n, d in walk(result["tree"]) if d == 4]
        self.assertTrue(all(UNIT_MIN_SEC <= n["end"] - n["start"] <= UNIT_MAX_SEC for n in leaves))
        self.assertIn("영상분석 없음", leaves[0]["tags"])


class SessionTests(unittest.TestCase):
    CLIPS = [{"id": "c01", "duration": 20, "offset": 0, "created_at": "2026-10-10T12:00:00"},
             {"id": "c02", "duration": 20, "offset": 20, "created_at": "2026-10-10T12:00:25"},    # 5초 뒤
             {"id": "c03", "duration": 20, "offset": 40, "created_at": "2026-10-10T14:00:00"}]    # 2시간 뒤

    def test_time_gap_forces_new_session_even_if_ai_merges(self):
        shots = [{**shot(0, 20, "카페 안", action="대화"), "clip_id": "c01"},
                 {**shot(20, 40, "카페 안", action="대화"), "clip_id": "c02"},
                 {**shot(40, 60, "카페 안", action="대화"), "clip_id": "c03"}]
        ask, prompts = fake_ai([{"title": "카페 (1차 방문)", "summary": "", "flows": [
            {"title": "대화 흐름", "summary": "", "steps": [step("s0001", "수다")]}]}])
        result = build_scene_tree(self.CLIPS, shots, [], ask=ask, **QUIET)
        self.assertIn("[촬영 끊김", "".join(prompts))
        self.assertIn("[클립 바뀜: c02", "".join(prompts))
        titles = [s["title"] for s in result["tree"]]
        self.assertEqual(len(titles), 2)                       # c01+c02는 이어서, c03은 새 세션
        self.assertEqual(result["tree"][1]["start"], 40.0)
        self.assertEqual(validate_tree(result["tree"]), [])

    def test_breaks_mark_hard_only_for_long_gaps(self):
        clips = normalize_clips(self.CLIPS)
        units = [{"clip_id": c, "id": f"s{i}"} for i, c in enumerate(["c01", "c01", "c02", "c03"])]
        breaks = session_breaks(units, clips)
        self.assertEqual({i: b["hard"] for i, b in breaks.items()}, {2: False, 3: True})

    def test_rules_count_revisits(self):
        units = [{"id": f"s{i}", "place": p, "action": a, "lines": [], "desc": ""}
                 for i, (p, a) in enumerate([("카페", "주문"), ("카페", "주문"), ("카페", "결제"), ("한강", "산책"),
                                             ("한강", "산책"), ("카페", "주문")])]
        out = fallback_structure(units, {})
        self.assertEqual([s["title"] for s in out["sessions"]], ["카페 (1차 방문)", "한강 (1차 방문)", "카페 (2차 방문)"])
        self.assertEqual([s["title"] for s in out["steps"]], ["주문", "결제", "산책", "주문"])
        self.assertEqual(out["flows"][0]["title"], "주문 흐름")

    def test_rules_ignore_one_scene_place_blip(self):
        units = [{"id": f"s{i}", "place": p, "action": "구경", "lines": [], "desc": ""}
                 for i, p in enumerate(["카페", "카페 입구", "카페"])]
        self.assertEqual(len(fallback_structure(units, {})["sessions"]), 1)


if __name__ == "__main__":
    unittest.main()
