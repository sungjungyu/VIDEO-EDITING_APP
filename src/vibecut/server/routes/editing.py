"""분석·편집 계획 API: 분석 작업, 분석 결과, 편집 계획 읽기·고치기, 장면 선택(AI 가편집), 수정 요청."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from ...errors import BadRequest, NotFound
from ...services import editing as editing_service
from ...services.analysis import run_analysis
from ..deps import state
from ..schemas import AnalyzeRequest, LinesPatch, PlanUpdate, ReviseRequest, SelectRequest
from ..views import plan_view

router = APIRouter()


# ---------------------------------------------------------------- 분석

@router.post("/projects/{project_id}/analyze")
def analyze(request: Request, project_id: str, body: AnalyzeRequest) -> dict:
    app = state(request)
    if not app.store.get(project_id).timeline:
        raise BadRequest("타임라인에 클립이 없습니다. 클립을 타임라인에 올린 뒤 분석하세요.")
    with app.store.lock(project_id):
        running = app.jobs.active(project_id, "analyze")
        if running is not None:
            return running.model_dump()
        job = app.jobs.submit("analyze", project_id, run_analysis, app.store, app.settings, project_id, body.profile,
                              app.ai)
        return job.model_dump()


@router.get("/projects/{project_id}/analysis")
def get_analysis(request: Request, project_id: str) -> dict:
    store = state(request).store
    store.get(project_id)
    analysis = store.load_analysis(project_id)
    if analysis is None:
        raise NotFound("아직 분석하지 않았습니다.")
    return analysis.model_dump()


# ---------------------------------------------------------------- 편집 계획

@router.get("/projects/{project_id}/plan")
def get_plan(request: Request, project_id: str) -> dict:
    app = state(request)
    return plan_view(app, *editing_service.current_plan(app.store, project_id))


@router.put("/projects/{project_id}/plan")
def put_plan(request: Request, project_id: str, body: PlanUpdate) -> dict:
    app = state(request)
    project, plan = editing_service.update_plan(app.store, project_id, body.selection, body.lines, body.styles,
                                                body.output, body.options)
    return plan_view(app, project, plan)


@router.patch("/projects/{project_id}/plan/lines")
def patch_lines(request: Request, project_id: str, body: LinesPatch) -> dict:
    app = state(request)
    return plan_view(app, *editing_service.patch_lines(app.store, project_id, body.changes))


@router.post("/projects/{project_id}/select")
async def select(request: Request, project_id: str, body: SelectRequest) -> dict:
    app = state(request)
    project, plan, engine, warnings = await run_in_threadpool(
        editing_service.select, app.store, app.ai, project_id, body.mode, body.target_sec, body.user_prompt,
        body.locked_ids, body.node_ids, body.profile)
    view = plan_view(app, project, plan)
    view.update({"engine": engine, "warnings": warnings})
    return view


@router.post("/projects/{project_id}/revise")
async def revise(request: Request, project_id: str, body: ReviseRequest) -> dict:
    app = state(request)
    project, plan, message, changed, engine = await run_in_threadpool(
        editing_service.revise, app.store, app.ai, project_id, body.instruction, body.profile)
    view = plan_view(app, project, plan)
    view.update({"message": message, "changed": changed, "engine": engine})
    return view
