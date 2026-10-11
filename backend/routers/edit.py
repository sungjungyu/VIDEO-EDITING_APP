"""POST /edit — job_id로 AI 파이프라인(Whisper+Gemini) 분석 실행"""
import shutil
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend import job_store
from config import config
from main import VideoEditingPipeline

router = APIRouter()


class EditRequest(BaseModel):
    job_id: str
    style_preset: Literal["매운맛", "순한맛", "정석맛"] = "정석맛"


def _run_pipeline(source_path: str, style: str) -> list[dict]:
    api_key = config.load_api_key()
    if not api_key:
        raise RuntimeError("Gemini API 키가 설정되지 않았습니다. GEMINI_API_KEY 또는 gemini_key.txt를 확인하세요.")
    pipeline = VideoEditingPipeline(api_key)
    try:
        pipeline.verify_gemini_connection()
    except Exception as e:
        print(f"Gemini 연결 확인 실패, fallback 진행: {e}")
    try:
        video_context = pipeline.step0_collect_video_context(source_path)
        audio_path = pipeline.step1_extract_audio(source_path)
        segments = pipeline.step2_transcribe_audio(audio_path)
        segments = pipeline.step2_refine_transcript(segments)
        return pipeline.step3_analyze_context(segments, style, video_context)
    finally:
        shutil.rmtree(pipeline.temp_dir, ignore_errors=True)


@router.post("/edit")
async def edit_video(req: EditRequest) -> JSONResponse:
    job = job_store.require_job(req.job_id)

    if job["status"] not in ("uploaded", "analyzed", "error"):
        raise HTTPException(status_code=409, detail=f"현재 상태({job['status']})에서는 분석을 시작할 수 없습니다.")

    job_store.update_job(req.job_id, status="analyzing")

    try:
        segments = await run_in_threadpool(_run_pipeline, job["source_path"], req.style_preset)
    except Exception as e:
        job_store.update_job(req.job_id, status="error")
        raise HTTPException(status_code=500, detail=f"AI 분석에 실패했습니다: {e}") from e

    job_store.update_job(req.job_id, status="analyzed", segments=segments)

    return JSONResponse({
        "job_id": req.job_id,
        "segments": segments,
        "status": "analyzed",
    })
