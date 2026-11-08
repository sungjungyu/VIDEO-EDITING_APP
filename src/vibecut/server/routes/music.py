"""배경음악 API: 고를 수 있는 곡, 기본 곡·내 음악 파일(미리 듣기·미리보기용), 내 음악 올리기."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from ...errors import FFmpegError, NotFound
from ...media.probe import probe
from ...services import music as music_service
from ...storage.music import MUSIC_EXTENSIONS, MusicLibrary
from ..deps import state
from ..views import media_response, plan_view

router = APIRouter()
MAX_MUSIC_MB = 50


def _library(request: Request) -> MusicLibrary:
    return MusicLibrary(state(request).settings.music_dir)


@router.get("/projects/{project_id}/music")
def music_choices(request: Request, project_id: str) -> dict:
    return music_service.music_choices(state(request).store, _library(request), project_id)


@router.get("/music/{track_id}/file")
def library_file(request: Request, track_id: str) -> FileResponse:
    return media_response(_library(request).path(track_id))


@router.get("/projects/{project_id}/music/file")
def project_music_file(request: Request, project_id: str) -> FileResponse:
    app = state(request)
    plan = app.store.load_plan(project_id)
    path = music_service.music_file(app.store, _library(request), project_id, plan.music)
    if path is None:
        raise NotFound("배경음악 파일이 없습니다.")
    return media_response(path)


@router.post("/projects/{project_id}/music")
async def upload_music(request: Request, project_id: str, file: UploadFile = File(...)) -> dict:
    """내 음악 올리기 (MP3·M4A·AAC·WAV·OGG·FLAC, 50MB까지). 올리면 배경음악이 '내 음악'이 된다."""
    app = state(request)
    app.store.get(project_id)
    suffix = Path(file.filename or "music.mp3").suffix.lower()
    if suffix not in MUSIC_EXTENSIONS:
        raise HTTPException(400, f"{file.filename}: MP3·M4A·AAC·WAV·OGG·FLAC 음악 파일만 올릴 수 있습니다.")
    tmp = app.store.project_dir(project_id) / "music" / f".upload_{uuid.uuid4().hex[:8]}{suffix}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_MUSIC_MB * 1024 * 1024:
                    raise HTTPException(413, f"{file.filename}: 음악 파일이 {MAX_MUSIC_MB}MB를 넘습니다.")
                out.write(chunk)
        try:
            info = await run_in_threadpool(probe, tmp)
        except FFmpegError as error:
            raise HTTPException(400, f"{file.filename}: 음악 정보를 읽지 못했습니다. ({error})") from error
        if not info.has_audio:
            raise HTTPException(400, f"{file.filename}: 소리가 없는 파일입니다.")
        project, plan = music_service.save_user_music(app.store, project_id, tmp, file.filename or tmp.name)
    finally:
        tmp.unlink(missing_ok=True)
    return plan_view(app, project, plan)
