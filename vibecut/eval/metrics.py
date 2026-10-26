"""프로젝트 하나의 평가 지표.

    압축률            결과 길이 / 원본 길이
    분량 정확도        결과 길이 / 목표 분량 (AI 가편집을 썼을 때)
    AI 판단 채택률     AI·규칙이 정한 문장 판단 중 사용자가 뒤집지 않은 비율 (검토 단계 기록)
    AI 장면 선택 유지율 AI가 고른 장면 중 사용자가 그대로 둔 비율
    단어 잘림         남길 구간 경계가 단어 중간에 걸린 수 (0이 정상)
    렌더 길이 오차     최종 렌더 길이 - 계획 길이 (ms, 1프레임 = 33ms 이내가 정상)
    처리 시간·AI 사용량 분석 단계별 시간, 요청 수, 토큰

명령줄: python -m vibecut.eval.metrics <project_id>  → 마크다운 표
"""

from __future__ import annotations

import sys
from collections import Counter

from ..edit.planner import effective_decisions
from ..models import Analysis, EditPlan, Job, Project


def project_metrics(project: Project, analysis: Analysis | None, plan: EditPlan, jobs: list[Job]) -> dict:
    clips = project.timeline_clips()
    source = sum(c.usable_end - c.in_point for c in clips)
    out: dict = {
        "source_sec": round(source, 2),
        "output_sec": plan.duration,
        "compression": round(plan.duration / source, 3) if source else None,
        "keep_ranges": len(plan.keep),
    }
    target = plan.selection.target_sec
    if target:
        out["target_sec"] = target
        out["target_ratio"] = round(plan.duration / target, 3)
    if analysis is not None:
        decisions = effective_decisions(plan, analysis)
        base = analysis.judgments
        user = {sid: d for sid, d in plan.lines.items() if d.source == "user"}
        flipped = [sid for sid, d in user.items() if sid in base and d.keep != base[sid].keep]
        edited = [sid for sid, d in user.items() if d.text]
        decided = [d for d in base.values() if d.source in ("ai", "rule")]
        cut = [d for d in decisions.values() if not d.keep]
        out.update({
            "lines": len(analysis.lines),
            "lines_cut": len(cut),
            "cut_reasons": dict(Counter(d.reason for d in cut)),
            "ai_decisions": sum(1 for d in decided if d.source == "ai"),
            "rule_decisions": sum(1 for d in decided if d.source == "rule"),
            "user_flips": len(flipped),
            "user_text_edits": len(edited),
            "decision_acceptance": round(1 - len(flipped) / len(decided), 3) if decided else None,
            "engines": analysis.engines,
        })
        word_cuts = 0
        lines_by_clip = analysis.lines_by_clip()
        for k in plan.keep:
            for line in lines_by_clip.get(k.clip_id, []):
                for w in line.words:
                    if w.start + 0.005 < k.start < w.end - 0.005 or w.start + 0.005 < k.end < w.end - 0.005:
                        word_cuts += 1
        out["word_cuts"] = word_cuts
    ai_nodes = set(plan.selection.ai_node_ids)
    if ai_nodes:
        final = set(plan.selection.node_ids)
        out["selection_retention"] = round(len(ai_nodes & final) / len(ai_nodes), 3)
    finals = [r for r in project.renders if r.quality == "final"]
    if finals:
        r = finals[0]
        out["render"] = {"duration": r.duration, "plan_duration": r.plan_duration, "error_ms": r.error_ms,
                         "elapsed_sec": r.elapsed_sec, "x_realtime": round(r.elapsed_sec / max(r.duration, 0.1), 2)}
    analyses = [j for j in jobs if j.kind == "analyze" and j.status == "done"]
    if analyses:
        j = analyses[0]
        out["analysis"] = {"elapsed_sec": j.metrics.get("elapsed_sec"), "stages": j.metrics.get("stages", {}),
                           "ai_usage": j.metrics.get("ai_usage", {}),
                           "sec_per_source_min": round(j.metrics.get("elapsed_sec", 0) / (source / 60), 1)
                           if source else None}
    return out


def to_markdown(name: str, m: dict) -> str:
    rows = [("원본 길이", f"{m['source_sec']}초"), ("결과 길이", f"{m['output_sec']}초"),
            ("압축률", m.get("compression"))]
    if "target_ratio" in m:
        rows.append(("분량 정확도 (결과/목표)", m["target_ratio"]))
    if "lines" in m:
        rows += [("문장 수 / 자른 문장", f"{m['lines']} / {m['lines_cut']}"),
                 ("자른 이유", ", ".join(f"{k} {v}" for k, v in m["cut_reasons"].items()) or "-"),
                 ("AI 판단 채택률", m.get("decision_acceptance")), ("단어 잘림", m.get("word_cuts")),
                 ("엔진", ", ".join(f"{k}={v}" for k, v in m.get("engines", {}).items()))]
    if "selection_retention" in m:
        rows.append(("AI 장면 선택 유지율", m["selection_retention"]))
    if "render" in m:
        rows += [("렌더 길이 오차", f"{m['render']['error_ms']}ms"), ("렌더 배속", m["render"]["x_realtime"])]
    if "analysis" in m:
        a = m["analysis"]
        rows += [("분석 시간", f"{a['elapsed_sec']}초 (원본 1분당 {a['sec_per_source_min']}초)"),
                 ("AI 요청 / 토큰", f"{a['ai_usage'].get('requests', 0)} / "
                                  f"{a['ai_usage'].get('prompt_tokens', 0) + a['ai_usage'].get('output_tokens', 0)}")]
    lines = [f"# {name} 평가 지표", "", "| 항목 | 값 |", "| --- | --- |"]
    lines += [f"| {k} | {'-' if v is None else v} |" for k, v in rows]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from ..edit.planner import compile_plan
    from ..server.storage import ProjectStore, read_json
    from ..settings import get_settings

    argv = argv if argv is not None else sys.argv[1:]
    settings = get_settings()
    store = ProjectStore(settings.data_dir)
    if not argv:
        for p in store.list():
            print(p.project_id, p.name, p.updated_at)
        return 0
    project = store.get(argv[0])
    analysis = store.load_analysis(project.project_id)
    plan = compile_plan(store.load_plan(project.project_id), project.timeline_clips(), analysis)
    # 서버가 켜져 있어도 건드리지 않게 작업 기록은 읽기만 한다 (JobManager를 만들면 '중단됨' 처리가 일어남)
    jobs = []
    for path in (settings.data_dir / "jobs").glob("*.json"):
        job = Job.model_validate(read_json(path))
        if job.project_id == project.project_id:
            jobs.append(job)
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    print(to_markdown(project.name, project_metrics(project, analysis, plan, jobs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
