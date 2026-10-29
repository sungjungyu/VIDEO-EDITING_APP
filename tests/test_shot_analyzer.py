import unittest

from shot_analyzer import SHOT_SCHEMA, build_prompt, chunk_bounds, clean_shots, merge_short, remember


def raw(st, en, desc, **extra):
    return {"start": st, "end": en, "desc": desc, "place": "카페", "action": "", "people": [], "visible_text": "",
            "event": "", "mood": "", **extra}


class ChunkTests(unittest.TestCase):
    def test_short_clip_is_one_chunk(self):
        self.assertEqual(chunk_bounds(120.0, 300.0), [(0.0, 120.0)])

    def test_long_clip_splits_and_short_tail_joins_previous(self):
        self.assertEqual(chunk_bounds(650.0, 300.0), [(0.0, 300.0), (300.0, 600.0), (600.0, 650.0)])
        self.assertEqual(chunk_bounds(620.0, 300.0), [(0.0, 300.0), (300.0, 620.0)])   # 꼬리 20초는 앞에 붙임


class CleanShotsTests(unittest.TestCase):
    def test_fills_gaps_and_overlaps_to_cover_whole_clip(self):
        shots = clean_shots([raw(1, 5, "가"), raw(6, 11, "나"), raw(10, 16, "다")], 16.0)
        self.assertEqual([(s["start"], s["end"], s["desc"]) for s in shots],
                         [(0.0, 5.5, "가"), (5.5, 10, "나"), (10, 16.0, "다")])

    def test_parses_mmss_and_string_people(self):
        shots = clean_shots([raw("0:00", "0:04", "가", people="검은 티셔츠, 모자 쓴 사람"), raw("0:04", "0:09", "나")], 9.0)
        self.assertEqual(shots[0]["people"], ["검은 티셔츠", "모자 쓴 사람"])
        self.assertEqual(shots[1]["start"], 4.0)

    def test_merges_short_and_identical_neighbors(self):
        shots = clean_shots([raw(0, 4, "가"), raw(4, 5, "번쩍", event="플래시"), raw(5, 9, "나"), raw(9, 13, "나")], 13.0)
        self.assertEqual([(s["start"], s["end"], s["desc"]) for s in shots], [(0.0, 5, "가"), (5, 13.0, "나")])
        self.assertEqual(shots[0]["event"], "플래시")                 # 합쳐진 장면의 사건은 남긴다

    def test_empty_or_broken_output_becomes_one_flagged_shot(self):
        for bad in ([], [{"start": "x"}], [raw(5, 3, "거꾸로")]):
            shots = clean_shots(bad, 7.0)
            self.assertEqual([(s["start"], s["end"], s["flag"]) for s in shots], [(0.0, 7.0, "empty")])

    def test_merge_short_prefers_shorter_neighbor(self):
        shots = merge_short([raw(0, 6, "가"), raw(6, 7, "짧음"), raw(7, 10, "나")], 2.0)
        self.assertEqual([(s["start"], s["end"]) for s in shots], [(0, 6), (6, 10)])


class PromptTests(unittest.TestCase):
    def test_known_labels_carry_over(self):
        known = {}
        remember(known, [raw(0, 4, "카운터 앞에 선다", people=["검은 티셔츠 남성"]), raw(4, 8, "메뉴를 본다", place="카페 카운터")])
        prompt = build_prompt(120.0, 300.0, 600.0, known, 2.0)
        self.assertIn("카페, 카페 카운터", prompt)
        self.assertIn("검은 티셔츠 남성", prompt)
        self.assertIn("카운터 앞에 선다 / 메뉴를 본다", prompt)
        self.assertIn("05:00부터 이어지는 부분", prompt)

    def test_schema_requires_screen_text(self):
        self.assertIn("visible_text", SHOT_SCHEMA["items"]["required"])


if __name__ == "__main__":
    unittest.main()
