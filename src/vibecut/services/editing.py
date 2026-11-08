"""편집 계획 고치기: 계산 결과 읽기, 사용자 값 바꾸기, 문장별 남김/자름·자막 수정, 장면 선택(AI 가편집), 수정 요청.

편집 계획은 언제나 '사용자 값 → compile_plan → 저장' 순서로 바뀐다 (계산 결과를 손으로 고치지 않는다).
저장된 계획을 바꾸는 곳은 모두 edit_plan을 거친다: 프로젝트 잠금 안에서 읽고·바꾸고·계산하고·저장한다.
AI처럼 오래 걸리는 일은 잠금 밖에서 끝내고 결과만 edit_plan으로 넣는다 (그 사이 사용자가 고친 내용이 사라지지 않게).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from ..ai.client import GeminiClient
from ..domain.models import EditPlan, LineDecision, OutputSpec, PlanOptions, Project, Selection, StyleSpec
from ..editing.planner import compile_plan, effective_decisions
from ..editing.revise import revise as revise_lines
from ..editing.select import select_beats
from ..errors import BadRequest, Conflict
from ..storage.projects import ProjectStore
from .analysis import apply_profile


class LineChange(BaseModel):
    """문장 하나의 사용자 결정 (API 요청 본문의 일부이기도 하다)."""
    seg_id: str
    keep: bool | None = None
    text: str | None = None
    reset: bool = False


def current_plan(store: ProjectStore, project_id: str) -> tuple[Project, EditPlan]:
    """저장된 사용자 값으로 다시 계산한 편집 계획 (클립·분석이 바뀌었어도 지금 상태에 맞는다)."""
    project = store.get(project_id)
    plan = compile_plan(store.load_plan(project_id), project.timeline_clips(), store.load_analysis(project_id))
    return project, plan


def recompile_and_save(store: ProjectStore, project: Project, plan: EditPlan) -> EditPlan:
    compiled = compile_plan(plan, project.timeline_clips(), store.load_analysis(project.project_id))
    store.save_plan(project.project_id, compiled)
    return compiled


def edit_plan(store: ProjectStore, project_id: str,
              change: Callable[[EditPlan], None] | None = None) -> tuple[Project, EditPlan]:
    """저장된 계획을 잠금 안에서 읽어 change로 바꾸고 다시 계산해 저장한다 (change가 없으면 다시 계산만)."""
    with store.lock(project_id):
        project = store.get(project_id)
        plan = store.load_plan(project_id)
        if change is not None:
            change(plan)
        return project, recompile_and_save(store, project, plan)


def update_plan(store: ProjectStore, project_id: str, selection: Selection | None = None,
                lines: dict[str, LineDecision] | None = None, styles: dict[str, StyleSpec] | None = None,
                output: OutputSpec | None = None, options: PlanOptions | None = None) -> tuple[Project, EditPlan]:
    """주어진 사용자 값만 바꾼다 (실행취소·다시실행도 이 함수로 이전 값을 통째로 되돌린다)."""
    def change(plan: EditPlan):
        for name, value in (("selection", selection), ("lines", lines), ("styles", styles), ("output", output),
                            ("options", options)):
            if value is not None:
                setattr(plan, name, value)
        if "subtitle" not in plan.styles:
            plan.styles["subtitle"] = StyleSpec()

    return edit_plan(store, project_id, change)


def apply_line_changes(plan: EditPlan, base: dict[str, LineDecision], changes: list[LineChange]) -> None:
    for ch in changes:
        if ch.reset:
            plan.lines.pop(ch.seg_id, None)
            continue
        current = plan.lines.get(ch.seg_id) or base.get(ch.seg_id) or LineDecision(seg_id=ch.seg_id)
        update: dict = {"source": "user"}
        if ch.keep is not None:
            update["keep"] = ch.keep
        if ch.text is not None:
            update["text"] = ch.text.strip() or None
        plan.lines[ch.seg_id] = current.model_copy(update=update)


def patch_lines(store: ProjectStore, project_id: str, changes: list[LineChange]) -> tuple[Project, EditPlan]:
    store.get(project_id)
    analysis = store.load_analysis(project_id)
    if analysis is None:
        raise Conflict("먼저 분석하세요.")
    known = {line.seg_id for line in analysis.lines}
    return edit_plan(store, project_id, lambda plan: apply_line_changes(
        plan, analysis.judgments, [c for c in changes if c.seg_id in known]))


def select(store: ProjectStore, client: GeminiClient | None, project_id: str,
           mode: Literal["all", "manual", "auto"], target_sec: float | None = None, user_prompt: str = "",
           locked_ids: list[str] | None = None, beat_ids: list[str] | None = None, profile: dict | None = None
           ) -> tuple[Project, EditPlan, str, list[str]]:
    """장면 선택: all(전체) / manual(사용자가 체크한 장면) / auto(AI 가편집). (프로젝트, 계획, 엔진, 경고)"""
    locked_ids, beat_ids, profile = locked_ids or [], beat_ids or [], profile or {}
    project = store.get(project_id)
    analysis = store.load_analysis(project_id)
    if mode != "all" and analysis is None:
        raise Conflict("장면을 고르려면 먼저 분석하세요.")
    engine, warnings, chosen = "user", [], None
    if mode == "auto":
        if not target_sec or target_sec <= 0:
            raise BadRequest("목표 분량(초)을 입력하세요.")
        # AI 점수는 오래 걸리므로 잠금 밖에서 지금 계획의 사본으로 계산하고, 고른 결과만 아래에서 넣는다
        snapshot = store.load_plan(project_id)
        snapshot.options = apply_profile(snapshot.options, profile)
        decisions = effective_decisions(snapshot, analysis)
        clips = {c.clip_id: c for c in project.timeline_clips()}
        chosen, engine, warnings = select_beats(analysis, clips, snapshot, decisions, target_sec, user_prompt,
                                                 locked_ids, profile, client)

    def change(plan: EditPlan):
        if mode == "all":
            plan.selection = Selection(mode="all")
        elif mode == "manual":
            known = {b.beat_id for b in analysis.beats}
            plan.selection = plan.selection.model_copy(update={
                "mode": "manual", "beat_ids": [i for i in beat_ids if i in known],
                "locked_ids": [i for i in locked_ids if i in known], "target_sec": target_sec,
                "user_prompt": user_prompt})
        else:
            plan.options = apply_profile(plan.options, profile)
            plan.selection = chosen

    project, plan = edit_plan(store, project_id, change)
    return project, plan, engine, warnings


def revise(store: ProjectStore, client: GeminiClient | None, project_id: str, instruction: str,
           profile: dict | None = None) -> tuple[Project, EditPlan, str, int, str]:
    """자연어 수정 요청 → 문장 판단·자막 변경. (프로젝트, 계획, 안내 메시지, 바뀐 문장 수, 엔진)"""
    project = store.get(project_id)
    analysis = store.load_analysis(project_id)
    if analysis is None:
        raise Conflict("먼저 분석하세요.")
    decisions = effective_decisions(store.load_plan(project_id), analysis)
    changes, message, engine = revise_lines(instruction, analysis.lines, decisions, profile or {}, client)
    line_changes = [LineChange(seg_id=sid, keep=c.get("keep"), text=c.get("text")) for sid, c in changes.items()]
    project, compiled = edit_plan(store, project_id,
                                  lambda plan: apply_line_changes(plan, analysis.judgments, line_changes))
    return project, compiled, message, len(changes), engine
