"""렌더 전 규칙 검사 (계획서 3-2). error가 있으면 렌더하지 않는다."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Analysis, ClipInfo, EditPlan
from .planner import effective_decisions

CUE_PATTERN = re.compile(r"(다시\s*(할게|갈게|찍|해)|처음부터|컷\s*컷|편집\s*해|자를게|잘라\s*줘|엔지|NG|잠깐만)")


def validate_plan(plan: EditPlan, clips: list[ClipInfo], analysis: Analysis | None,
                  clip_files: dict[str, Path] | None = None) -> list[dict]:
    issues: list[dict] = []

    def add(level: str, message: str):
        issues.append({"level": level, "message": message})

    by_id = {c.clip_id: c for c in clips}
    if not plan.keep:
        add("error", "남길 구간이 없습니다.")
    for k in plan.keep:
        clip = by_id.get(k.clip_id)
        if clip is None:
            add("error", f"타임라인에 없는 클립을 쓰고 있습니다: {k.clip_id}")
            continue
        if k.start < -0.001 or k.end > clip.duration + 0.05 or k.end <= k.start:
            add("error", f"{clip.filename}: 구간 {k.start:.2f}~{k.end:.2f}초가 영상 범위를 벗어났습니다.")
        if clip_files is not None and not clip_files.get(k.clip_id, Path("?")).exists():
            add("error", f"{clip.filename}: 원본 파일이 없습니다.")
    for a, b in zip(plan.keep, plan.keep[1:]):
        if a.clip_id == b.clip_id and b.start < a.end - 0.001:
            add("error", f"{a.clip_id}: 남길 구간이 겹칩니다 ({a.start:.2f}~{a.end:.2f}, {b.start:.2f}~{b.end:.2f}).")

    if analysis is not None:
        decisions = effective_decisions(plan, analysis)
        lines_by_clip = analysis.lines_by_clip()
        cut_words = 0
        for k in plan.keep:
            for line in lines_by_clip.get(k.clip_id, []):
                for w in line.words:
                    if w.start + 0.005 < k.start < w.end - 0.005 or w.start + 0.005 < k.end < w.end - 0.005:
                        cut_words += 1
        if cut_words:
            add("warning", f"단어 중간에서 잘리는 곳이 {cut_words}곳 있습니다.")
        def kept(line) -> bool:
            d = decisions.get(line.seg_id)
            in_output = any(k.clip_id == line.clip_id and k.start < line.end and line.start < k.end for k in plan.keep)
            return (d is None or d.keep) and in_output

        kept_cues = [line for line in analysis.lines if CUE_PATTERN.search(line.text) and kept(line)]
        for line in kept_cues[:5]:
            add("warning", f"촬영 지시어로 보이는 문장이 남아 있습니다: \"{line.text[:30]}\"")
    short = [k for k in plan.keep if k.end - k.start < 0.3]
    if short:
        add("warning", f"0.3초보다 짧은 조각이 {len(short)}개 있습니다 (화면이 튀어 보일 수 있음).")
    target = plan.selection.target_sec
    if target and plan.duration:
        ratio = plan.duration / target
        if not 0.95 <= ratio <= 1.05:
            add("warning", f"결과 길이 {plan.duration:.1f}초 / 목표 {target:.0f}초 (비율 {ratio:.2f}).")
    return issues
