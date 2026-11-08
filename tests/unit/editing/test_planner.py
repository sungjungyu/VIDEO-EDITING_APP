"""편집 계획 계산 (planner) 테스트 — 영상 없이 숫자만으로 확인한다."""

from __future__ import annotations

from vibecut.domain.models import (
    Analysis,
    Beat,
    ClipInfo,
    ClipSpan,
    EditPlan,
    KeepRange,
    Line,
    LineDecision,
    OutputSpec,
    PlanOptions,
    Selection,
    Word,
)
from vibecut.editing import planner as planner_mod
from vibecut.editing.planner import compile_plan, count_word_cuts, plan_clip, validate_plan

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
    beats = [Beat(beat_id="b-t0001", kind="speech", clip_id="c01", start=0.0, end=8.0,
                  seg_ids=["t0001", "t0002", "t0003"], place="카페"),
             Beat(beat_id="r-c01-80", kind="broll", clip_id="c01", start=8.0, end=20.0, place="카페"),
             Beat(beat_id="b-t0004", kind="speech", clip_id="c02", start=0.0, end=10.0, seg_ids=["t0004"],
                  place="거리")]
    analysis = Analysis(clips=[ClipSpan(clip_id="c01", offset=0.0, duration=20.0),
                               ClipSpan(clip_id="c02", offset=20.0, duration=10.0)],
                        lines=lines, beats=beats,
                        judgments={"t0002": cut("t0002"),
                                   "t0003": LineDecision(seg_id="t0003", keep=True, reason="핵심", emphasis=True,
                                                         confidence=0.9)})
    return analysis, clips


def test_compile_plan_multi_clip_selection_events_and_effects():
    analysis, clips = analysis_two_clips()
    plan = EditPlan(selection=Selection(mode="manual", beat_ids=["b-t0001", "b-t0004"]))
    plan.options.max_pause = None
    out = compile_plan(plan, clips, analysis)
    assert [k.clip_id for k in out.keep][0] == "c01" and out.keep[-1].clip_id == "c02"
    assert all(k.end <= 8.2 for k in out.keep if k.clip_id == "c01")          # 풍경 비트(8~20초)는 빠짐
    total = sum(k.end - k.start for k in out.keep)
    assert abs(out.duration - total) < 1e-3
    assert out.keep[0].out_start == 0.0
    for a, b in zip(out.keep, out.keep[1:]):
        assert abs(b.out_start - (a.out_start + a.end - a.start)) < 1e-3
    texts = [e.text.replace("\n", " ") for e in out.events]
    assert "음" not in texts                                                  # 자른 문장은 자막도 없다
    assert any("두 번째 클립" in t for t in texts)
    punch = [fx for fx in out.effects if fx.type == "punch_in"]
    assert len(punch) == 1 and punch[0].seg_id == "t0003"
    jumps = [fx for fx in out.effects if fx.type == "jump_cut"]                # '음'을 잘라 이은 곳 뒤는 확대
    assert len(jumps) == 1 and jumps[0].clip_id == "c01" and jumps[0].start > 3.8
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
    plan = EditPlan(selection=Selection(mode="manual", beat_ids=[]))
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


def test_count_word_cuts_counts_boundaries_inside_words():
    words_line = line("t1", 0.0, 2.0, "하나 둘 셋 넷")
    lines = {"c01": [words_line]}
    assert count_word_cuts([KeepRange(clip_id="c01", start=0.0, end=2.0)], lines) == 0
    mid = (words_line.words[1].start + words_line.words[1].end) / 2
    assert count_word_cuts([KeepRange(clip_id="c01", start=mid, end=2.0)], lines) == 1


def test_output_aspect_follows_clip_orientation_until_user_picks_one():
    vertical = clip("c01", 20.0).model_copy(update={"width": 1080, "height": 1920})
    wide = clip("c02", 5.0).model_copy(update={"width": 1920, "height": 1080, "filename": "wide.mp4"})
    out = compile_plan(EditPlan(), [vertical, wide], None)
    assert out.output.aspect == "9:16" and out.output.aspect_source == "auto"     # 세로가 더 길다
    assert any("wide.mp4" in w and "양옆" in w for w in out.warnings)              # 섞여 있으면 알려 준다
    assert compile_plan(EditPlan(), [wide], None).output.aspect == "16:9"
    chosen = EditPlan(output=OutputSpec(aspect="16:9"))                              # 직접 고른 비율
    assert chosen.output.aspect_source == "user"
    out = compile_plan(chosen, [vertical], None)
    assert out.output.aspect == "16:9" and any("위아래" in w for w in out.warnings)
    unknown = clip("c03", 5.0)                                                       # 크기를 모르면 그대로
    assert compile_plan(EditPlan(), [unknown], None).output.aspect == "16:9"



def test_jump_cut_zoom_alternates_within_a_clip_and_resets_on_new_clip():
    ranges = [("c01", 0, 2), ("c01", 3, 5), ("c01", 6, 8), ("c01", 8.1, 9), ("c02", 0, 2), ("c02", 4, 6)]
    keep = [KeepRange(clip_id=c, start=s, end=e, out_start=0) for c, s, e in ranges]
    fx = planner_mod._jump_cut_effects(keep, PlanOptions())
    # 0~2 원래 크기 → (컷) 3~5 확대 → (컷) 6~8 원래 → (0.1초는 이어진 것) 8.1~9 원래 → 새 클립 원래 → (컷) 확대
    assert [(e.clip_id, e.start) for e in fx] == [("c01", 3), ("c02", 4)]
    assert all(e.type == "jump_cut" and e.scale == 1.1 for e in fx)
    assert planner_mod._jump_cut_effects(keep, PlanOptions(jump_zoom=False)) == []


def test_speech_spans_are_in_output_time_and_skip_cut_lines():
    lines = {"c01": [line("a", 1.0, 2.0, "첫 말", "c01"), line("b", 6.0, 7.0, "뺀 말", "c01"),
                     line("c", 10.0, 11.0, "끝 말", "c01")]}
    keep = [KeepRange(clip_id="c01", start=0.5, end=3.0, out_start=0.0),
            KeepRange(clip_id="c01", start=9.5, end=12.0, out_start=2.5)]
    spans = planner_mod.speech_spans(keep, lines, {"b": cut("b")})
    assert spans == [(0.5, 1.5), (3.0, 4.0)]                     # 결과 초, 뺀 문장은 없음
