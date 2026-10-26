"""편집 계획 계산 (planner) 테스트 — 영상 없이 숫자만으로 확인한다."""

from __future__ import annotations

from vibecut.edit.planner import compile_plan, merge, plan_clip, subtract
from vibecut.edit.validate import validate_plan
from vibecut.models import (
    Analysis,
    ClipInfo,
    ClipSpan,
    EditPlan,
    Line,
    LineDecision,
    PlanOptions,
    Selection,
    TreeNode,
    Word,
)

FPS = 30


def clip(clip_id="c01", duration=60.0, **kw) -> ClipInfo:
    return ClipInfo(clip_id=clip_id, filename=f"{clip_id}.mp4", stored_name=f"{clip_id}.mp4", duration=duration,
                    fps=FPS, **kw)


def line(seg_id, start, end, text="안녕하세요 반갑습니다", clip_id="c01", words=True) -> Line:
    ws = []
    if words:
        toks = text.split()
        step = (end - start) / len(toks)
        ws = [Word(word=t, start=round(start + i * step, 3), end=round(start + (i + 1) * step - 0.02, 3))
              for i, t in enumerate(toks)]
    return Line(seg_id=seg_id, clip_id=clip_id, start=start, end=end, text=text, words=ws)


def cut(seg_id, reason="군더더기") -> LineDecision:
    return LineDecision(seg_id=seg_id, keep=False, reason=reason, confidence=0.8)


def near(a, b, tol=1.0 / FPS + 1e-6):
    return abs(a - b) <= tol


def test_interval_helpers():
    assert merge([(3, 5), (0, 1), (0.9, 2)]) == [(0, 2), (3, 5)]
    assert merge([(0, 1), (1.2, 2)], gap=0.3) == [(0, 2)]
    assert subtract([(0, 10)], [(2, 3), (5, 6)]) == [(0, 2), (3, 5), (6, 10)]


def test_cut_line_swallows_short_pauses_and_keeps_padding():
    opts = PlanOptions(max_pause=None)
    lines = [line("t1", 1.0, 3.0), line("t2", 3.5, 4.0, "음"), line("t3", 4.6, 7.0)]
    kept = plan_clip(clip(), [(0.0, 10.0)], lines, {"t2": cut("t2")}, {}, [], opts)
    # 잘린 문장 앞뒤 쉼까지 지우고, 남는 문장 끝 +0.12 / 다음 문장 시작 -0.08만 남는다
    assert near(kept[0][1], 3.0 + opts.pad_end)
    assert near(kept[1][0], 4.6 - opts.pad_start)
    assert len(kept) == 2


def test_long_silent_scene_is_kept_and_long_pause_between_lines_is_compressed():
    opts = PlanOptions(max_pause=0.8, pause_limit=4.0)
    lines = [line("t1", 1.0, 3.0), line("t2", 5.0, 7.0), line("t3", 15.0, 17.0)]
    kept = plan_clip(clip(), [(0.0, 20.0)], lines, {}, {}, [], opts)
    total = sum(e - s for s, e in kept)
    # 3~5초(2초 쉼)는 0.2초로 줄고, 7~15초(8초, 말 없는 장면)는 그대로
    assert near(total, 20.0 - (2.0 - opts.pad_end - opts.pad_start), tol=0.07)
    assert any(s <= 8.0 and e >= 14.0 for s, e in kept)


def test_scene_boundary_inside_kept_line_extends_to_whole_line():
    opts = PlanOptions(max_pause=None)
    lines = [line("t1", 9.0, 12.0)]
    kept = plan_clip(clip(), [(0.0, 11.0)], lines, {}, {}, [], opts)      # 문장 가운데(10.5)가 구간 안
    assert near(kept[-1][1], 12.0 + opts.pad_end)
    kept = plan_clip(clip(), [(0.0, 9.8)], lines, {}, {}, [], opts)       # 가운데가 구간 밖 → 문장을 뺀다
    assert kept[-1][1] <= 9.0


def test_boundaries_never_split_a_word_and_snap_to_silence():
    opts = PlanOptions(max_pause=None)
    lines = [line("t1", 1.0, 3.0, "하나 둘 셋 넷"), line("t2", 3.1, 5.0, "다섯 여섯")]
    kept = plan_clip(clip(), [(0.0, 2.2)], lines, {}, {}, [(5.0, 6.0)], opts)
    for s, e in kept:
        for w in lines[0].words + lines[1].words:
            assert not (w.start < s < w.end) and not (w.start < e < w.end), (s, e, w)
    # 무음 직전에 끝나는 경계는 무음 안으로 옮긴다
    kept = plan_clip(clip(), [(0.0, 4.9)], [line("t1", 1.0, 4.85, "하나 둘")], {}, {}, [(4.95, 6.0)],
                     PlanOptions(max_pause=None, pad_end=0.0))
    assert kept[-1][1] >= 4.95


def test_clip_trim_points_and_frame_grid():
    c = clip(in_point=2.0, out_point=8.0)
    kept = plan_clip(c, [(0.0, 60.0)], [], {}, {}, [], PlanOptions())
    assert kept == [(2.0, 8.0)]
    kept = plan_clip(clip(), [(0.013, 5.019)], [], {}, {}, [], PlanOptions())
    for s, e in kept:
        assert abs(s * FPS - round(s * FPS)) < 1e-6 and abs(e * FPS - round(e * FPS)) < 1e-6


