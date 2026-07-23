"""
백엔드 FastAPI 앱 진입점

실행: uvicorn backend.main:app --reload --port 8000
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.routers import compat, upload, edit, render

BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
OUTPUT_DIR = BASE_DIR / "outputs"

app = FastAPI(title="Cutroom AI", version="3.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# compat 은 프론트가 실제로 호출하는 얇은 계약(/analyze, /revise, /render,
# /jobs, /media, /analyze_jobs)을 제공한다. 기존 라우터들과 /jobs 등 경로가
# 겹치므로 반드시 먼저 include 해서 경로 우선순위를 잡는다.
app.include_router(compat.router)
app.include_router(upload.router)
app.include_router(edit.router)
app.include_router(render.router)


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    """현재 메인 화면은 편집기(static/editor.html)."""
    return HTMLResponse((STATIC_DIR / "editor.html").read_text(encoding="utf-8"))


@app.get("/legacy", response_class=HTMLResponse)
async def legacy_home() -> HTMLResponse:
    """이전 메인 화면(index.html)은 /legacy 로 남겨둔다."""
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/download/{filename}")
async def download_file(filename: str) -> FileResponse:
    file_path = OUTPUT_DIR / Path(filename).name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="결과 영상을 찾을 수 없습니다.")
    return FileResponse(file_path, filename=file_path.name, media_type="video/mp4")


if __name__ == "__main__":
    import uvicorn
    print("Cutroom AI 백엔드 서버 시작: http://localhost:8000")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
