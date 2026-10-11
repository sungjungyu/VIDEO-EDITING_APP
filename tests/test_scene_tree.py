import unittest

from prompt_builder import calc_duration, normalize_tree
from scene_tree import build_tree, fallback_scenes

SCENES = [
    {"start": 0.0, "end": 20.0, "place": "카페", "activity": "주문", "event": "메뉴 고르기", "summary": "메뉴판을 본다"},
    {"start": 20.0, "end": 45.0, "place": "카페", "activity": "주문", "event": "", "summary": "음료를 받는다"},
    {"start": 45.0, "end": 70.0, "place": "카페", "activity": "대화", "event": "친구 도착", "summary": "친구가 온다"},
    {"start": 70.0, "end": 90.0, "place": "한강", "activity": "산책", "event": "", "summary": "강변을 걷는다"},
    {"start": 90.0, "end": 100.0, "place": "카페", "activity": "주문", "event": "", "summary": "다시 카페"},
]
SEGS = [
    {"start": 1.0, "end": 3.0, "text": "안녕하세요.", "cut": False},
    {"start": 18.0, "end": 23.0, "text": "아메리카노 두 잔이요.", "cut": True},   # 가운데 20.5 → 두 번째 장면
    {"start": 50.0, "end": 52.0, "text": "왔어?", "cut": False},
]


def walk(nodes, depth=0):
    for n in nodes:
        yield n, depth
        yield from walk(n["children"], depth + 1)


class BuildTreeTests(unittest.TestCase):
    def setUp(self):
        self.tree = build_tree(SCENES, SEGS, 100.0)

    def test_four_levels_place_activity_scene_line(self):
        self.assertEqual([n["title"] for n in self.tree], ["카페", "한강", "카페"])   # 재방문은 새 노드
        cafe = self.tree[0]
        self.assertEqual([a["title"] for a in cafe["children"]], ["주문", "대화"])
        self.assertEqual(len(cafe["children"][0]["children"]), 2)                    # 주문 장면 2개
        self.assertEqual(max(d for _, d in walk(self.tree)), 3)

    def test_line_goes_to_scene_containing_its_middle_and_is_clipped(self):
        second = self.tree[0]["children"][0]["children"][1]
        line = second["children"][0]
        self.assertEqual(line["summary"], "아메리카노 두 잔이요.")
        self.assertEqual((line["start"], line["end"]), (20.0, 23.0))
        self.assertEqual(line["tags"], ["AI 컷 제안"])

    def test_parent_contains_children_and_ids_unique(self):
        ids = [n["id"] for n, _ in walk(self.tree)]
        self.assertEqual(len(ids), len(set(ids)))
        for node, _ in walk(self.tree):
            for c in node["children"]:
                self.assertTrue(node["start"] <= c["start"] <= c["end"] <= node["end"], (node["id"], c["id"]))

    def test_works_with_prompt_builder(self):
        norm = normalize_tree(self.tree)
        self.assertEqual(calc_duration(["p01"], norm), 70.0)
        self.assertEqual(calc_duration(["p01", "p01-a01-s01"], norm), 70.0)          # 부모 선택 시 자식은 안 셈

    def test_scene_titles_use_event_then_summary(self):
        sits = self.tree[0]["children"][0]["children"]
        self.assertEqual([s["title"] for s in sits], ["메뉴 고르기", "음료를 받는다"])


class FallbackTests(unittest.TestCase):
    def test_no_scenes_splits_by_pauses(self):
        segs = [{"start": 0, "end": 2, "text": "가"}, {"start": 2.5, "end": 4, "text": "나"},
                {"start": 8, "end": 9, "text": "다"}]
        tree = build_tree([], segs, 10.0)
        self.assertEqual(tree[0]["title"], "영상 전체 (영상분석 없음)")
        sits = tree[0]["children"][0]["children"]
        self.assertEqual([len(s["children"]) for s in sits], [2, 1])                 # 4초 쉼에서 나뉨
        self.assertEqual((tree[0]["start"], tree[0]["end"]), (0.0, 10.0))

    def test_no_scenes_no_lines(self):
        self.assertEqual(fallback_scenes([], 5.0)[0]["end"], 5.0)
        self.assertEqual(build_tree([], [], 5.0)[0]["children"][0]["children"][0]["children"], [])


if __name__ == "__main__":
    unittest.main()
