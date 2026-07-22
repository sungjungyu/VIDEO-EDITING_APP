"""
미디어 엔진 예외 → 웹소켓 에러 메시지 변환
"""
from media_engine.exceptions import (
    MediaEngineError,
    InvalidCutRangeError,
    FFmpegCuttingError,
    SubtitleGenerationError,
    FFmpegEncodingError,
)


def to_ws_error(exc: Exception) -> dict:
    """예외 객체 → 웹소켓으로 전송할 error 페이로드."""
    error_type = type(exc).__name__
    message = str(exc)
    return {"stage": "error", "error_type": error_type, "message": message}


MEDIA_ENGINE_ERRORS = (
    InvalidCutRangeError,
    FFmpegCuttingError,
    SubtitleGenerationError,
    FFmpegEncodingError,
    MediaEngineError,
)
