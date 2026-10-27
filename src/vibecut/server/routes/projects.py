"""프로젝트·클립 API."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from ...domain.models import ClipInfo
from ...errors import FFmpegError, NotFound
from ...media.probe import VIDEO_EXTENSIONS, probe
from ...services import media as media_service
from ...services import projects as project_service
from ...services.rendering import run_proxy
from ..deps import state
from ..schemas import ProjectCreate, ProjectPatch
from ..views import media_response, project_view

router = APIRouter()


@router.post("/projects")
def create_project(request: Request, body: ProjectCreate) -> dict:
    app = state(request)
    return project_view(app, app.store.create(body.name))


@router.get("/projects")
def list_projects(request: Request) -> list[dict]:
    return [{"project_id": p.project_id, "name": p.name, "updated_at": p.updated_at, "clips": len(p.clips),
             "analysis": p.analysis.status} for p in state(request).store.list()]


@router.get("/projects/{project_id}")
def get_project(request: Request, project_id: str) -> dict:
    app = state(request)
    return project_view(app, app.store.get(project_id))


@router.patch("/projects/{project_id}")
def patch_project(request: Request, project_id: str, body: ProjectPatch) -> dict:
    app = state(request)
    ranges = [(c.clip_id, c.in_point, c.out_point) for c in body.clips or []]
    return project_view(app, project_service.update_project(app.store, project_id, body.name, body.timeline, ranges))


@router.delete("/projects/{project_id}")
def delete_project(request: Request, project_id: str) -> dict:
    app = state(request)
    project_service.delete_project(app.store, app.jobs, project_id)
    return {"ok": True}


# ---------------------------------------------------------------- 클립

@router.post("/projects/{project_id}/clips")
async def upload_clips(request: Request, project_id: str, files: list[UploadFile] = File(...)) -> dict:
    """영상을 1MB씩 받아 저장하고(용량 제한·형식 검사) 클립으로 등록한 뒤 미리보기 사본 작업을 건다."""
    app = state(request)
    store, settings = app.store, app.settings
    store.get(project_id)
    limit = settings.max_upload_mb * 1024 * 1024
    added: list[ClipInfo] = []
    for upload in files:
        suffix = Path(upload.filename or "video.mp4").suffix.lower()
        if suffix not in VIDEO_EXTENSIONS:
            raise HTTPException(400, f"{upload.filename}: MP4·MOV·M4V·AVI·MKV·WEBM·3GP 영상만 올릴 수 있습니다.")
        tmp = store.project_dir(project_id) / "clips" / f".upload_{uuid.uuid4().hex[:8]}{suffix}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha1(), 0
        try:
            with open(tmp, "wb") as out:
                while chunk := await upload.read(1 << 20):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"{upload.filename}: 파일이 {settings.max_upload_mb}MB를 넘습니다.")
                    digest.update(chunk)
                    out.write(chunk)
            try:
                info = await run_in_threadpool(probe, tmp)
            except FFmpegError as error:
                raise HTTPException(400, f"{upload.filename}: 영상 정보를 읽지 못했습니다. ({error})") from error
            if not info.has_video:
                raise HTTPException(400, f"{upload.filename}: 영상 트랙이 없습니다.")
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        clip = project_service.import_clip(store, project_id, tmp, upload.filename or tmp.name, size,
                                           digest.hexdigest(), info)
        added.append(clip)
        app.jobs.submit("proxy", project_id, run_proxy, store, project_id, clip.clip_id)
    return {"clips": [c.model_dump() for c in added], "project": project_view(app, store.get(project_id))}


@router.delete("/projects/{project_id}/clips/{clip_id}")
def delete_clip(request: Request, project_id: str, clip_id: str) -> dict:
    app = state(request)
    return project_view(app, project_service.delete_clip(app.store, app.jobs, project_id, clip_id))


@router.get("/projects/{project_id}/clips/{clip_id}/file")
def clip_file(request: Request, project_id: str, clip_id: str) -> FileResponse:
    store = state(request).store
    clip = store.get(project_id).clip(clip_id)
    if clip is None:
        raise NotFound("클립을 찾을 수 없습니다.")
    return media_response(store.clip_path(project_id, clip.stored_name))


@router.get("/projects/{project_id}/clips/{clip_id}/proxy")
def clip_proxy(request: Request, project_id: str, clip_id: str) -> FileResponse:
    store = state(request).store
    store.get(project_id)
    return media_response(store.proxy_path(project_id, clip_id))


@router.get("/projects/{project_id}/clips/{clip_id}/waveform")
async def clip_waveform(request: Request, project_id: str, clip_id: str) -> dict:
    """오디오 트랙 파형 (처음 한 번은 오디오를 뽑아 계산하므로 스레드에서 돌린다)."""
    store = state(request).store
    return await run_in_threadpool(media_service.clip_waveform, store, project_id, clip_id)
