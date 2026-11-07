"""FastAPI 앱 조립.

    vibecut serve              → http://127.0.0.1:8000
    vibecut serve --reload     개발용: 코드를 고치면 자동으로 다시 시작 (uvicorn --factory --reload)

설정(주소·AI 모드·모델 이름·데이터 폴더)은 환경 변수나 .env로 바꾼다: vibecut/settings.py 참고.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .. import __version__
from ..ai.client import GeminiClient
from ..errors import BadRequest, Conflict, NotFound
from ..log import setup_logging
from ..services.jobs import JobManager
from ..settings import Settings, get_settings
from ..storage.projects import ProjectStore
from .deps import AppState
from .routes import router

log = logging.getLogger("vibecut.server")
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}
LOCAL_HOSTS = ("127.0.0.1", "localhost")
OPEN_HOSTS = ("0.0.0.0", "::")      # 일부러 외부에 연 경우(팀 시연)는 접속 주소를 알 수 없어 Host를 검사하지 않는다
SHUTDOWN_TIMEOUT_SEC = 2            # Ctrl+C 종료 시 열린 스트리밍 연결을 최대 2초만 기다린다


def _silence_windows_connection_reset(loop: asyncio.AbstractEventLoop) -> None:
    """Windows에서 브라우저 <video>가 Range 요청을 먼저 끊을 때 찍히는 무해한 WinError 10054를 숨긴다."""
    if os.name != "nt":
        return
    default_handler = loop.get_exception_handler()

    def handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        if isinstance(exc, ConnectionResetError) or (
            isinstance(exc, OSError) and getattr(exc, "winerror", None) == 10054
        ):
            return
        if default_handler is not None:
            default_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handler)


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
        _silence_windows_connection_reset(asyncio.get_running_loop())
        # 영상은 서버가 켜져 있는 동안에만 둔다 (켤 때: 지난번에 못 지운 것까지, 끌 때: 작업을 멈춘 뒤)
        removed = state.store.wipe_media()
        if removed:
            log.info("지난 실행의 프로젝트 %d개(영상·렌더)를 지웠습니다.", removed)
        mode = "live (Gemini 사용)" if settings.ai_live else "offline (규칙·캐시만)"
        log.info("VIBE CUT %s — AI 모드: %s, 데이터: %s", __version__, mode, settings.data_dir)
        yield
        state.jobs.shutdown()
        state.store.wipe_media()

    app = FastAPI(title="VIBE CUT", version=__version__, lifespan=lifespan)
    app.state.vibecut = state
    if settings.host not in OPEN_HOSTS:
        # 인증이 없으니 Host가 이 PC 주소일 때만 받는다 (DNS 리바인딩으로 다른 사이트가 API를 부르는 것 차단)
        allowed = list(dict.fromkeys([*LOCAL_HOSTS, settings.host]))
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed)
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

    @app.exception_handler(BadRequest)
    async def bad_request(request: Request, error: BadRequest):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(ValueError)
    async def server_value_error(request: Request, error: ValueError):
        # BadRequest가 아닌 ValueError는 요청 잘못이 아니라 서버 쪽 문제다 (저장 파일 깨짐·코드 버그)
        log.error("요청 처리 중 오류 (%s %s)", request.method, request.url.path,
                  exc_info=(type(error), error, error.__traceback__))
        return JSONResponse({"detail": "서버에서 처리하지 못했습니다. 서버 로그를 확인하세요."}, status_code=500)

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
        uvicorn.run("vibecut.server.app:create_app", factory=True, host=host, port=port, reload=True,
                    timeout_graceful_shutdown=SHUTDOWN_TIMEOUT_SEC)
    else:
        uvicorn.run(create_app(settings), host=host, port=port,
                    timeout_graceful_shutdown=SHUTDOWN_TIMEOUT_SEC)
