"""설정·상태: 화면이 시작할 때 한 번 읽는다 (AI 모드, ffmpeg, 글꼴, 자막 기본값, 올릴 수 있는 확장자)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ... import __version__
from ...analysis.stt import whisper_available
from ...domain.models import default_styles
from ...errors import FFmpegError
from ...media.ffmpeg import ffmpeg_path, ffmpeg_version
from ...media.probe import VIDEO_EXTENSIONS
from ...render import fonts
from ...render.ass import REFERENCE_SHORT_SIDE
from ...settings import TARGET_TOLERANCE
from ..deps import state

router = APIRouter()


@router.get("/config")
def get_config(request: Request) -> dict:
    settings = state(request).settings
    try:
        ff = {"path": ffmpeg_path(), "version": ".".join(map(str, ffmpeg_version())), "ok": True}
    except FFmpegError as error:
        ff = {"ok": False, "error": str(error)}
    return {"version": __version__, **settings.public_dict(), "ffmpeg": ff, "whisper": whisper_available(),
            "font_metrics": fonts.font_metrics_table(), "fonts": fonts.available_fonts(),
            "reference_short_side": REFERENCE_SHORT_SIDE,
            "style_defaults": {key: spec.model_dump() for key, spec in default_styles().items()},
            "video_extensions": list(VIDEO_EXTENSIONS), "target_tolerance": TARGET_TOLERANCE}
