"""API 응답 모양: 프로젝트(파일 주소·진행 중 작업 포함), 편집 계획(+ 렌더 전 검사), 파일 응답."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from ..domain.models import EditPlan, Project
from ..editing.planner import validate_plan
from .deps import AppState


def project_view(app: AppState, project: Project) -> dict:
    data = project.model_dump()
    base = f"/api/projects/{project.project_id}"
    for clip in data["clips"]:
        clip["file_url"] = f"{base}/clips/{clip['clip_id']}/file"
        clip["proxy_url"] = f"{base}/clips/{clip['clip_id']}/proxy" if clip["proxy"] else None
    for render in data["renders"]:
        render["url"] = f"{base}/renders/{render['file']}"
    data["analysis_stale"] = project.analysis_stale
    data["active_jobs"] = [j.model_dump() for j in app.jobs.list(project.project_id) if not j.finished]
    return data


def plan_view(app: AppState, project: Project, plan: EditPlan) -> dict:
    analysis = app.store.load_analysis(project.project_id)
    issues = validate_plan(plan, project.timeline_clips(), analysis, app.store.clip_files(project))
    return {"plan": plan.model_dump(), "issues": issues}


def media_response(path: Path, download_name: str | None = None) -> FileResponse:
    if not path.exists():
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() == ".mov":
        media_type = "video/quicktime"
    return FileResponse(path, media_type=media_type, filename=download_name,
                        content_disposition_type="attachment" if download_name else "inline")
