"""평가 벤치마크: 검수한 프로젝트 → 정답 묶음 저장 → 방법별 채점."""

from __future__ import annotations

import pytest

from vibecut.domain.models import Analysis, AnalysisState, ClipInfo, ClipSpan, Line, LineDecision
from vibecut.errors import BadRequest, Conflict
from vibecut.services import bench as bench_service
from vibecut.services import editing as editing_service
from vibecut.storage.bench import BenchStore
from vibecut.storage.projects import ProjectStore

TEXTS = ["오늘은 성수동 카페에 왔어요", "음 어", "여기 소금빵이 유명하대요", "여기 소금빵이 진짜 유명하대요",
         "다시 갈게", "", "맛이 정말 좋네요"]


def reviewed_project(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create("카페 브이로그")
    lines = [Line(seg_id=f"s{i:03d}", clip_id="c01", start=i * 3.0, end=i * 3.0 + 2.5, text=t)
             for i, t in enumerate(TEXTS)]
    analysis = Analysis(clips=[ClipSpan(clip_id="c01", offset=0, duration=21)], lines=lines,
                        judgments={"s001": LineDecision(seg_id="s001", keep=False, reason="군더더기")},
                        engines={"judge": "rule"})

    def add(p):
        p.clips.append(ClipInfo(clip_id="c01", filename="cafe.mp4", stored_name="c01.mp4", duration=21, sha1="ab"))
        p.timeline.append("c01")
        p.analysis = AnalysisState(status="done")

    store.update(project.project_id, add)
    store.save_analysis(project.project_id, analysis)
    # 사람이 검수: NG 앞부분(s002)과 촬영 지시(s004)를 뺀다
    editing_service.patch_lines(store, project.project_id, [editing_service.LineChange(seg_id="s002", keep=False),
                                                            editing_service.LineChange(seg_id="s004", keep=False)])
    return store, project.project_id


def test_save_case_uses_current_keep_and_cut_as_gold_and_overwrites(tmp_path):
    store, pid = reviewed_project(tmp_path)
    bench = BenchStore(tmp_path)
    case = bench_service.save_case(store, bench, pid, person="민지", split="tune")
    assert case.gold["s001"].reason == "군더더기"                         # 엔진 판단을 그대로 둔 것
    assert case.gold["s002"].keep is False and case.gold["s002"].reason == "직접"   # 사람이 뺀 것
    assert case.gold["s000"].keep is True
    assert "s005" not in case.spoken_ids                                  # 글자 없는 문장은 채점하지 않음
    assert case.clips[0].sha1 == "ab" and case.person == "민지" and case.split == "tune"
    again = bench_service.save_case(store, bench, pid)
    assert again.case_id == case.case_id and len(bench.list_cases()) == 1
    assert (tmp_path / "bench" / "cases" / f"{case.case_id}.json").exists()
    store.wipe_media()                                                    # 프로젝트가 지워져도 정답은 남는다
    assert bench.load_case(case.case_id).gold["s004"].keep is False


def test_save_case_needs_finished_analysis(tmp_path):
    store = ProjectStore(tmp_path)
    pid = store.create("빈 프로젝트").project_id
    with pytest.raises(Conflict):
        bench_service.save_case(store, BenchStore(tmp_path), pid)


class FakeGemini:
    available = True

    def generate_json(self, prompt, schema, **kwargs):
        return {"decisions": [{"id": "s002", "keep": False, "reason": "NG", "confidence": 0.9, "emphasis": False,
                               "note": "다시 말함"}]}


def test_run_bench_scores_rule_and_gemini_and_skips_unavailable(tmp_path):
    store, pid = reviewed_project(tmp_path)
    bench = BenchStore(tmp_path)
    bench_service.save_case(store, bench, pid)
    result = bench_service.run_bench(bench, FakeGemini(), ci_rounds=50)
    rows = {r["method"]: r["score"] for r in result["rows"]}
    assert result["cases"][0]["sentences"] == 6 and result["cases"][0]["gold_cut"] == 3
    assert rows["rule"]["ai_ratio"] == 0 and rows["gemini"]["ai_ratio"] == 1.0
    assert rows["gemini"]["tp"] >= 2                                      # 규칙이 잡은 것 + Gemini가 잡은 NG
    offline = bench_service.run_bench(bench, None, ci_rounds=0)
    assert [r["method"] for r in offline["rows"]] == ["rule"] and offline["skipped"] == ["gemini", "hybrid"]


def test_run_bench_without_cases_explains_how_to_make_them(tmp_path):
    with pytest.raises(Conflict, match="검수 완료"):
        bench_service.run_bench(BenchStore(tmp_path), None)


def test_run_bench_hybrid_and_threshold_variants(tmp_path):
    store, pid = reviewed_project(tmp_path)
    bench = BenchStore(tmp_path)
    bench_service.save_case(store, bench, pid)
    result = bench_service.run_bench(bench, FakeGemini(), ["hybrid", "hybrid@0.5"], ci_rounds=0)
    rows = {r["method"]: r["score"] for r in result["rows"]}
    assert set(rows) == {"hybrid", "hybrid@0.5"}
    assert rows["hybrid"]["ai_ratio"] < 1.0                               # 모든 문장을 보내지 않는다
    with pytest.raises(BadRequest):
        bench_service.run_bench(bench, None, ["hybrid@2"])
