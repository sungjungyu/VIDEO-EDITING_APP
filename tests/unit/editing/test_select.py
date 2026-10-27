"""AI 가편집 테스트: 목표 분량 맞추기(fit_duration)와 오프라인 장면 선택."""

from __future__ import annotations

import pytest

from vibecut.domain.models import Analysis, ClipInfo, ClipSpan, EditPlan, Line, TreeNode
from vibecut.editing.planner import compile_plan
from vibecut.editing.select import fit_duration, select_scenes


def test_fit_duration_hits_target_band():
    nodes = [TreeNode(id=f"s{i}", title="", level=2, start=i * 30, end=(i + 1) * 30) for i in range(6)]
    seconds = {n.id: 30.0 for n in nodes}
    scores = {"s0": {"score": 0.9}, "s1": {"score": 0.2}, "s2": {"score": 0.8}, "s3": {"score": 0.1, "never": True},
              "s4": {"score": 0.5}, "s5": {"score": 0.3, "must": True}}
    chosen = fit_duration(nodes, seconds, scores, [], 90.0, {}, {})
    assert set(chosen) == {"s5", "s0", "s2"}                          # must + 점수 높은 순, never 제외


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
