#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive AI video editor web application."""

import asyncio
import json
import os
import shutil
import sys
import uuid
import traceback
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from config import config
from main import VideoEditingPipeline

# Windows cp949 터미널에서 이모지 print 시 UnicodeEncodeError 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
for directory in (STATIC_DIR, UPLOAD_DIR, OUTPUT_DIR):
    directory.mkdir(exist_ok=True)

app = FastAPI(title="VibeCut", version="2.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

uploaded_files: Dict[str, Path] = {}
render_jobs: Dict[str, Dict[str, Any]] = {}
analyze_jobs: Dict[str, Dict[str, Any]] = {}


class SubtitleSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=1000)
    cut: bool = False
    subtitle_color: str = "white"
    fontsize: int = Field(default=32, ge=16, le=96)


class StyleOverrides(BaseModel):
    font: Optional[str] = None
    color: Optional[str] = None
    size: Optional[int] = None
    outline: Optional[bool] = None
    outline_width: Optional[float] = None
    background_box: Optional[bool] = None
    karaoke: Optional[bool] = None
    fade: Optional[bool] = None


class RenderRequest(BaseModel):
    source_file: str
    segments: List[SubtitleSegment] = Field(min_length=1, max_length=1000)
    style_preset: Literal["매운맛", "순한맛", "정석맛"] = "정석맛"
    style_overrides: Optional[StyleOverrides] = None
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"


class ReviseRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    segments: List[SubtitleSegment] = Field(min_length=1, max_length=1000)


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
        raise RuntimeError("Gemini API 키가 설정되지 않았습니다.")
    pipeline = VideoEditingPipeline(api_key)
    try:
        pipeline.verify_gemini_connection()
    except Exception as e:
        print(f"Gemini 연결 확인 실패, 계속 진행합니다: {e}")
    return pipeline


# ── Upload ──────────────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_video(file: UploadFile = File(...)) -> JSONResponse:
    """영상 파일만 저장하고 source_file 토큰 반환 (분석 없음)."""
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
        return JSONResponse({"source_file": stored_name, "source_url": f"/media/{stored_name}"})
    except HTTPException:
        stored_path.unlink(missing_ok=True)
        uploaded_files.pop(stored_name, None)
        raise
    except Exception as error:
        stored_path.unlink(missing_ok=True)
        uploaded_files.pop(stored_name, None)
        raise HTTPException(status_code=500, detail=f"업로드 실패: {error}") from error


# ── Analyze ─────────────────────────────────────────────────────────────────

def _analyze_video_with_progress(
    job_id: str, input_path: Path, stored_name: str, style: str
) -> None:
    def stage(msg: str, pct: int) -> None:
        analyze_jobs[job_id].update(stage=msg, progress=pct)

    pipeline = _load_pipeline()
    try:
        stage("음성 추출 중...", 10)
        audio_path = pipeline.step1_extract_audio(str(input_path))

        stage("음성 인식(Whisper) 처리 중... (시간이 걸립니다)", 15)
        segments = pipeline.step2_transcribe_audio(audio_path)

        stage("자막 교정 중...", 65)
        segments = pipeline.step2_refine_transcript(segments)

        stage("AI 문맥 분석(Gemini) 중...", 75)
        segments = pipeline.step3_analyze_context(segments, style)

        analyze_jobs[job_id].update(
            status="completed", stage="분석 완료", progress=100,
            segments=segments, source_file=stored_name,
            source_url=f"/media/{stored_name}",
        )
    except Exception as error:
        traceback.print_exc()
        analyze_jobs[job_id].update(status="failed", stage="분석 실패", message=str(error))
    finally:
        shutil.rmtree(pipeline.temp_dir, ignore_errors=True)


@app.post("/analyze")
async def analyze_video(file: UploadFile = File(...), style: str = Form("정석맛")) -> JSONResponse:
    """영상 업로드 후 AI 분석을 백그라운드로 시작, job_id 즉시 반환."""
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
    except HTTPException:
        stored_path.unlink(missing_ok=True)
        uploaded_files.pop(stored_name, None)
        raise
    except Exception as error:
        stored_path.unlink(missing_ok=True)
        uploaded_files.pop(stored_name, None)
        raise HTTPException(status_code=500, detail=f"업로드 실패: {error}") from error

    job_id = uuid.uuid4().hex
    analyze_jobs[job_id] = {"status": "processing", "stage": "업로드 완료, 분석 시작...", "progress": 2}
    asyncio.create_task(
        asyncio.to_thread(_analyze_video_with_progress, job_id, stored_path, stored_name, style)
    )
    return JSONResponse({"job_id": job_id, "status": "processing"})


