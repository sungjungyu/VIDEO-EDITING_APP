#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive AI video editor web application."""

import asyncio
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from config import config
from main import VideoEditingPipeline

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
for directory in (STATIC_DIR, UPLOAD_DIR, OUTPUT_DIR):
    directory.mkdir(exist_ok=True)

app = FastAPI(title="Cutroom AI", version="2.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# A lightweight in-memory store is sufficient for the single-process local app.
uploaded_files: Dict[str, Path] = {}
render_jobs: Dict[str, Dict[str, Any]] = {}


class SubtitleSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=1000)
    cut: bool = False
    subtitle_color: str = "white"
    fontsize: int = Field(default=32, ge=16, le=96)


class RenderRequest(BaseModel):
    source_file: str
    segments: List[SubtitleSegment] = Field(min_length=1, max_length=1000)
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


def _safe_upload_name(filename: str) -> str:
    suffix = Path(filename or "video.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        raise HTTPException(status_code=400, detail="MP4, MOV, AVI, MKV, WEBM 영상만 업로드할 수 있습니다.")
    return f"{uuid.uuid4().hex}{suffix}"


def _load_pipeline() -> VideoEditingPipeline:
    api_key = config.load_api_key()
    if not api_key:
        raise RuntimeError("Gemini API 키가 설정되지 않았습니다. GEMINI_API_KEY 또는 gemini_key.txt를 확인하세요.")
    return VideoEditingPipeline(api_key)


def _analyze_video(input_path: Path, style: str) -> List[Dict[str, Any]]:
    pipeline = _load_pipeline()
    try:
        audio_path = pipeline.step1_extract_audio(str(input_path))
        segments = pipeline.step2_transcribe_audio(audio_path)
        segments = pipeline.step2_refine_transcript(segments)
        return pipeline.step3_analyze_context(segments, style)
    finally:
        shutil.rmtree(pipeline.temp_dir, ignore_errors=True)


@app.post("/analyze")
async def analyze_video(file: UploadFile = File(...), style: str = Form("정석맛")) -> JSONResponse:
    """Upload a video and return AI-produced, user-editable subtitle segments."""
    if style not in {"매운맛", "순한맛", "정석맛"}:
        raise HTTPException(status_code=400, detail="지원하지 않는 스타일입니다.")
    if not (file.content_type or "").startswith("video/"):
        raise HTTPException(status_code=400, detail="영상 파일만 업로드할 수 있습니다.")

    stored_name = _safe_upload_name(file.filename or "video.mp4")
    stored_path = UPLOAD_DIR / stored_name
    try:
        content = await file.read()
        if len(content) > 500 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="파일 크기는 500MB를 초과할 수 없습니다.")
        stored_path.write_bytes(content)
        uploaded_files[stored_name] = stored_path
        segments = await asyncio.to_thread(_analyze_video, stored_path, style)
        return JSONResponse({
            "source_file": stored_name,
            "source_url": f"/media/{stored_name}",
            "segments": segments,
        })
    except HTTPException:
        stored_path.unlink(missing_ok=True)
        uploaded_files.pop(stored_name, None)
        raise
    except Exception as error:
        stored_path.unlink(missing_ok=True)
        uploaded_files.pop(stored_name, None)
        raise HTTPException(status_code=500, detail=f"AI 분석에 실패했습니다: {error}") from error


def _render_video(
    job_id: str,
    input_path: Path,
    segments: List[Dict[str, Any]],
    aspect_ratio: str,
) -> None:
    output_name = f"cutroom_{job_id}.mp4"
    output_path = OUTPUT_DIR / output_name
    try:
        render_jobs[job_id].update(progress=20, message="타임라인을 정리하는 중…")
        # Rendering itself does not call Gemini, so no API key is needed at this stage.
        pipeline = VideoEditingPipeline.__new__(VideoEditingPipeline)
        pipeline.temp_dir = ""
        render_jobs[job_id].update(progress=55, message=f"{aspect_ratio} 캔버스에 자막과 컷을 렌더링하는 중…")
        pipeline.step5_create_final_video(
            str(input_path), segments, str(output_path), aspect_ratio=aspect_ratio
        )
        render_jobs[job_id].update(
            status="completed",
            progress=100,
            message="렌더링이 완료되었습니다.",
            output_file=output_name,
            output_url=f"/download/{output_name}",
        )
    except Exception as error:
        render_jobs[job_id].update(status="failed", message=str(error))


@app.post("/render")
async def render_video(request: RenderRequest) -> JSONResponse:
    """Render the exact subtitle/cut data currently edited in the browser."""
    input_path = uploaded_files.get(request.source_file)
    if input_path is None or not input_path.exists():
        raise HTTPException(status_code=404, detail="업로드한 원본 영상을 찾을 수 없습니다. 다시 분석해주세요.")

    normalized_segments = []
    for segment in request.segments:
        if segment.end <= segment.start:
            raise HTTPException(status_code=422, detail="종료 시간은 시작 시간보다 뒤여야 합니다.")
        normalized_segments.append(
            segment.model_dump() if hasattr(segment, "model_dump") else segment.dict()
        )

    job_id = uuid.uuid4().hex
    render_jobs[job_id] = {"status": "processing", "progress": 5, "message": "렌더링을 준비하는 중…"}
    asyncio.create_task(
        asyncio.to_thread(
            _render_video, job_id, input_path, normalized_segments, request.aspect_ratio
        )
    )
    return JSONResponse({"job_id": job_id, **render_jobs[job_id]})


@app.get("/jobs/{job_id}")
async def get_render_job(job_id: str) -> JSONResponse:
    job = render_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="렌더링 작업을 찾을 수 없습니다.")
    return JSONResponse(job)


@app.get("/media/{filename}")
async def media_file(filename: str) -> FileResponse:
    file_path = uploaded_files.get(filename)
    if file_path is None or not file_path.exists():
        raise HTTPException(status_code=404, detail="원본 영상을 찾을 수 없습니다.")
    return FileResponse(file_path, media_type="video/mp4")


@app.get("/download/{filename}")
async def download_file(filename: str) -> FileResponse:
    file_path = OUTPUT_DIR / Path(filename).name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="결과 영상을 찾을 수 없습니다.")
    return FileResponse(file_path, filename=file_path.name, media_type="video/mp4")


if __name__ == "__main__":
    print("🚀 Cutroom AI 서버 시작: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
