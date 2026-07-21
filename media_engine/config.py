import os
import tempfile

# FFmpeg
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")

# 출력 해상도 (None이면 원본 유지)
OUTPUT_WIDTH = None
OUTPUT_HEIGHT = None

# 인코딩 기본값
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
CRF = 23
PRESET = "medium"

# 자막 폰트 (시스템에 설치된 폰트명)
DEFAULT_FONT = "NanumGothic"
FALLBACK_FONT = "Arial"

# 자막 기본 크기
DEFAULT_FONT_SIZE = 24

# 임시 파일 저장 디렉토리
TEMP_DIR = os.environ.get("MEDIA_ENGINE_TEMP_DIR", tempfile.gettempdir())

# 최종 출력 디렉토리
OUTPUT_DIR = os.environ.get("MEDIA_ENGINE_OUTPUT_DIR", os.path.join(TEMP_DIR, "media_engine_output"))
