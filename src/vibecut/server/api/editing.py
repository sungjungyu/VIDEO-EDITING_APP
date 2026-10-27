"""분석·편집 API: /analyze, /analysis, /plan, /plan/lines, /select (AI 가편집), /revise (채팅 수정)"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ...ai.gemini import GeminiClient
from ...ai.revise import revise as revise_lines
from ...ai.select import select_scenes
from ...edit.planner import compile_plan, effective_decisions, flatten
from ...models import EditPlan, LineDecision, OutputSpec, PlanOptions, Selection, StyleSpec
from .. import pipeline
from .common import app_state, plan_view, project_or_404, recompile_and_save

router = APIRouter()


# ---------------------------------------------------------------- 분석

class AnalyzeRequest(BaseModel):
    profile: dict = Field(default_factory=dict)


@router.post("/projects/{project_id}/analyze")
def analyze(request: Request, project_id: str, body: AnalyzeRequest) -> dict:
    state = app_state(request)
    project = project_or_404(request, project_id)
    if not project.timeline:
        raise HTTPException(422, "타임라인에 클립이 없습니다. 클립을 타임라인에 올린 뒤 분석하세요.")
    running = state.jobs.active(project_id, "analyze")
    if running is not None:
        return running.model_dump()
    job = state.jobs.submit("analyze", project_id, pipeline.run_analysis, state.store, state.settings, project_id,
                            body.profile)
    return job.model_dump()


@router.get("/projects/{project_id}/analysis")
def get_analysis(request: Request, project_id: str) -> dict:
    project_or_404(request, project_id)
    analysis = app_state(request).store.load_analysis(project_id)
    if analysis is None:
        raise HTTPException(404, "아직 분석하지 않았습니다.")
    return analysis.model_dump()


# ---------------------------------------------------------------- 편집 계획

class PlanUpdate(BaseModel):
    selection: Selection | None = None
    lines: dict[str, LineDecision] | None = None
    styles: dict[str, StyleSpec] | None = None
    output: OutputSpec | None = None
    options: PlanOptions | None = None


class LineChange(BaseModel):
    seg_id: str
    keep: bool | None = None
    text: str | None = None
    reset: bool = False


class LinesPatch(BaseModel):
    changes: list[LineChange]


@router.get("/projects/{project_id}/plan")
def get_plan(request: Request, project_id: str) -> dict:
    project = project_or_404(request, project_id)
    plan = compile_plan(app_state(request).store.load_plan(project_id), project.timeline_clips(),
                        app_state(request).store.load_analysis(project_id))
    return plan_view(request, project, plan)


@router.put("/projects/{project_id}/plan")
def put_plan(request: Request, project_id: str, body: PlanUpdate) -> dict:
    project = project_or_404(request, project_id)
    store = app_state(request).store
    with store.lock(project_id):
        plan = store.load_plan(project_id)
        for field_name in ("selection", "lines", "styles", "output", "options"):
            value = getattr(body, field_name)
            if value is not None:
                setattr(plan, field_name, value)
        if "subtitle" not in plan.styles:
            plan.styles["subtitle"] = StyleSpec()
        compiled = recompile_and_save(request, project, plan)
    return plan_view(request, project, compiled)


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


@router.patch("/projects/{project_id}/plan/lines")
def patch_lines(request: Request, project_id: str, body: LinesPatch) -> dict:
    project = project_or_404(request, project_id)
    store = app_state(request).store
    analysis = store.load_analysis(project_id)
    if analysis is None:
        raise HTTPException(409, "먼저 분석하세요.")
    known = {line.seg_id for line in analysis.lines}
    with store.lock(project_id):
        plan = store.load_plan(project_id)
        apply_line_changes(plan, analysis.judgments, [c for c in body.changes if c.seg_id in known])
        compiled = recompile_and_save(request, project, plan)
    return plan_view(request, project, compiled)


class SelectRequest(BaseModel):
    mode: Literal["all", "manual", "auto"] = "auto"
    target_sec: float | None = None
    user_prompt: str = ""
    locked_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    profile: dict = Field(default_factory=dict)


@router.post("/projects/{project_id}/select")
async def select(request: Request, project_id: str, body: SelectRequest) -> dict:
    state = app_state(request)
    project = project_or_404(request, project_id)
    analysis = state.store.load_analysis(project_id)
    if body.mode != "all" and analysis is None:
        raise HTTPException(409, "장면을 고르려면 먼저 분석하세요.")
    plan = state.store.load_plan(project_id)
    engine, warnings = "user", []
    if body.mode == "all":
        plan.selection = Selection(mode="all")
    elif body.mode == "manual":
        known = flatten(analysis.tree)
        plan.selection = plan.selection.model_copy(update={
            "mode": "manual", "node_ids": [i for i in body.node_ids if i in known],
            "locked_ids": [i for i in body.locked_ids if i in known], "target_sec": body.target_sec,
            "user_prompt": body.user_prompt})
    else:
        if not body.target_sec or body.target_sec <= 0:
            raise HTTPException(422, "목표 분량(초)을 입력하세요.")
        client = GeminiClient(state.settings, state.store.cache_dir / "ai")
        decisions = effective_decisions(plan, analysis)
        clips = {c.clip_id: c for c in project.timeline_clips()}
        plan.options = pipeline.apply_profile(plan.options, body.profile)
        selection, engine, warnings = await run_in_threadpool(
            select_scenes, analysis, clips, plan, decisions, body.target_sec, body.user_prompt, body.locked_ids,
            body.profile, client)
        plan.selection = selection
    compiled = recompile_and_save(request, project, plan)
    view = plan_view(request, project, compiled)
    view.update({"engine": engine, "warnings": warnings})
    return view


class ReviseRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    profile: dict = Field(default_factory=dict)


@router.post("/projects/{project_id}/revise")
async def revise(request: Request, project_id: str, body: ReviseRequest) -> dict:
    state = app_state(request)
    project = project_or_404(request, project_id)
    analysis = state.store.load_analysis(project_id)
    if analysis is None:
        raise HTTPException(409, "먼저 분석하세요.")
    plan = state.store.load_plan(project_id)
    decisions = effective_decisions(plan, analysis)
    client = GeminiClient(state.settings, state.store.cache_dir / "ai")
    changes, message, engine = await run_in_threadpool(revise_lines, body.instruction, analysis.lines, decisions,
                                                       body.profile, client)
    with state.store.lock(project_id):
        plan = state.store.load_plan(project_id)
        line_changes = [LineChange(seg_id=sid, keep=c.get("keep"), text=c.get("text")) for sid, c in changes.items()]
        apply_line_changes(plan, analysis.judgments, line_changes)
        compiled = recompile_and_save(request, project, plan)
    view = plan_view(request, project, compiled)
    view.update({"message": message, "changed": len(changes), "engine": engine})
    return view