@app.get("/analyze_jobs/{job_id}")
async def get_analyze_job(job_id: str) -> JSONResponse:
    job = analyze_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="분석 작업을 찾을 수 없습니다.")
    return JSONResponse(job)


# ── Revise ───────────────────────────────────────────────────────────────────

def _revise_segments(instruction: str, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    pipeline = _load_pipeline()
    prompt = (
        "당신은 영상 편집 AI 어시스턴트입니다.\n"
        "아래 JSON 형식의 세그먼트 목록과 사용자의 편집 지시를 받아,\n"
        "지시에 따라 세그먼트를 수정하고 수정된 JSON 배열만 반환하세요.\n\n"
        f"편집 지시: {instruction}\n\n"
        "세그먼트:\n"
        f"{json.dumps(segments, ensure_ascii=False, indent=2)}\n\n"
        "규칙:\n"
        "- cut이 true이면 해당 구간을 삭제, false이면 유지\n"
        "- 지시에 따라 cut 값이나 text를 수정할 수 있음\n"
        "- start/end 시간과 세그먼트 순서는 절대 변경하지 말 것\n"
        "- JSON 배열만 반환하고 다른 설명 텍스트는 포함하지 말 것\n"
    )
    response_text = pipeline._call_gemini(prompt)
    text = (response_text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    revised = json.loads(text)
    if not isinstance(revised, list):
        raise ValueError("Gemini 응답이 JSON 배열이 아닙니다.")
    return {"ok": True, "message": "AI 수정 완료", "segments": revised}


@app.post("/revise")
async def revise_segments(request: ReviseRequest) -> JSONResponse:
    """자연어 지시로 세그먼트를 Gemini가 수정."""
    segments_data = [
        s.model_dump() if hasattr(s, "model_dump") else s.dict()
        for s in request.segments
    ]
    try:
        result = await asyncio.to_thread(_revise_segments, request.instruction, segments_data)
        return JSONResponse(result)
    except Exception as error:
        traceback.print_exc()
        return JSONResponse({"ok": False, "message": f"AI 수정 실패: {error}"})


# ── Render ───────────────────────────────────────────────────────────────────

def _render_video(
    job_id: str, input_path: Path, segments: List[Dict[str, Any]],
    aspect_ratio: str, style_preset: str = "정석맛",
    style_overrides: Optional[Dict[str, Any]] = None,
) -> None:
    output_name = f"vibecut_{job_id}.mp4"
    output_path = OUTPUT_DIR / output_name
    try:
        render_jobs[job_id].update(progress=20, message="타임라인을 정리하는 중...")
        pipeline = VideoEditingPipeline.__new__(VideoEditingPipeline)
        pipeline.temp_dir = ""
        # style_overrides 가 있으면 세그먼트의 색상·크기를 일괄 덮어씀
        if style_overrides:
            for seg in segments:
                if style_overrides.get("color"):
                    seg["subtitle_color"] = style_overrides["color"]
                if style_overrides.get("size") is not None:
                    seg["fontsize"] = int(style_overrides["size"])
        render_jobs[job_id].update(progress=55, message="렌더링 중...")
        pipeline.step5_create_final_video(
            str(input_path), segments, str(output_path), aspect_ratio=aspect_ratio
        )
        render_jobs[job_id].update(
            status="completed", progress=100,
            message="렌더링이 완료되었습니다.",
            output_file=output_name,
            output_url=f"/download/{output_name}",
        )
    except Exception as error:
        traceback.print_exc()
        render_jobs[job_id].update(status="failed", message=str(error))


@app.post("/render")
async def render_video(request: RenderRequest) -> JSONResponse:
    input_path = uploaded_files.get(request.source_file)
    if input_path is None or not input_path.exists():
        raise HTTPException(status_code=404, detail="원본 영상을 찾을 수 없습니다. 다시 분석해주세요.")

    normalized = []
    for seg in request.segments:
        if seg.end <= seg.start:
            raise HTTPException(status_code=422, detail="종료 시간은 시작 시간보다 뒤여야 합니다.")
        normalized.append(seg.model_dump() if hasattr(seg, "model_dump") else seg.dict())

    overrides = (
        request.style_overrides.model_dump(exclude_none=True)
        if request.style_overrides else None
    )

    job_id = uuid.uuid4().hex
    render_jobs[job_id] = {"status": "processing", "progress": 5, "message": "렌더링을 준비하는 중..."}
    asyncio.create_task(
        asyncio.to_thread(
            _render_video, job_id, input_path, normalized,
            request.aspect_ratio, request.style_preset, overrides,
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
    print("VibeCut 서버 시작: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
