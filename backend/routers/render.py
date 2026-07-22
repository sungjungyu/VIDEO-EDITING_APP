"""
POST /render  — 렌더링 시작 (즉시 접수 응답, 진행률은 WebSocket으로)
WS   /ws/{job_id} — 실시간 진행률 수신
"""
import asyncio
import shutil
import traceback
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend import job_store, websocket_manager
from backend.exceptions import to_ws_error, MEDIA_ENGINE_ERRORS
from media_engine import render_video as me_render_video

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

router = APIRouter()


class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float


class SubtitleItem(BaseModel):
    start: float
    end: float
    text: str
    words: list[WordTimestamp] = []


class CutItem(BaseModel):
    start: float
    end: float


class RenderRequest(BaseModel):
    job_id: str
    cuts: list[CutItem]
    subtitles: list[SubtitleItem] = []
    style_preset: Literal["매운맛", "순한맛", "정석맛"] = "정석맛"


def _do_render(job_id: str, source_path: str, edit_data: dict) -> None:
    """렌더링 스레드에서 실행되는 블로킹 함수."""
    output_name = f"{job_id}_final.mp4"
    output_path = OUTPUT_DIR / output_name

    def _progress(stage: str, pct: int) -> None:
        websocket_manager.send_from_thread(job_id, {"stage": stage, "percent": pct})
        job_store.update_job(job_id, progress=pct, stage=stage)

    try:
        job_store.update_job(job_id, status="rendering")
        final_path = me_render_video(source_path, edit_data, _progress)
        shutil.copy2(final_path, str(output_path))

        result_url = f"/download/{output_name}"
        job_store.update_job(job_id, status="done", result_path=str(output_path), result_url=result_url)
        websocket_manager.send_from_thread(job_id, {
            "stage": "done",
            "percent": 100,
            "result_url": result_url,
        })

    except MEDIA_ENGINE_ERRORS as exc:
        job_store.update_job(job_id, status="error")
        websocket_manager.send_from_thread(job_id, to_ws_error(exc))
    except Exception as exc:
        traceback.print_exc()
        job_store.update_job(job_id, status="error")
        websocket_manager.send_from_thread(job_id, to_ws_error(exc))


@router.post("/render")
async def render_video(req: RenderRequest) -> JSONResponse:
    job = job_store.require_job(req.job_id)

    if job["status"] == "rendering":
        raise HTTPException(status_code=409, detail="이미 렌더링이 진행 중입니다.")

    edit_data = {
        "cuts": [c.model_dump() for c in req.cuts],
        "subtitles": [s.model_dump() for s in req.subtitles],
        "style_preset": req.style_preset,
    }

    asyncio.create_task(
        run_in_threadpool(_do_render, req.job_id, job["source_path"], edit_data)
    )

    return JSONResponse({"job_id": req.job_id, "status": "rendering_started"})


@router.websocket("/ws/{job_id}")
async def ws_progress(ws: WebSocket, job_id: str) -> None:
    if job_store.get_job(job_id) is None:
        await ws.close(code=4004)
        return

    await ws.accept()
    loop = asyncio.get_event_loop()
    websocket_manager.register(job_id, ws, loop)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        websocket_manager.unregister(job_id)
