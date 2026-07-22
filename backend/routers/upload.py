"""POST /upload — 영상 파일 업로드, job_id 발급"""
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from backend import job_store

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB
ALLOWED_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

router = APIRouter()


@router.post("/upload")
async def upload_video(file: UploadFile = File(...)) -> JSONResponse:
    suffix = Path(file.filename or "video.mp4").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="MP4, MOV, AVI, MKV, WEBM 영상만 업로드할 수 있습니다.")
    if not (file.content_type or "").startswith("video/"):
        raise HTTPException(status_code=400, detail="영상 파일만 업로드할 수 있습니다.")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기는 500MB를 초과할 수 없습니다.")

    job_id = uuid.uuid4().hex
    stored_name = f"{job_id}{suffix}"
    stored_path = UPLOAD_DIR / stored_name
    stored_path.write_bytes(content)

    job = job_store.create_job(job_id, str(stored_path), file.filename or stored_name)

    return JSONResponse({
        "job_id": job_id,
        "filename": job["filename"],
        "status": job["status"],
    })
