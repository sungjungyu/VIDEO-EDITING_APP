"""평가 벤치마크 사용 사례 (v4 설계안 T1).

save_case   ④ 확인·수정에서 사람이 검수를 끝낸 프로젝트 → 정답 묶음 (지금 화면의 살림/뺌이 정답)
run_bench   저장한 정답 묶음마다 컷 판단 방법들을 다시 돌려 채점 → 표 + 결과 파일

방법 (METHODS)
    rule    자체 규칙만 (analysis/judge.py rule_decisions)
    gemini  지금 방식: 모든 문장을 Gemini에 보내고 규칙과 합침 (analysis/judge.py judge_lines)
    hybrid  확신도가 낮은 문장만 Gemini에 묻고 나머지는 규칙 (analysis/judge.py judge_hybrid)
            hybrid@0.7처럼 쓰면 '물어볼 기준 확신도'를 바꿔 본다 (조정용 정답으로 기준값을 맞출 때)
AI 응답은 캐시되므로 같은 정답 묶음을 다시 돌리면 요청을 다시 보내지 않는다.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from ..ai.client import GeminiClient
from ..analysis.judge import ASK_BELOW, judge_hybrid, judge_lines
from ..domain.models import BenchCase, BenchClip, GoldLabel, LineDecision, gold_reason
from ..errors import BadRequest, Conflict
from ..eval.bench import pairs_for, score
from ..storage.bench import BenchStore
from ..storage.projects import ProjectStore
from .editing import effective_decisions

# (정답 묶음, Gemini) → (문장별 판단, Gemini에 보낸 문장 id). 쓸 수 없으면 None
Method = Callable[[BenchCase, GeminiClient | None], tuple[dict[str, LineDecision], set[str]] | None]


def _rule(case: BenchCase, client: GeminiClient | None):
    decisions, _engine, _warnings = judge_lines(case.lines, case.scenes, case.profile, None)
    return decisions, set()


def _gemini(case: BenchCase, client: GeminiClient | None):
    if client is None or not client.available:
        return None
    decisions, engine, _warnings = judge_lines(case.lines, case.scenes, case.profile, client)
    if engine != "ai":
        return None
    return decisions, set(case.spoken_ids)


def _hybrid(ask_below: float) -> Method:
    def run(case: BenchCase, client: GeminiClient | None):
        if client is None or not client.available:
            return None
        decisions, _engine, _warnings, asked = judge_hybrid(case.lines, case.scenes, case.profile, client, ask_below)
        return decisions, asked
    return run


METHODS: dict[str, Method] = {"rule": _rule, "gemini": _gemini, "hybrid": _hybrid(ASK_BELOW)}


def method(name: str) -> Method:
    """METHODS 이름 또는 'hybrid@0.7' (물어볼 기준 확신도를 바꾼 하이브리드)."""
    if name in METHODS:
        return METHODS[name]
    if name.startswith("hybrid@"):
        try:
            value = float(name.split("@", 1)[1])
        except ValueError:
            value = -1.0
        if 0.0 < value <= 1.0:
            return _hybrid(value)
    raise BadRequest(f"모르는 방법: {name} (가능: {', '.join(METHODS)}, hybrid@0.7처럼 기준값 지정)")


# ---------------------------------------------------------------- 정답 저장

def save_case(store: ProjectStore, bench: BenchStore, project_id: str, name: str = "", person: str = "",
              split: str = "test", profile: dict | None = None) -> BenchCase:
    project = store.get(project_id)
    analysis = store.load_analysis(project_id)
    if analysis is None or project.analysis is None or project.analysis.status != "done":
        raise Conflict("먼저 분석하고 문장을 검수하세요.")
    if split not in ("tune", "test"):
        raise BadRequest("split은 tune 또는 test입니다.")
    decisions = effective_decisions(store.load_plan(project_id), analysis)
    gold = {}
    for line in analysis.lines:
        d = decisions.get(line.seg_id) or LineDecision(seg_id=line.seg_id)
        gold[line.seg_id] = GoldLabel(keep=d.keep, reason=gold_reason(d.keep, d.reason))
    clips = {c.clip_id: c for c in project.clips}
    old = bench.find_by_project(project_id)
    case = BenchCase(
        case_id=old.case_id if old else bench.new_id(),
        name=name.strip() or project.name, person=person.strip(), split=split,  # type: ignore[arg-type]
        source_project=project_id, judge_engine=analysis.engines.get("judge", ""), profile=profile or {},
        clips=[BenchClip(clip_id=s.clip_id, filename=clips[s.clip_id].filename if s.clip_id in clips else "",
                         sha1=clips[s.clip_id].sha1 if s.clip_id in clips else "", duration=s.duration)
               for s in analysis.clips],
        spans=analysis.clips, lines=analysis.lines, scenes=analysis.scenes, silences=analysis.silences, gold=gold)
    return bench.save_case(case)


def case_summary(case: BenchCase) -> dict:
    ids = case.spoken_ids
    return {"case_id": case.case_id, "name": case.name, "person": case.person, "split": case.split,
            "created_at": case.created_at, "sentences": len(ids),
            "gold_cut": sum(1 for i in ids if not case.gold[i].keep),
            "seconds": round(sum(c.duration for c in case.clips), 1)}


# ---------------------------------------------------------------- 채점

def run_bench(bench: BenchStore, client: GeminiClient | None, methods: list[str] | None = None,
              split: str | None = None, case_ids: list[str] | None = None, ci_rounds: int = 1000) -> dict:
    methods = methods or list(METHODS)
    runners = {name: method(name) for name in methods}
    cases = [bench.load_case(i) for i in case_ids] if case_ids else bench.list_cases()
    if split:
        cases = [c for c in cases if c.split == split]
    if not cases:
        raise Conflict("채점할 정답 묶음이 없습니다. ④ 확인·수정에서 '검수 완료'로 저장하세요.")

    rows, skipped = [], []
    for name in methods:
        pairs, per_case, started = [], [], time.perf_counter()
        for case in cases:
            out = runners[name](case, client)
            if out is None:
                break
            decisions, asked = out
            case_pairs = pairs_for(case.spoken_ids, case.gold, decisions, asked)
            pairs += case_pairs
            per_case.append({"case_id": case.case_id, "name": case.name, **score(case_pairs, ci_rounds=0)})
        else:
            rows.append({"method": name, "seconds": round(time.perf_counter() - started, 2),
                         "score": score(pairs, ci_rounds), "cases": per_case})
            continue
        skipped.append(name)
    return {"cases": [case_summary(c) for c in cases], "split": split, "rows": rows, "skipped": skipped}
