"""FastAPI 앱 조립.

    vibecut serve              → http://127.0.0.1:8000
    vibecut serve --reload     개발용: 코드를 고치면 자동으로 다시 시작 (uvicorn --factory --reload)

설정(주소·AI 모드·모델 이름·데이터 폴더)은 환경 변수나 .env로 바꾼다: vibecut/settings.py 참고.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..ai.client import GeminiClient
from ..errors import Conflict, NotFound
from ..log import setup_logging
from ..services.jobs import JobManager
from ..settings import Settings, get_settings
from ..storage.projects import ProjectStore
from .deps import AppState
from .routes import router

log = logging.getLogger("vibecut.server")
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging()
    store = ProjectStore(settings.data_dir)
    state = AppState(
        settings=settings,
        store=store,
        jobs=JobManager(settings.data_dir, {"analyze": settings.analyze_workers, "render": settings.render_workers},
                        retention_days=settings.retention_days),
        ai=GeminiClient(settings, store.cache_dir / "ai"),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        removed = state.store.cleanup(settings.retention_days)
        if removed:
            log.info("오래된 중간 파일·미리보기 %d개를 정리했습니다.", removed)
        mode = "live (Gemini 사용)" if settings.ai_live else "offline (규칙·캐시만)"
        log.info("VIBE CUT %s — AI 모드: %s, 데이터: %s", __version__, mode, settings.data_dir)
        yield
        state.jobs.shutdown()

    app = FastAPI(title="VIBE CUT", version=__version__, lifespan=lifespan)
    app.state.vibecut = state
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

    @app.exception_handler(Conflict)
    async def conflict(request: Request, error: Conflict):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(ValueError)
    async def bad_value(request: Request, error: ValueError):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.get("/", include_in_schema=False)
    async def home():
        return FileResponse(settings.web_dir / "index.html", media_type="text/html", headers=NO_CACHE)

    return app


def serve(host: str | None = None, port: int | None = None, reload: bool = False) -> None:
    """웹 서버 실행 (vibecut serve)."""
    import uvicorn

    settings = get_settings()
    host, port = host or settings.host, port or settings.port
    print(f"VIBE CUT 서버 시작: http://{host}:{port}")
    if reload:
        uvicorn.run("vibecut.server.app:create_app", factory=True, host=host, port=port, reload=True)
    else:
        uvicorn.run(create_app(settings), host=host, port=port)
