"""렌더·작업·평가 지표 API."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from ...editing.planner import validate_plan
from ...errors import BadRequest, NotFound
from ...eval.metrics import project_metrics
from ...services import editing as editing_service
from ...services.rendering import run_render
from ..deps import state
from ..schemas import RenderRequest
from ..views import media_response

router = APIRouter()
UNSAFE_FILENAME_CHARS = set('\\/:*?"<>|')


@router.post("/projects/{project_id}/render")
def render(request: Request, project_id: str, body: RenderRequest) -> dict:
    app = state(request)
    project, plan = editing_service.current_plan(app.store, project_id)
    errors = [i for i in validate_plan(plan, project.timeline_clips(), app.store.load_analysis(project_id),
                                       app.store.clip_files(project)) if i["level"] == "error"]
    if errors:
        raise BadRequest(" / ".join(e["message"] for e in errors[:3]))
    with app.store.lock(project_id):          # 두 번 눌러도 렌더는 하나만 (도는 중이면 그 작업을 돌려준다)
        running = app.jobs.active(project_id, "render")
        if running is not None:
            return running.model_dump()
        return app.jobs.submit("render", project_id, run_render, app.store, project_id, body.quality,
                               app.settings).model_dump()


@router.get("/projects/{project_id}/renders/{file_name}")
def get_render(request: Request, project_id: str, file_name: str) -> FileResponse:
    store = state(request).store
    project = store.get(project_id)
    render_info = next((r for r in project.renders if r.file == Path(file_name).name), None)
    if render_info is None:
        raise NotFound("결과 영상을 찾을 수 없습니다.")
    label = "미리보기" if render_info.quality == "preview" else "최종"
    safe_name = "".join(ch for ch in project.name if ch not in UNSAFE_FILENAME_CHARS).strip() or "vibecut"
    return media_response(store.render_path(project_id, render_info.file),
                          f"{safe_name}_{label}_{render_info.render_id}.mp4")


# ---------------------------------------------------------------- 작업

@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict:
    job = state(request).jobs.get(job_id)
    if job is None:
        raise NotFound("작업을 찾을 수 없습니다.")
    return job.model_dump()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict:
    job = state(request).jobs.cancel(job_id)
    if job is None:
        raise NotFound("작업을 찾을 수 없습니다.")
    return job.model_dump()


@router.get("/projects/{project_id}/jobs")
def project_jobs(request: Request, project_id: str) -> list[dict]:
    app = state(request)
    app.store.get(project_id)
    return [j.model_dump() for j in app.jobs.list(project_id)[:30]]


# ---------------------------------------------------------------- 평가 지표

@router.get("/projects/{project_id}/metrics")
def metrics(request: Request, project_id: str) -> dict:
    app = state(request)
    project, plan = editing_service.current_plan(app.store, project_id)
    return project_metrics(project, app.store.load_analysis(project_id), plan, app.jobs.list(project_id))
