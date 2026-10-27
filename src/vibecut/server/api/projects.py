"""설정·프로젝트·클립 API: /config, /projects, /projects/{pid}/clips"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ... import __version__
from ...ai.stt import whisper_available
from ...media.ffmpeg import FFmpegError, ffmpeg_path, ffmpeg_version, probe
from ...models import ClipInfo, Project
from ...render import fonts
from .. import pipeline
from ..storage import NotFound
from .common import VIDEO_EXT, app_state, media_response, project_or_404, project_view, recompile_and_save

router = APIRouter()


# ---------------------------------------------------------------- 설정·상태

@router.get("/config")
def get_config(request: Request) -> dict:
    settings = app_state(request).settings
    try:
        ff = {"path": ffmpeg_path(), "version": ".".join(map(str, ffmpeg_version())), "ok": True}
    except FFmpegError as error:
        ff = {"ok": False, "error": str(error)}
    return {"version": __version__, **settings.public_dict(), "ffmpeg": ff, "whisper": whisper_available(),
            "font_metrics": fonts.font_metrics_table(), "fonts": fonts.available_fonts(),
            "reference_short_side": 1080}


# ---------------------------------------------------------------- 프로젝트

class ProjectCreate(BaseModel):
    name: str = "새 프로젝트"


class ClipPatch(BaseModel):
    clip_id: str
    in_point: float | None = None
    out_point: float | None = None


class ProjectPatch(BaseModel):
    name: str | None = None
    timeline: list[str] | None = None
    clips: list[ClipPatch] | None = None


@router.post("/projects")
def create_project(request: Request, body: ProjectCreate) -> dict:
    return project_view(request, app_state(request).store.create(body.name))


@router.get("/projects")
def list_projects(request: Request) -> list[dict]:
    return [{"project_id": p.project_id, "name": p.name, "updated_at": p.updated_at, "clips": len(p.clips),
             "analysis": p.analysis.status} for p in app_state(request).store.list()]


@router.get("/projects/{project_id}")
def get_project(request: Request, project_id: str) -> dict:
    return project_view(request, project_or_404(request, project_id))


@router.patch("/projects/{project_id}")
def patch_project(request: Request, project_id: str, body: ProjectPatch) -> dict:
    store = app_state(request).store
    project = project_or_404(request, project_id)

    def change(p: Project):
        if body.name is not None:
            p.name = body.name.strip()[:80] or p.name
        if body.timeline is not None:
            ids = {c.clip_id for c in p.clips}
            unknown = [cid for cid in body.timeline if cid not in ids]
            if unknown or len(set(body.timeline)) != len(body.timeline):
                raise HTTPException(422, f"타임라인 클립 목록이 올바르지 않습니다: {unknown}")
            p.timeline = list(body.timeline)
        for patch in body.clips or []:
            clip = p.clip(patch.clip_id)
            if clip is None:
                raise HTTPException(404, f"클립을 찾을 수 없습니다: {patch.clip_id}")
            if patch.in_point is not None:
                clip.in_point = max(0.0, min(patch.in_point, clip.duration - 0.1))
            if patch.out_point is not None:
                clip.out_point = None if patch.out_point >= clip.duration - 0.01 else max(clip.in_point + 0.1,
                                                                                         patch.out_point)

    project = store.update(project.project_id, change)
    recompile_and_save(request, project, store.load_plan(project_id))
    return project_view(request, project)


@router.delete("/projects/{project_id}")
def delete_project(request: Request, project_id: str) -> dict:
    state = app_state(request)
    for job in state.jobs.list(project_id):
        state.jobs.cancel(job.job_id)
    try:
        state.store.delete(project_id)
    except NotFound as error:
        raise HTTPException(404, str(error)) from error
    return {"ok": True}


# ---------------------------------------------------------------- 클립

@router.post("/projects/{project_id}/clips")
async def upload_clips(request: Request, project_id: str, files: list[UploadFile] = File(...)) -> dict:
    state = app_state(request)
    store, settings = state.store, state.settings
    project_or_404(request, project_id)
    limit = settings.max_upload_mb * 1024 * 1024
    added: list[ClipInfo] = []
    for upload in files:
        suffix = Path(upload.filename or "video.mp4").suffix.lower()
        if suffix not in VIDEO_EXT:
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
        clip = pipeline.add_clip(store, project_id, tmp, upload.filename or tmp.name, size, digest.hexdigest(), info)
        added.append(clip)
        state.jobs.submit("proxy", project_id, pipeline.run_proxy, store, project_id, clip.clip_id)
    project = store.get(project_id)
    return {"clips": [c.model_dump() for c in added], "project": project_view(request, project)}


@router.delete("/projects/{project_id}/clips/{clip_id}")
def delete_clip(request: Request, project_id: str, clip_id: str) -> dict:
    store = app_state(request).store
    project = project_or_404(request, project_id)
    clip = project.clip(clip_id)
    if clip is None:
        raise HTTPException(404, "클립을 찾을 수 없습니다.")
    analysis_job = app_state(request).jobs.active(project_id, "analyze")
    if analysis_job is not None and clip_id in project.timeline:
        raise HTTPException(409, "분석 중에는 타임라인의 클립을 삭제할 수 없습니다.")

    def change(p: Project):
        p.clips = [c for c in p.clips if c.clip_id != clip_id]
        p.timeline = [cid for cid in p.timeline if cid != clip_id]

    project = store.update(project_id, change)
    store.clip_path(project_id, clip.stored_name).unlink(missing_ok=True)
    store.proxy_path(project_id, clip_id).unlink(missing_ok=True)
    recompile_and_save(request, project, store.load_plan(project_id))
    return project_view(request, project)


@router.get("/projects/{project_id}/clips/{clip_id}/file")
def clip_file(request: Request, project_id: str, clip_id: str) -> FileResponse:
    project = project_or_404(request, project_id)
    clip = project.clip(clip_id)
    if clip is None:
        raise HTTPException(404, "클립을 찾을 수 없습니다.")
    return media_response(app_state(request).store.clip_path(project_id, clip.stored_name))


@router.get("/projects/{project_id}/clips/{clip_id}/proxy")
def clip_proxy(request: Request, project_id: str, clip_id: str) -> FileResponse:
    project_or_404(request, project_id)
    return media_response(app_state(request).store.proxy_path(project_id, clip_id))
