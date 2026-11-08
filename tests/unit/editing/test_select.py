"""AI 가편집 테스트: 비트 점수, 분량 맞추기(동적계획법 fit_duration), 오프라인 선택."""

from __future__ import annotations

import pytest

from vibecut.domain.models import Analysis, Beat, ClipInfo, ClipSpan, EditPlan, Line
from vibecut.editing.planner import compile_plan
from vibecut.editing.select import _keywords, fit_duration, score_beats, select_beats


def B(beat_id, start, end, kind="speech", clip_id="c01", **kw) -> Beat:
    return Beat(beat_id=beat_id, kind=kind, clip_id=clip_id, start=start, end=end, **kw)


def test_fit_duration_finds_exact_combination_greedy_misses():
    """점수순 greedy는 60초짜리를 먼저 넣고 막히지만(60초), 동적계획법은 50+40=90초를 찾는다."""
    beats = [B("a", 0, 60), B("b", 60, 110), B("c", 110, 150)]
    seconds = {"a": 60.0, "b": 50.0, "c": 40.0}
    scores = {"a": {"score": 0.9}, "b": {"score": 0.8}, "c": {"score": 0.8}}
    assert fit_duration(beats, seconds, scores, [], 90.0) == ["b", "c"]


def test_fit_duration_respects_locked_never_and_time_order():
    beats = [B("a", 0, 10), B("b", 10, 20), B("c", 20, 30), B("d", 30, 40)]
    seconds = {k: 10.0 for k in "abcd"}
    scores = {"a": {"score": 0.1}, "b": {"score": 0.9, "never": True}, "c": {"score": 0.8}, "d": {"score": 0.7}}
    chosen = fit_duration(beats, seconds, scores, ["a"], 20.0)
    assert chosen == ["a", "c"]                                      # 고정 a + 점수 높은 c, never b 제외, 시간순


def test_fit_duration_limits_broll_but_uses_it_when_material_is_short():
    beats = [B("s1", 0, 10), B("r1", 10, 15, "broll"), B("r2", 15, 20, "broll"), B("s2", 20, 30)]
    seconds = {"s1": 10.0, "r1": 5.0, "r2": 5.0, "s2": 10.0}
    scores = {"s1": {"score": 0.5}, "r1": {"score": 0.9}, "r2": {"score": 0.9}, "s2": {"score": 0.5}}
    assert fit_duration(beats, seconds, scores, [], 20.0) == ["s1", "s2"]      # B롤은 목표의 25%까지만
    assert set(fit_duration(beats, seconds, scores, [], 30.0)) == {"s1", "r1", "r2", "s2"}   # 모자라면 제한을 푼다


def test_keywords_preserve_korean_nouns_starting_with_josa_chars():
    want, avoid = _keywords("이태원 맛집 위주로, 산책 장면은 빼줘")
    assert "이태원" in want and "맛집" in want
    assert "산책" in avoid


def beat_analysis():
    """30초 장면 8개, 장면마다 말 비트 하나(문장 3개)와 B롤 비트 하나."""
    lines, beats = [], []
    for i in range(8):
        t = i * 30.0
        seg = []
        for j in range(3):
            sid = f"t{i * 3 + j + 1:04d}"
            s = t + j * 7 + 1
            lines.append(Line(seg_id=sid, clip_id="c01", start=s, end=s + 6, text=f"장면{i} 대사{j} 이야기 {sid}"))
            seg.append(sid)
        place = "카페" if i in (2, 5) else "거리"
        beats.append(B(f"b-{seg[0]}", t + 1, t + 21, seg_ids=seg, place=place, title=f"장면{i}"))
        beats.append(B(f"r-c01-{int((t + 22) * 10)}", t + 22, t + 27, "broll", place=place, title="풍경"))
    analysis = Analysis(clips=[ClipSpan(clip_id="c01", offset=0, duration=240)], lines=lines, beats=beats)
    clip = ClipInfo(clip_id="c01", filename="a.mp4", stored_name="c01.mp4", duration=240, fps=30)
    return analysis, clip


@pytest.mark.parametrize("target", [40.0, 60.0, 95.0, 120.0])
def test_select_beats_offline_reaches_target(target):
    analysis, clip = beat_analysis()
    plan = EditPlan()
    selection, engine, warnings = select_beats(analysis, {"c01": clip}, plan, {}, target, "카페 장면 위주로",
                                               [], {}, None)
    assert engine == "rule" and selection.mode == "auto" and not warnings
    plan.selection = selection
    out = compile_plan(plan, [clip], analysis)
    assert abs(out.duration / target - 1) <= 0.05, (out.duration, target)
    assert "b-t0007" in selection.beat_ids or "b-t0016" in selection.beat_ids    # 요청 단어(카페)가 있는 장면 우선
    assert selection.reasons and selection.ai_beat_ids == selection.beat_ids


def test_score_beats_penalizes_repeated_content_and_avoided_words():
    lines = [Line(seg_id="a", clip_id="c01", start=0, end=5, text="이 카페 라떼가 정말 맛있어요"),
             Line(seg_id="b", clip_id="c01", start=10, end=15, text="이 카페 라떼가 정말 맛있어요 진짜로"),
             Line(seg_id="c", clip_id="c01", start=20, end=25, text="공원에서 산책을 했어요")]
    beats = [B("b-a", 0, 5, seg_ids=["a"]), B("b-b", 10, 15, seg_ids=["b"]), B("b-c", 20, 25, seg_ids=["c"])]
    analysis = Analysis(clips=[ClipSpan(clip_id="c01", offset=0, duration=30)], lines=lines, beats=beats)
    scores = score_beats(beats, analysis, {}, "산책은 빼줘")
    repeated = [k for k in ("b-a", "b-b") if "비슷함" in scores[k]["reason"]]
    assert len(repeated) == 1                                         # 둘 중 하나만 깎는다
    assert scores["b-c"]["never"] is True
