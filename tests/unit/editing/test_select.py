"""AI 가편집 테스트: 목표 분량 맞추기(fit_duration)와 오프라인 장면 선택."""

from __future__ import annotations

import pytest

from vibecut.domain.models import Analysis, ClipInfo, ClipSpan, EditPlan, Line, TreeNode
from vibecut.editing.planner import compile_plan
from vibecut.editing.select import _keywords, fit_duration, select_scenes


def test_fit_duration_hits_target_band():
    nodes = [TreeNode(id=f"s{i}", title="", level=2, start=i * 30, end=(i + 1) * 30) for i in range(6)]
    seconds = {n.id: 30.0 for n in nodes}
    scores = {"s0": {"score": 0.9}, "s1": {"score": 0.2}, "s2": {"score": 0.8}, "s3": {"score": 0.1, "never": True},
              "s4": {"score": 0.5}, "s5": {"score": 0.3, "must": True}}
    chosen = fit_duration(nodes, seconds, scores, [], 90.0, {}, {})
    assert set(chosen) == {"s5", "s0", "s2"}                          # must + 점수 높은 순, never 제외


def test_keywords_preserve_korean_nouns_starting_with_josa_chars():
    """'서울에서', '도쿄', '이태원에서'처럼 조사 글자로 시작하는 단어의 앞글자가 잘리지 않는다."""
    want, avoid = _keywords("서울에서 도쿄 이태원으로 이동하고, 산책은 빼줘")
    assert "서울" in want and "도쿄" in want and "이태원" in want
    assert "산책" in avoid


def tree_analysis():
    lines, nodes, t = [], [], 0.0
    for i in range(8):                                               # 30초 장면 8개, 장면마다 대사 3개
        children = []
        for j in range(3):
            sid = f"t{i * 3 + j + 1:04d}"
            s = t + j * 9 + 1
            lines.append(Line(seg_id=sid, clip_id="c01", start=s, end=s + 6, text=f"장면{i} 대사{j} 이야기"))
            children.append(TreeNode(id=f"n{i}-l{j}", title="", level=3, start=s, end=s + 6, seg_id=sid))
        nodes.append(TreeNode(id=f"n{i}", title=f"장면{i}", level=2, start=t, end=t + 30, children=children,
                              summary="카페" if i in (2, 5) else ""))
        t += 30
    tree = [TreeNode(id="p", title="장소", level=0, start=0, end=240, children=[
        TreeNode(id="a", title="일", level=1, start=0, end=240, children=nodes)])]
    analysis = Analysis(clips=[ClipSpan(clip_id="c01", offset=0, duration=240)], lines=lines, tree=tree)
    clip = ClipInfo(clip_id="c01", filename="a.mp4", stored_name="c01.mp4", duration=240, fps=30)
    return analysis, clip


@pytest.mark.parametrize("target", [60.0, 95.0, 150.0])
def test_select_scenes_offline_reaches_target(target):
    analysis, clip = tree_analysis()
    plan = EditPlan()
    selection, engine, warnings = select_scenes(analysis, {"c01": clip}, plan, {}, target, "카페 장면 위주로",
                                                [], {}, None)
    assert engine == "rule" and selection.mode == "auto"
    plan.selection = selection
    out = compile_plan(plan, [clip], analysis)
    assert abs(out.duration / target - 1) <= 0.06, (out.duration, target)
    assert "n2" in selection.node_ids or "n5" in selection.node_ids   # 요청 단어(카페)가 있는 장면 우선
    assert selection.reasons


def test_fit_duration_does_not_count_line_twice_when_adding_its_scene():
    """대사(b1)를 먼저 넣은 뒤 그 장면(B)을 통째로 넣으면 b1 길이를 두 번 세지 않고, b1은 B로 바뀐다."""
    b1 = TreeNode(id="b1", title="", level=3, start=100, end=105, seg_id="t0001")
    nodes = [TreeNode(id="A", title="", level=2, start=0, end=60),
             TreeNode(id="B", title="", level=2, start=60, end=110, children=[b1])]
    seconds = {"A": 60.0, "B": 50.0}
    scores = {"A": {"score": 0.9}, "B": {"score": 0.5}}
    chosen = fit_duration(nodes, seconds, scores, [], 100.0, {"t0001": 5.0}, {"t0001": 0.5})
    assert set(chosen) == {"A", "B"}                                  # 예전: {"A", "b1", "B"} (115초로 셈, 실제 110초)