def analysis_two_clips() -> tuple[Analysis, list[ClipInfo]]:
    clips = [clip("c01", 20.0), clip("c02", 10.0)]
    lines = [line("t0001", 1.0, 3.0, "첫 번째 장면 이야기", "c01"), line("t0002", 3.4, 3.8, "음", "c01"),
             line("t0003", 4.2, 6.0, "카페에 왔어요 대박!", "c01"), line("t0004", 1.0, 2.5, "두 번째 클립", "c02")]
    tree = [
        TreeNode(id="p01", title="카페", level=0, start=0.0, end=20.0, children=[
            TreeNode(id="p01-a01", title="주문", level=1, start=0.0, end=20.0, children=[
                TreeNode(id="p01-a01-s01", title="입장", level=2, start=0.0, end=8.0),
                TreeNode(id="p01-a01-s02", title="풍경", level=2, start=8.0, end=20.0)])]),
        TreeNode(id="p02", title="거리", level=0, start=20.0, end=30.0, children=[
            TreeNode(id="p02-a01", title="걷기", level=1, start=20.0, end=30.0, children=[
                TreeNode(id="p02-a01-s01", title="산책", level=2, start=20.0, end=30.0)])]),
    ]
    analysis = Analysis(clips=[ClipSpan(clip_id="c01", offset=0.0, duration=20.0),
                               ClipSpan(clip_id="c02", offset=20.0, duration=10.0)],
                        lines=lines, tree=tree,
                        judgments={"t0002": cut("t0002"),
                                   "t0003": LineDecision(seg_id="t0003", keep=True, reason="핵심", emphasis=True,
                                                         confidence=0.9)})
    return analysis, clips


def test_compile_plan_multi_clip_selection_events_and_effects():
    analysis, clips = analysis_two_clips()
    plan = EditPlan(selection=Selection(mode="manual", node_ids=["p01-a01-s01", "p02-a01-s01"]))
    plan.options.max_pause = None
    out = compile_plan(plan, clips, analysis)
    assert [k.clip_id for k in out.keep][0] == "c01" and out.keep[-1].clip_id == "c02"
    assert all(k.end <= 8.2 for k in out.keep if k.clip_id == "c01")          # 풍경 장면(8~20초)은 빠짐
    total = sum(k.end - k.start for k in out.keep)
    assert abs(out.duration - total) < 1e-3
    assert out.keep[0].out_start == 0.0
    for a, b in zip(out.keep, out.keep[1:]):
        assert abs(b.out_start - (a.out_start + a.end - a.start)) < 1e-3
    texts = [e.text.replace("\n", " ") for e in out.events]
    assert "음" not in texts                                                  # 자른 문장은 자막도 없다
    assert any("두 번째 클립" in t for t in texts)
    assert len(out.effects) == 1 and out.effects[0].seg_id == "t0003"
    assert not [i for i in validate_plan(out, clips, analysis) if i["level"] == "error"]


def test_user_overrides_and_text_edit():
    analysis, clips = analysis_two_clips()
    plan = EditPlan()
    plan.lines["t0002"] = LineDecision(seg_id="t0002", keep=True, source="user")
    plan.lines["t0001"] = LineDecision(seg_id="t0001", keep=True, source="user", text="고친 자막")
    out = compile_plan(plan, clips, analysis)
    texts = [e.text.replace("\n", " ") for e in out.events]
    assert "음" in texts and "고친 자막" in texts
    edited = next(e for e in out.events if e.text == "고친 자막")
    assert edited.words == []                    # 고친 글자는 단어 시각과 안 맞아 카라오케 없이


def test_empty_selection_warns_and_unanalyzed_clip_is_included_whole():
    analysis, clips = analysis_two_clips()
    plan = EditPlan(selection=Selection(mode="manual", node_ids=[]))
    out = compile_plan(plan, clips, analysis)
    assert out.keep == [] and any("고른 장면이 없습니다" in w for w in out.warnings)
    extra = clip("c03", 5.0)
    out = compile_plan(EditPlan(), clips + [extra], analysis)
    assert out.keep[-1].clip_id == "c03" and abs(out.keep[-1].end - 5.0) < 1e-6
    assert any("아직 분석하지 않아" in w for w in out.warnings)


def test_long_sentence_is_split_into_two_line_chunks():
    text = "오늘은 성수동에 있는 아주 유명한 카페에 와서 라떼와 소금빵을 먹어 보고 솔직한 후기를 남겨 보려고 합니다"
    analysis = Analysis(clips=[ClipSpan(clip_id="c01", offset=0.0, duration=20.0)],
                        lines=[line("t0001", 1.0, 9.0, text)])
    plan = EditPlan()
    plan.styles["subtitle"].max_chars_per_line = 12
    out = compile_plan(plan, [clip(duration=20.0)], analysis)
    assert len(out.events) >= 3
    for e in out.events:
        assert len(e.text.split("\n")) <= 2
        assert all(len(row) <= 12 for row in e.text.split("\n"))
    for a, b in zip(out.events, out.events[1:]):
        assert a.end <= b.start + 1e-6
