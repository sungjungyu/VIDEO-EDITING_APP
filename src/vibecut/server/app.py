"""FastAPI 앱 조립.

    vibecut-server                                              → http://127.0.0.1:8000
    python -m vibecut.server                                    (같은 동작)
    uvicorn vibecut.server.app:create_app --factory --reload    (개발용: 코드 수정 시 자동 재시작)

설정(주소·AI 모드·모델 이름·데이터 폴더)은 환경 변수나 .env로 바꾼다: vibecut/settings.py 참고.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..log import setup_logging
from ..settings import Settings, get_settings
from .api import router
from .jobs import JobManager
from .storage import NotFound, ProjectStore

log = logging.getLogger("vibecut.server")
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        removed = app.state.store.cleanup(settings.retention_days)
        if removed:
            log.info("오래된 중간 파일·미리보기 %d개를 정리했습니다.", removed)
        mode = "live (Gemini 사용)" if settings.ai_live else "offline (규칙·캐시만)"
        log.info("VIBE CUT %s — AI 모드: %s, 데이터: %s", __version__, mode, settings.data_dir)
        yield
        app.state.jobs.shutdown()

    app = FastAPI(title="VIBE CUT", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.store = ProjectStore(settings.data_dir)
    app.state.jobs = JobManager(settings.data_dir, {"analyze": settings.analyze_workers,
                                                    "render": settings.render_workers})
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=settings.web_dir), name="static")

    @app.middleware("http")
    async def no_cache_static(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):      # 개발 중 수정한 화면 코드가 바로 반영되게
            response.headers.update(NO_CACHE)
        return response

    @app.exception_handler(NotFound)
    async def not_found(request: Request, error: NotFound):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(ValueError)
    async def bad_value(request: Request, error: ValueError):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.get("/", include_in_schema=False)
    async def home():
        return FileResponse(settings.web_dir / "index.html", media_type="text/html", headers=NO_CACHE)

    return app


def run() -> None:
    """웹 서버 실행 (명령 `vibecut-server`)."""
    import uvicorn

    settings = get_settings()
    print(f"VIBE CUT 서버 시작: http://{settings.host}:{settings.port}")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
