"""비트 나누기 테스트: 큰 경계(클립·장면·긴 쉼), 주제 경계(TextTiling 방식), 길이 제한, B롤 구간."""

from __future__ import annotations

from vibecut.analysis import beats as beats_mod
from vibecut.analysis.beats import boundary_scores, build_beats, split_topics
from vibecut.domain.models import ClipSpan, Line, Scene


def L(seg_id, start, end, text, clip_id="c01"):
    return Line(seg_id=seg_id, clip_id=clip_id, start=start, end=end, text=text)


def S(scene_id, start, end, place, clip_id="c01", **kw):
    return Scene(scene_id=scene_id, clip_id=clip_id, start=start, end=end, place=place, **kw)


CAFE = ["카페 라떼가 정말 부드러워요", "라떼 위에 그림도 예쁘네요", "카페 라떼 가격도 괜찮아요",
        "라떼를 한 잔 더 시킬까 봐요"]
PARK = ["공원 산책로가 넓어요", "공원 나무가 단풍이 들었어요", "산책하는 강아지가 많아요", "공원 벤치에 앉아 쉬어요"]


def test_scene_change_and_long_pause_split_beats_and_clip_order_is_kept():
    lines = [L("a1", 1, 3, "오늘은 카페에 왔어요"), L("a2", 3.5, 5, "메뉴가 많네요"),
             L("a3", 12, 14, "창가에 앉았어요"),                                      # 쉼 7초 → 새 비트
             L("a4", 21, 23, "이제 밖으로 나가요"),                                    # 장면이 바뀜 → 새 비트
             L("b1", 1, 3, "두 번째 클립이에요", "c02")]
    scenes = [S("s1", 0, 20, "카페"), S("s2", 20, 30, "거리"), S("s3", 0, 10, "공원", "c02")]
    spans = [ClipSpan(clip_id="c01", offset=0, duration=30), ClipSpan(clip_id="c02", offset=30, duration=10)]
    beats = build_beats(spans, scenes, lines, {"c01": "클립 1", "c02": "클립 2"})
    speech = [b for b in beats if b.kind == "speech"]
    assert [b.seg_ids for b in speech] == [["a1", "a2"], ["a3"], ["a4"], ["b1"]]
    assert [b.place for b in speech] == ["카페", "카페", "거리", "공원"]
    assert speech[0].beat_id == "b-a1" and speech[0].title == "오늘은 카페에 왔어요"
    assert [b.clip_id for b in beats] == sorted([b.clip_id for b in beats])               # 타임라인 순서


def test_topic_shift_splits_long_run_at_the_topic_boundary(monkeypatch):
    monkeypatch.setattr(beats_mod, "IDEAL_BEAT", 10.0)
    texts = CAFE + PARK
    lines = [L(f"t{i}", i * 2.5, i * 2.5 + 2.0, t) for i, t in enumerate(texts)]       # 쉼은 모두 0.5초로 같다
    groups = split_topics(lines)
    assert [[line.seg_id for line in g] for g in groups] == [[f"t{i}" for i in range(4)],
                                                              [f"t{i}" for i in range(4, 8)]]


def test_one_topic_is_not_split_and_long_run_respects_max_and_min():
    same = ["카페 라떼가 정말 부드러워요", "라떼 위에 그림도 예쁘네요", "카페 라떼 가격도 괜찮아요",
            "라떼를 한 잔 더 시킬까 봐요", "카페 라떼 향이 진해요", "라떼 우유가 고소해요", "카페 라떼 잔이 예뻐요",
            "라떼 한 잔 더 마셔요"]
    one_topic = [L(f"s{i}", i * 2.5, i * 2.5 + 2.0, t) for i, t in enumerate(same)]     # 19.5초, 주제 하나
    assert max(boundary_scores(one_topic)) < beats_mod.STRONG and len(split_topics(one_topic)) == 1
    long = [L(f"l{i}", i * 3.0, i * 3.0 + 2.5, f"같은 이야기를 계속 해요 {i}") for i in range(30)]   # 약 90초
    groups = split_topics(long)
    for g in groups:
        dur = g[-1].end - g[0].start
        assert dur <= beats_mod.MAX_BEAT and dur >= beats_mod.MIN_BEAT


def test_quiet_regions_become_broll_beats_without_touching_speech():
    lines = [L("a", 0.5, 3.0, "안녕하세요"), L("b", 12.0, 14.0, "다시 말해요")]
    scenes = [S("s1", 0, 20, "한강", event="노을")]
    beats = build_beats([ClipSpan(clip_id="c01", offset=0, duration=20)], scenes, lines, {})
    broll = [b for b in beats if b.kind == "broll"]
    assert [(b.start, b.end) for b in broll] == [(3.5, 8.5), (14.5, 19.5)]
    assert all(b.title == "노을" and b.place == "한강" and not b.seg_ids for b in broll)
    picked = build_beats([ClipSpan(clip_id="c01", offset=0, duration=20)], scenes, lines, {},
                         pick_window=lambda cid, s, e: (e - 3.0, e))     # 다른 기준으로 고를 수 있다 (T4 품질 곡선)
    assert [(b.start, b.end) for b in picked if b.kind == "broll"] == [(8.7, 11.7), (17.0, 20.0)]


def test_clip_without_scenes_uses_clip_label_as_place():
    beats = build_beats([ClipSpan(clip_id="c01", offset=0, duration=5)], [], [L("a", 0.5, 2, "말해요")],
                        {"c01": "클립 1 · cafe"})
    assert beats[0].place == "클립 1 · cafe"
