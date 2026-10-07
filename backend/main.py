"""
백엔드 FastAPI 앱 진입점

실행: uvicorn backend.main:app --reload --port 8000
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.routers import upload, edit, render

BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
OUTPUT_DIR = BASE_DIR / "outputs"

app = FastAPI(title="Cutroom AI", version="3.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(upload.router)
app.include_router(edit.router)
app.include_router(render.router)


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/download/{filename}")
async def download_file(filename: str) -> FileResponse:
    file_path = OUTPUT_DIR / Path(filename).name
    if not file_path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="결과 영상을 찾을 수 없습니다.")
    return FileResponse(file_path, filename=file_path.name, media_type="video/mp4")


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    from backend import job_store
    from fastapi.responses import JSONResponse
    job = job_store.require_job(job_id)
    return JSONResponse(job)


if __name__ == "__main__":
    import uvicorn
    print("Cutroom AI 백엔드 서버 시작: http://localhost:8000")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
