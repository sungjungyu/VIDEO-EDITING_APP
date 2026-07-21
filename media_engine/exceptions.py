class MediaEngineError(Exception):
    """미디어 엔진 기본 예외"""


class InvalidCutRangeError(MediaEngineError):
    """cuts 구간이 겹치거나, 역전되거나, 영상 길이를 벗어남"""


class FFmpegCuttingError(MediaEngineError):
    """컷 편집 단계 실패 (-c copy 및 재인코딩 fallback 모두 실패)"""


class SubtitleGenerationError(MediaEngineError):
    """.ass 파일 생성 실패 (폰트 없음, 스타일 프리셋 오류 등)"""


class FFmpegEncodingError(MediaEngineError):
    """최종 인코딩 단계 실패"""
