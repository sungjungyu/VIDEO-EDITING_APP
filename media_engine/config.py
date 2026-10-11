import os
import shutil
import tempfile


def _find_bin(name: str) -> str:
    """PATH에서 못 찾으면 WinGet 설치 경로를 탐색한다."""
    if shutil.which(name):
        return name
    winget_base = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Microsoft", "WinGet", "Packages",
    )
    if os.path.isdir(winget_base):
        for root, _, files in os.walk(winget_base):
            if f"{name}.exe" in files:
                return os.path.join(root, f"{name}.exe")
    return name


# FFmpeg
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", _find_bin("ffmpeg"))
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", _find_bin("ffprobe"))

# 출력 해상도 (None이면 원본 유지)
OUTPUT_WIDTH = None
OUTPUT_HEIGHT = None

# 인코딩 기본값
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
CRF = 23
PRESET = "medium"

# 자막 폰트 (시스템에 설치된 폰트명)
DEFAULT_FONT = "Malgun Gothic"
FALLBACK_FONT = "Arial"

# 자막 기본 크기
DEFAULT_FONT_SIZE = 24

# 임시 파일 저장 디렉토리
TEMP_DIR = os.environ.get("MEDIA_ENGINE_TEMP_DIR", tempfile.gettempdir())

# 최종 출력 디렉토리
OUTPUT_DIR = os.environ.get("MEDIA_ENGINE_OUTPUT_DIR", os.path.join(TEMP_DIR, "media_engine_output"))
