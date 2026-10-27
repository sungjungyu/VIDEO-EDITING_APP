"""4단 트리 (장소 → 일 → 상황 → 대사) 묶기 테스트."""

from __future__ import annotations

import pytest

from vibecut.analysis.tree import fallback_scenes, group_tree

SCENES = [
    {"start": 0.0, "end": 20.0, "place": "카페", "activity": "주문", "event": "메뉴 고르기",
     "summary": "메뉴판을 본다"},
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


@pytest.fixture
def tree():
    return group_tree(SCENES, SEGS, 100.0)


def test_four_levels_place_activity_scene_line(tree):
    assert [n["title"] for n in tree] == ["카페", "한강", "카페"]   # 재방문은 새 노드
    cafe = tree[0]
    assert [a["title"] for a in cafe["children"]] == ["주문", "대화"]
    assert len(cafe["children"][0]["children"]) == 2                    # 주문 장면 2개
    assert max(d for _, d in walk(tree)) == 3


def test_line_goes_to_scene_containing_its_middle_and_is_clipped(tree):
    line = tree[0]["children"][0]["children"][1]["children"][0]
    assert line["summary"] == "아메리카노 두 잔이요."
    assert (line["start"], line["end"]) == (20.0, 23.0)
    assert line["tags"] == ["AI 컷 제안"]


def test_parent_contains_children_and_ids_unique(tree):
    ids = [n["id"] for n, _ in walk(tree)]
    assert len(ids) == len(set(ids))
    for node, _ in walk(tree):
        for c in node["children"]:
            assert node["start"] <= c["start"] <= c["end"] <= node["end"], (node["id"], c["id"])


def test_scene_titles_use_event_then_summary(tree):
    assert [s["title"] for s in tree[0]["children"][0]["children"]] == ["메뉴 고르기", "음료를 받는다"]


def test_no_scenes_splits_by_pauses():
    segs = [{"start": 0, "end": 2, "text": "가"}, {"start": 2.5, "end": 4, "text": "나"},
            {"start": 8, "end": 9, "text": "다"}]
    tree = group_tree([], segs, 10.0)
    assert tree[0]["title"] == "영상 전체 (영상분석 없음)"
    sits = tree[0]["children"][0]["children"]
    assert [len(s["children"]) for s in sits] == [2, 1]                 # 4초 쉼에서 나뉨
    assert (tree[0]["start"], tree[0]["end"]) == (0.0, 10.0)


def test_no_scenes_no_lines():
    assert fallback_scenes([], 5.0)[0]["end"] == 5.0
    assert group_tree([], [], 5.0)[0]["children"][0]["children"][0]["children"] == []
