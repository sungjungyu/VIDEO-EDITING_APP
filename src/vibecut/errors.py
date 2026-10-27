"""VIBE CUT 예외. 모든 계층이 여기서 가져다 쓴다 (예외 때문에 위 계층 모듈을 import하지 않게).

    VibecutError
     ├─ NotFound        프로젝트·클립·파일이 없음 (API에서 404)
     ├─ Conflict        지금 상태에서는 할 수 없음 — 분석 전·분석 중 (API에서 409)
     ├─ Canceled        사용자가 작업을 취소함
     ├─ FFmpegError     ffmpeg 실행·영상 읽기 실패
     ├─ AIUnavailable   키가 없거나 오프라인 모드라 Gemini를 부를 수 없음 (캐시에도 없음)
     └─ AIError         재시도·대체 모델까지 써도 Gemini 호출 실패
"""

from __future__ import annotations

CANCELED_MESSAGE = "사용자가 작업을 취소했습니다."


class VibecutError(Exception):
    pass


class NotFound(VibecutError, LookupError):
    pass


class Conflict(VibecutError):
    pass


class Canceled(VibecutError):
    def __init__(self, message: str = CANCELED_MESSAGE):
        super().__init__(message)


class FFmpegError(VibecutError, RuntimeError):
    pass


class AIUnavailable(VibecutError, RuntimeError):
    pass


class AIError(VibecutError, RuntimeError):
    pass
