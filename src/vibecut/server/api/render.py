"""렌더·작업·평가 API: /render, /renders/{file}, /jobs, /metrics"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...edit.planner import compile_plan, validate_plan
from ...eval.metrics import project_metrics
from .. import pipeline
from .common import app_state, media_response, project_or_404

router = APIRouter()


# ---------------------------------------------------------------- 렌더

class RenderRequest(BaseModel):
    quality: Literal["preview", "final"] = "final"


@router.post("/projects/{project_id}/render")
def render(request: Request, project_id: str, body: RenderRequest) -> dict:
    state = app_state(request)
    project = project_or_404(request, project_id)
    plan = compile_plan(state.store.load_plan(project_id), project.timeline_clips(),
                        state.store.load_analysis(project_id))
    errors = [i for i in validate_plan(plan, project.timeline_clips(), state.store.load_analysis(project_id),
                                       state.store.clip_files(project)) if i["level"] == "error"]
    if errors:
        raise HTTPException(422, " / ".join(e["message"] for e in errors[:3]))
    job = state.jobs.submit("render", project_id, pipeline.run_render, state.store, project_id, body.quality)
    return job.model_dump()


@router.get("/projects/{project_id}/renders/{file_name}")
def get_render(request: Request, project_id: str, file_name: str) -> FileResponse:
    project = project_or_404(request, project_id)
    render_info = next((r for r in project.renders if r.file == Path(file_name).name), None)
    if render_info is None:
        raise HTTPException(404, "결과 영상을 찾을 수 없습니다.")
    label = "미리보기" if render_info.quality == "preview" else "최종"
    safe_name = "".join(ch for ch in project.name if ch not in '\\/:*?"<>|').strip() or "vibecut"
    return media_response(app_state(request).store.render_path(project_id, render_info.file),
                           f"{safe_name}_{label}_{render_info.render_id}.mp4")


# ---------------------------------------------------------------- 작업

@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict:
    job = app_state(request).jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job.model_dump()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict:
    job = app_state(request).jobs.cancel(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job.model_dump()


@router.get("/projects/{project_id}/jobs")
def project_jobs(request: Request, project_id: str) -> list[dict]:
    project_or_404(request, project_id)
    return [j.model_dump() for j in app_state(request).jobs.list(project_id)[:30]]


# ---------------------------------------------------------------- 평가 지표

@router.get("/projects/{project_id}/metrics")
def metrics(request: Request, project_id: str) -> dict:
    state = app_state(request)
    project = project_or_404(request, project_id)
    analysis = state.store.load_analysis(project_id)
    plan = compile_plan(state.store.load_plan(project_id), project.timeline_clips(), analysis)
    return project_metrics(project, analysis, plan, state.jobs.list(project_id))
