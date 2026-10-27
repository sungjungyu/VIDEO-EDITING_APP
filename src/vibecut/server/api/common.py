"""라우터들이 함께 쓰는 도우미: 앱 상태, 404 처리, 응답 모양(project_view·plan_view), 계획 재계산, 파일 응답."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from ...edit.planner import compile_plan, validate_plan
from ...models import EditPlan, Project
from ..storage import NotFound

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"}


def app_state(request: Request):
    return request.app.state


def project_or_404(request: Request, project_id: str) -> Project:
    try:
        return app_state(request).store.get(project_id)
    except NotFound as error:
        raise HTTPException(404, str(error)) from error


def project_view(request: Request, project: Project) -> dict:
    jobs = app_state(request).jobs
    data = project.model_dump()
    base = f"/api/projects/{project.project_id}"
    for clip in data["clips"]:
        clip["file_url"] = f"{base}/clips/{clip['clip_id']}/file"
        clip["proxy_url"] = f"{base}/clips/{clip['clip_id']}/proxy" if clip["proxy"] else None
    for render in data["renders"]:
        render["url"] = f"{base}/renders/{render['file']}"
    data["analysis_stale"] = project.analysis_stale
    data["active_jobs"] = [j.model_dump() for j in jobs.list(project.project_id) if not j.finished]
    return data


def plan_view(request: Request, project: Project, plan: EditPlan) -> dict:
    store = app_state(request).store
    analysis = store.load_analysis(project.project_id)
    issues = validate_plan(plan, project.timeline_clips(), analysis, store.clip_files(project))
    return {"plan": plan.model_dump(), "issues": issues}


def recompile_and_save(request: Request, project: Project, plan: EditPlan) -> EditPlan:
    store = app_state(request).store
    compiled = compile_plan(plan, project.timeline_clips(), store.load_analysis(project.project_id))
    store.save_plan(project.project_id, compiled)
    return compiled


def media_response(path: Path, download_name: str | None = None) -> FileResponse:
    if not path.exists():
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() == ".mov":
        media_type = "video/quicktime"
    return FileResponse(path, media_type=media_type, filename=download_name,
                        content_disposition_type="attachment" if download_name else "inline")
