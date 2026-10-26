"""렌더 엔진 실제 실행 테스트 (ffmpeg 필요, 클립 생성 포함 수십 초).

이번 개선의 핵심 확인 사항
    - 키프레임 간격이 긴 영상에서도 프레임 단위로 정확히 자른다 (예전 media_engine: 5초 → 8.09초)
    - 결과 길이 = 계획 길이 (1프레임 이내), 영상·소리 길이가 같다 (컷이 많아도 싱크 유지)
    - 해상도·fps가 다른 클립, 소리 없는 클립을 섞어도 된다
"""

from __future__ import annotations

import pytest

from tests.media_fixtures import frame_lumas, make_clip, stream_durations
from vibecut.media.ffmpeg import probe
from vibecut.models import ClipInfo, EditPlan, Effect, KeepRange, OutputSpec, PlanOptions, SubtitleEvent, Word
from vibecut.render.renderer import render_plan

pytestmark = pytest.mark.slow


def clip_info(clip_id: str, path) -> ClipInfo:
    info = probe(path)
    return ClipInfo(clip_id=clip_id, filename=path.name, stored_name=path.name, duration=info.duration,
                    width=info.width, height=info.height, fps=info.fps, has_audio=info.has_audio)


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    d = tmp_path_factory.mktemp("src")
    a = make_clip(d / "a.mp4", 20, size="320x180", fps=30, gop=150)          # 키프레임 5초 간격
    b = make_clip(d / "b.mp4", 8, size="240x240", fps=25, gop=125, tone=660)
    c = make_clip(d / "c.mp4", 5, size="320x180", fps=30, audio=False)
    return {"c01": a, "c02": b, "c03": c}


def keep_plan(ranges: list[tuple[str, float, float]], **kw) -> EditPlan:
    keep, cursor = [], 0.0
    for clip_id, s, e in ranges:
        keep.append(KeepRange(clip_id=clip_id, start=s, end=e, out_start=cursor))
        cursor += e - s
    plan = EditPlan(output=OutputSpec(aspect="16:9", fps=30), options=PlanOptions(loudness=False), **kw)
    plan.keep, plan.duration = keep, round(cursor, 3)
    return plan


def test_cuts_are_frame_accurate_on_long_gop(sources, tmp_path):
    clips = {"c01": clip_info("c01", sources["c01"])}
    plan = keep_plan([("c01", 3.0, 6.0), ("c01", 12.0, 14.0)])
    out = tmp_path / "accurate.mp4"
    result = render_plan(plan, clips, {"c01": sources["c01"]}, "preview", out, tmp_path / "work")
    assert abs(result["duration"] - 5.0) <= 1 / 30 + 1e-3
    video_sec, audio_sec = stream_durations(out)
    assert abs(video_sec / 30 - 5.0) <= 1 / 30 + 1e-3
    assert abs(audio_sec - 5.0) <= 0.03
    # 결과 첫 프레임 = 원본 90번(3.0초), 결과 3.0초 = 원본 360번(12.0초) → 밝기 90, 104(=360%256)
    first, second = frame_lumas(out, [0.0, 3.0 + 0.5 / 30], 30)
    assert abs(first - 90) <= 2
    assert abs(second - 104) <= 2


def test_mixed_clips_and_many_cuts_stay_in_sync(sources, tmp_path):
    clips = {cid: clip_info(cid, p) for cid, p in sources.items()}
    ranges = [("c01", t, t + 0.4) for t in [0.5 + 0.6 * i for i in range(25)]]      # 25개 짧은 컷
    ranges += [("c02", 1.0, 4.0), ("c03", 0.5, 2.5)]
    plan = keep_plan(ranges)
    plan.effects = [Effect(clip_id="c02", start=2.0, end=3.0, scale=1.1)]
    plan.events = [SubtitleEvent(start=0.2, end=2.0, text="안녕하세요\n두 번째 줄",
                                 words=[Word(word="안녕하세요", start=0.2, end=0.9),
                                        Word(word="두", start=1.0, end=1.2), Word(word="번째", start=1.2, end=1.5),
                                        Word(word="줄", start=1.5, end=1.9)], word_lines=[0, 1, 1, 1])]
    plan.styles["subtitle"].karaoke = True
    out = tmp_path / "mixed.mp4"
    result = render_plan(plan, clips, sources, "preview", out, tmp_path / "work2")
    expected = 25 * 0.4 + 3.0 + 2.0
    assert abs(result["duration"] - expected) <= 1 / 30 + 0.01
    assert (result["width"], result["height"]) == (960, 540)
    video_sec, audio_sec = stream_durations(out)
    assert abs(video_sec / 30 - audio_sec) <= 0.05        # 컷 27개에도 영상·소리 길이가 같다


def test_vertical_output_and_cancel(sources, tmp_path):
    import threading

    clips = {"c01": clip_info("c01", sources["c01"])}
    plan = keep_plan([("c01", 0.0, 20.0)])
    plan.output = OutputSpec(aspect="9:16", fps=30)
    out = tmp_path / "vertical.mp4"
    result = render_plan(plan, clips, {"c01": sources["c01"]}, "preview", out, tmp_path / "work3")
    assert (result["width"], result["height"]) == (540, 960)

    cancel = threading.Event()
    cancel.set()
    from vibecut.media.ffmpeg import Canceled
    with pytest.raises(Canceled):
        render_plan(plan, clips, {"c01": sources["c01"]}, "final", tmp_path / "never.mp4", tmp_path / "work4",
                    cancel=cancel)
    assert not (tmp_path / "never.mp4").exists()
