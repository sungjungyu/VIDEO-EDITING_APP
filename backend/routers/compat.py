"""
프론트엔드(static/editor.html) 호환 라우터.

기존 upload.py / edit.py / render.py 는 job_id 기반의 다단계 흐름
(업로드 → /edit → /render + WebSocket)을 제공하지만, 현재 프론트가 실제로
호출하는 계약은 다음과 같이 더 얇고 완결적이다.

  1) POST /analyze              — multipart(file, style) → {job_id}
     · 업로드 + 분석을 한 번에 시작하고 즉시 job_id 반환
  2) GET  /analyze_jobs/{job_id} — 진행률/단계와 (완료 시) segments, source_file
  3) POST /revise               — 자연어 지시로 cut/text만 수정
  4) POST /render               — {source_file, segments, style_preset} → {job_id}
  5) GET  /jobs/{job_id}         — 렌더 진행률/결과 URL
  6) GET  /media/{filename}      — 업로드 원본 스트리밍

내부 상태는 backend.job_store 를 그대로 재사용하고, 프론트가 기대하는
{"processing" | "completed" | "failed"} 3-상태로 매핑해서 응답한다.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import traceback
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend import job_store
from config import config
from main import VideoEditingPipeline
from media_engine import render_video as me_render_video, segments_to_edit_data

BASE_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE = 500 * 1024 * 1024
ALLOWED_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALLOWED_STYLES = {"매운맛", "순한맛", "정석맛"}

router = APIRouter()

# source_file(=uuid.ext) → 업로드 원본 절대경로.
# /render 는 source_file 로 원본을 다시 찾아야 하고 /media 도 여기서 서빙한다.
_uploaded_files: dict[str, Path] = {}


# --------------------------------------------------------------------------- #
# 공통 유틸
# --------------------------------------------------------------------------- #

class SubtitleSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=1000)
    cut: bool = False
    subtitle_color: str = "white"
    fontsize: int = Field(default=32, ge=16, le=96)


class ReviseRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    segments: list[SubtitleSegment] = Field(min_length=1, max_length=1000)


class RenderRequest(BaseModel):
    source_file: str = Field(min_length=1, max_length=200)
    segments: list[SubtitleSegment] = Field(min_length=1, max_length=1000)
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    style_preset: Literal["매운맛", "순한맛", "정석맛"] = "정석맛"


def _safe_upload_name(filename: str) -> str:
    suffix = Path(filename or "video.mp4").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="MP4, MOV, AVI, MKV, WEBM 영상만 업로드할 수 있습니다.",
        )
    return f"{uuid.uuid4().hex}{suffix}"


def _load_pipeline() -> VideoEditingPipeline:
    api_key = config.load_api_key()
    if not api_key:
        raise RuntimeError(
            "Gemini API 키가 설정되지 않았습니다. GEMINI_API_KEY 또는 gemini_key.txt를 확인하세요."
        )
    pipeline = VideoEditingPipeline(api_key)
    try:
        pipeline.verify_gemini_connection()
    except Exception as error:  # noqa: BLE001 — 폴백 경로가 이미 존재
        print(f"Gemini 연결 확인 실패, 로컬 fallback으로 계속 진행합니다: {error}")
    return pipeline


# 내부 job_store status → 프론트가 폴링에서 기대하는 3-상태로 축약.
_PROCESSING = {"uploaded", "analyzing", "rendering"}
_COMPLETED = {"analyzed", "done"}


def _public_status(internal: str | None) -> str:
    if internal in _COMPLETED:
        return "completed"
    if internal == "error":
        return "failed"
    return "processing"


# --------------------------------------------------------------------------- #
# /analyze  (업로드 + 분석 백그라운드 시작)
# --------------------------------------------------------------------------- #

def _run_analyze_pipeline(job_id: str, source_path: Path, style: str) -> None:
    """블로킹 파이프라인 실행. 단계마다 job_store 를 갱신한다."""
    def stage(msg: str, pct: int) -> None:
        job_store.update_job(job_id, progress=pct, stage=msg, message=msg)

    try:
        pipeline = _load_pipeline()
    except Exception as error:
        traceback.print_exc()
        job_store.update_job(
            job_id,
            status="error",
            stage="분석 실패",
            message=str(error),
        )
        return

    try:
        stage("영상 정보 수집 중...", 5)
        video_context = pipeline.step0_collect_video_context(str(source_path))

        stage("음성 추출 중...", 10)
        audio_path = pipeline.step1_extract_audio(str(source_path))

        stage("음성 인식(Whisper) 처리 중... (가장 오래 걸립니다)", 15)
        segments = pipeline.step2_transcribe_audio(audio_path)

        stage("자막 표기 교정 중...", 65)
        segments = pipeline.step2_refine_transcript(segments)

        stage("AI 편집 판단(Gemini) 중...", 80)
        segments = pipeline.step3_analyze_context(segments, style, video_context)

        job_store.update_job(
            job_id,
            status="analyzed",
            progress=100,
            stage="분석 완료",
            message="분석 완료",
            segments=segments,
        )
    except Exception as error:
        traceback.print_exc()
        job_store.update_job(
            job_id,
            status="error",
            stage="분석 실패",
            message=str(error),
        )
    finally:
        shutil.rmtree(pipeline.temp_dir, ignore_errors=True)


@router.post("/analyze")
async def analyze_video(
    file: UploadFile = File(...),
    style: str = Form("정석맛"),
) -> JSONResponse:
    """영상 업로드 + AI 분석을 한 번에 시작하고 즉시 job_id 만 반환."""
    if style not in ALLOWED_STYLES:
        raise HTTPException(status_code=400, detail="지원하지 않는 스타일입니다.")
    if not (file.content_type or "").startswith("video/"):
        raise HTTPException(status_code=400, detail="영상 파일만 업로드할 수 있습니다.")

    stored_name = _safe_upload_name(file.filename or "video.mp4")
    stored_path = UPLOAD_DIR / stored_name
    try:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="파일 크기는 500MB를 초과할 수 없습니다.")
        stored_path.write_bytes(content)
    except HTTPException:
        stored_path.unlink(missing_ok=True)
        raise
    except Exception as error:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"업로드에 실패했습니다: {error}") from error

    _uploaded_files[stored_name] = stored_path

    # job_id 를 source_file(stored_name)로 맞춰두면 폴링 완료 시 source_file 을
    # 별도 필드로 계속 되돌려 줄 수 있어 프론트 계약이 간결해진다.
    job_id = stored_path.stem
    job_store.create_job(job_id, str(stored_path), file.filename or stored_name)
    job_store.update_job(
        job_id,
        status="analyzing",
        progress=2,
        stage="업로드 완료, 분석 시작...",
        message="업로드 완료, 분석 시작...",
        source_file=stored_name,
    )

    asyncio.create_task(run_in_threadpool(_run_analyze_pipeline, job_id, stored_path, style))

    return JSONResponse({"job_id": job_id, "status": "processing"})


@router.get("/analyze_jobs/{job_id}")
async def get_analyze_job(job_id: str) -> JSONResponse:
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="분석 작업을 찾을 수 없습니다.")

    payload: dict[str, Any] = {
        "status": _public_status(job.get("status")),
        "progress": job.get("progress", 0),
        "stage": job.get("stage", ""),
        "message": job.get("message", ""),
    }
    if payload["status"] == "completed":
        payload["source_file"] = job.get("source_file")
        payload["segments"] = job.get("segments") or []
    return JSONResponse(payload)


# --------------------------------------------------------------------------- #
# /revise  (Gemini 자연어 편집)
# --------------------------------------------------------------------------- #

def _revise_with_gemini(instruction: str, segments: list[dict]) -> list[dict]:
    """지시를 반영한 세그먼트 배열을 Gemini 로부터 받아 검증 후 반환."""
    pipeline = _load_pipeline()
    try:
        prompt = (
            "당신은 영상 편집 AI 어시스턴트입니다.\n"
            "아래 JSON 형식의 세그먼트 목록과 사용자의 편집 지시를 받아,\n"
            "지시에 따라 cut 값 또는 text 만 수정하고 수정된 JSON 배열만 반환하세요.\n\n"
            f"편집 지시: {instruction}\n\n"
            "세그먼트:\n"
            f"{json.dumps(segments, ensure_ascii=False, indent=2)}\n\n"
            "규칙:\n"
            "- cut 이 true 이면 해당 구간을 삭제, false 이면 유지\n"
            "- 지시에 따라 cut 값이나 text 를 수정할 수 있음\n"
            "- start/end 시간과 세그먼트 순서·개수는 절대 변경하지 말 것\n"
            "- JSON 배열만 반환하고 다른 설명 텍스트는 포함하지 말 것\n"
        )
        response_text = str(pipeline._call_gemini(prompt) or "").strip()
    finally:
        shutil.rmtree(pipeline.temp_dir, ignore_errors=True)

    if response_text.startswith("```"):
        lines = response_text.split("\n")
        end = -1 if lines and lines[-1].strip() == "```" else len(lines)
        response_text = "\n".join(lines[1:end]).strip()

    revised = json.loads(response_text)
    if not isinstance(revised, list):
        raise ValueError("Gemini 응답이 JSON 배열이 아닙니다.")
    if len(revised) != len(segments):
        raise ValueError(
            f"세그먼트 개수가 일치하지 않습니다 (입력 {len(segments)} vs 응답 {len(revised)})."
        )

    # start/end/개수/순서는 원본을 강제로 유지하고, cut/text/색상/폰트만 반영한다.
    merged: list[dict] = []
    for original, updated in zip(segments, revised):
        if not isinstance(updated, dict):
            raise ValueError("응답 배열 원소가 객체가 아닙니다.")
        merged.append({
            "start": original["start"],
            "end": original["end"],
            "text": str(updated.get("text", original["text"])).strip() or original["text"],
            "cut": bool(updated.get("cut", original.get("cut", False))),
            "subtitle_color": str(updated.get("subtitle_color", original.get("subtitle_color", "white"))),
            "fontsize": int(updated.get("fontsize", original.get("fontsize", 32)) or 32),
        })
    return merged


@router.post("/revise")
async def revise_segments(req: ReviseRequest) -> JSONResponse:
    segments_in = [
        s.model_dump() if hasattr(s, "model_dump") else s.dict()  # type: ignore[attr-defined]
        for s in req.segments
    ]
    try:
        revised = await run_in_threadpool(_revise_with_gemini, req.instruction, segments_in)
        return JSONResponse({"ok": True, "message": "AI 수정 완료", "segments": revised})
    except Exception as error:
        traceback.print_exc()
        return JSONResponse({"ok": False, "message": f"AI 수정 실패: {error}"})


# --------------------------------------------------------------------------- #
# /render + /jobs  (media_engine 렌더링)
# --------------------------------------------------------------------------- #

def _run_render(job_id: str, source_path: Path, edit_data: dict) -> None:
    output_name = f"cutroom_{job_id}.mp4"
    output_path = OUTPUT_DIR / output_name

    def _progress(stage: str, pct: int) -> None:
        job_store.update_job(
            job_id,
            progress=pct,
            stage=stage,
            message=f"{stage}...",
        )

    try:
        job_store.update_job(job_id, status="rendering", progress=10, message="렌더링을 준비하는 중...")
        final_path = me_render_video(str(source_path), edit_data, _progress)
        shutil.copy2(final_path, str(output_path))

        result_url = f"/download/{output_name}"
        job_store.update_job(
            job_id,
            status="done",
            progress=100,
            stage="done",
            message="렌더링이 완료되었습니다.",
            result_path=str(output_path),
            result_url=result_url,
            output_file=output_name,
            output_url=result_url,
        )
    except Exception as error:
        traceback.print_exc()
        job_store.update_job(
            job_id,
            status="error",
            stage="렌더링 실패",
            message=str(error),
        )


@router.post("/render")
async def render_video_endpoint(req: RenderRequest) -> JSONResponse:
    source_path = _uploaded_files.get(req.source_file)
    if source_path is None or not source_path.exists():
        raise HTTPException(
            status_code=404,
            detail="업로드한 원본 영상을 찾을 수 없습니다. 다시 분석해주세요.",
        )

    normalized: list[dict] = []
    for segment in req.segments:
        if segment.end <= segment.start:
            raise HTTPException(status_code=422, detail="종료 시간은 시작 시간보다 뒤여야 합니다.")
        normalized.append(
            segment.model_dump() if hasattr(segment, "model_dump") else segment.dict()  # type: ignore[attr-defined]
        )

    edit_data = segments_to_edit_data(normalized, style_preset=req.style_preset)

    job_id = uuid.uuid4().hex
    job_store.create_job(job_id, str(source_path), req.source_file)
    job_store.update_job(
        job_id,
        status="rendering",
        progress=5,
        stage="렌더링 대기열",
        message="렌더링을 준비하는 중...",
    )

    asyncio.create_task(run_in_threadpool(_run_render, job_id, source_path, edit_data))

    return JSONResponse({
        "job_id": job_id,
        "status": "processing",
        "progress": 5,
        "message": "렌더링을 준비하는 중...",
    })


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> JSONResponse:
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

    payload: dict[str, Any] = {
        "status": _public_status(job.get("status")),
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "stage": job.get("stage", ""),
    }
    output_url = job.get("output_url") or job.get("result_url")
    if output_url:
        payload["output_url"] = output_url
    if job.get("output_file"):
        payload["output_file"] = job["output_file"]
    return JSONResponse(payload)


# --------------------------------------------------------------------------- #
# /media  (업로드 원본 스트리밍)
# --------------------------------------------------------------------------- #

@router.get("/media/{filename}")
async def media_file(filename: str) -> FileResponse:
    path = _uploaded_files.get(filename)
    if path is None or not path.exists():
        # 프로세스 재시작 후에도 파일이 디스크에 남아 있다면 이름으로 복구를 시도한다.
        candidate = UPLOAD_DIR / Path(filename).name
        if candidate.exists():
            _uploaded_files[candidate.name] = candidate
            path = candidate
        else:
            raise HTTPException(status_code=404, detail="원본 영상을 찾을 수 없습니다.")
    return FileResponse(path, media_type="video/mp4")
