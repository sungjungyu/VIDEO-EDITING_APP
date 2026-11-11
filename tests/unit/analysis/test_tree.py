"""4단 트리 (analysis.tree + services.tree): 서버 분석 결과 → 트리. AI 없음."""

from __future__ import annotations

from vibecut.domain.models import Analysis, ClipInfo, ClipSpan, Line, Scene, Word
from vibecut.services import tree as tree_service
from vibecut.storage.projects import ProjectStore


def sample_analysis() -> tuple[Analysis, list[ClipInfo]]:
    """클립 2개: c01 120초(장면 2개, 2초마다 문장), c02 60초(장면 1개, 앞 20초만 말함). 시각은 클립 안 초."""
    def lines(clip_id: str, upto: float, prefix: str) -> list[Line]:
        out, t, i = [], 1.0, 0
        while t + 1.5 <= upto:
            i += 1
            text = f"{prefix} 문장 {i}번입니다 아주 길게 말해 보는 대사."
            out.append(Line(seg_id=f"{clip_id}-{i:03d}", clip_id=clip_id, start=t, end=t + 1.5, text=text,
                            words=[Word(word=w, start=t + k * 0.3, end=t + k * 0.3 + 0.25)
                                   for k, w in enumerate(text.split()[:5])]))
            t += 2.0
        return out

    scenes = [Scene(scene_id="s001", clip_id="c01", start=0, end=70, place="카페", activity="주문",
                    people="민수, 경우", summary="카페에서 주문한다", source="gemini"),
              Scene(scene_id="s002", clip_id="c01", start=70, end=120, place="카페", activity="먹기",
                    people="민수", summary="케이크를 먹는다", source="gemini"),
              Scene(scene_id="s003", clip_id="c02", start=0, end=60, place="거리", activity="걷기",
                    people="", summary="거리를 걷는다", source="gemini")]
    analysis = Analysis(clips=[ClipSpan(clip_id="c01", offset=0, duration=120),
                               ClipSpan(clip_id="c02", offset=120, duration=60)],
                        lines=lines("c01", 120, "카페") + lines("c02", 20, "거리"), scenes=scenes)
    clips = [ClipInfo(clip_id="c01", filename="카페.mp4", stored_name="c01.mp4", duration=120, created_at=1000.0),
             ClipInfo(clip_id="c02", filename="거리.mp4", stored_name="c02.mp4", duration=60, created_at=1130.0)]
    return analysis, clips


def walk(nodes, level=None):
    for n in nodes:
        if level is None or n["level"] == level:
            yield n
        yield from walk(n["children"], level)


def test_inputs_move_to_timeline_seconds_and_rename_fields():
    analysis, clips = sample_analysis()
    tree_clips, shots, segments = tree_service.tree_inputs(analysis, clips)
    assert [c["offset"] for c in tree_clips] == [0, 120] and tree_clips[1]["created"] == 1130.0
    assert shots[2] == {"clip_id": "c02", "start": 120, "end": 180, "desc": "거리를 걷는다", "place": "거리",
                        "action": "걷기", "people": [], "event": "", "mood": ""}
    assert shots[0]["people"] == ["민수", "경우"]
    c02 = [s for s in segments if s["clip_id"] == "c02"][0]
    assert c02["start"] == 121.0 and c02["words"][0]["start"] == 121.0      # 클립 안 1초 → 타임라인 121초


def test_tree_covers_timeline_and_l4_is_10_to_30_seconds():
    analysis, clips = sample_analysis()
    doc = tree_service.build_tree_doc(analysis, clips)
    tree = doc["tree"]
    assert doc["meta"]["source"] == "rules" and not doc["warnings"]
    assert tree[0]["start"] == 0 and tree[-1]["end"] == 180
    for parent in walk(tree):
        kids = parent["children"]
        if kids:                                         # 자식이 부모 구간을 빈틈·겹침 없이 덮는다
            assert kids[0]["start"] == parent["start"] and kids[-1]["end"] == parent["end"]
            assert all(a["end"] == b["start"] for a, b in zip(kids, kids[1:]))
        else:
            assert parent["level"] == 4                  # 모든 가지가 L4까지
    l4 = list(walk(tree, 4))
    assert all(10 - 1e-6 <= u["end"] - u["start"] <= 30 + 1e-6 for u in l4)
    assert {u["clip_id"] for u in l4} == {"c01", "c02"}
    assert doc["meta"]["counts"]["l4"] == len(l4)


def test_l4_title_is_first_line_or_scene_description():
    analysis, clips = sample_analysis()
    l4 = list(walk(tree_service.build_tree_doc(analysis, clips)["tree"], 4))
    spoken = l4[0]
    assert spoken["title"] == spoken["lines"][0]["text"][:19] + "…"          # 첫 대사 앞 20자
    assert "words" not in spoken["lines"][0]                                 # 화면으로 보낼 때 단어 시각은 뺀다
    silent = [u for u in l4 if not u["lines"]]
    assert silent and silent[-1]["title"] == "거리를 걷는다"                  # 말 없는 장면은 장면 설명


def test_get_tree_saves_and_rebuilds_when_analysis_changes(tmp_path):
    analysis, clips = sample_analysis()
    store = ProjectStore(tmp_path)
    pid = store.create("트리").project_id

    def add(p):
        p.clips += clips
        p.timeline += [c.clip_id for c in clips]

    store.update(pid, add)
    store.save_analysis(pid, analysis)
    first = tree_service.get_tree(store, pid)
    again = tree_service.get_tree(store, pid)
    assert first["cached"] is False and again["cached"] is True and again["tree"] == first["tree"]

    store.save_analysis(pid, analysis.model_copy(update={"created_at": "2099-01-01T00:00:00"}))
    assert tree_service.get_tree(store, pid)["cached"] is False                # 다시 분석하면 다시 만든다
