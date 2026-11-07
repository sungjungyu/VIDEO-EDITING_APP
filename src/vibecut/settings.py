"""VIBE CUT 설정.

환경 변수는 이 파일에서만 읽는다. 다른 모듈은 get_settings()로 가져다 쓴다.
값은 실제 환경 변수 → 저장소 루트의 .env 파일(KEY=VALUE, .env.example 참고) 순서로 찾는다.

주요 환경 변수 (괄호는 기본값)
    GEMINI_API_KEY            Gemini 키 (예전 방식인 gemini_key.txt / api_key.txt 파일도 읽는다)
    VIBECUT_AI_MODE           live | offline  (키가 있으면 live)
                              offline: 네트워크를 쓰지 않는다. 저장해 둔 AI 응답이 있으면 그대로 쓰고,
                              없으면 규칙 기반 판단으로 대신한다 (시연·테스트용)
    GEMINI_MODEL              글 판단용 (gemini-3.5-flash)
    GEMINI_FALLBACK_MODEL     혼잡·한도 초과 시 대체 (gemini-3.5-flash-lite)
    GEMINI_STT_MODEL          받아쓰기 (gemini-3.5-transcribe)
    SCENE_MODEL               영상 장면 이해 (gemini-3.5-flash-lite)
    STT_ENGINE                auto | gemini | whisper-local | energy
    SCENE_ENGINE              auto | gemini | local
    WHISPER_MODEL             로컬 Whisper 크기 (small)
    WHISPER_INITIAL_PROMPT    로컬 Whisper 안내 문구 (고유명사·숫자 표기 안내)
    FFMPEG_BIN                ffmpeg 실행 파일 (없으면 PATH → imageio-ffmpeg 내장)
    VIBECUT_DATA_DIR          프로젝트·작업·캐시 폴더 (./data)
    VIBECUT_HOST / PORT       서버 주소 (127.0.0.1 / 8000)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]     # src/vibecut/settings.py → 저장소 루트
KEY_FILES = ("gemini_key.txt", "api_key.txt")
DEFAULT_WHISPER_PROMPT = "다음은 자연스러운 한국어 영상 자막입니다. 고유명사, 제품명, 숫자와 단위를 정확히 표기하세요."
TARGET_TOLERANCE = 0.05       # AI 가편집 목표 분량 허용 오차 (±5%) — 화면에도 /api/config로 알려 준다


def read_dotenv(root: Path = ROOT_DIR) -> dict[str, str]:
    """root/.env의 KEY=VALUE 줄을 읽는다 (# 주석·빈 줄 무시, 값의 따옴표 제거). 파일이 없으면 빈 dict."""
    path = root / ".env"
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def _env(name: str, default: str, dotenv: dict[str, str] | None = None) -> str:
    value = os.getenv(name) or (dotenv or {}).get(name)
    return value.strip() if value and value.strip() else default


def env(name: str, default: str) -> str:
    """설정 하나 읽기 (환경 변수 → .env → 기본값). Settings에 없는 명령줄 전용 값에 쓴다."""
    return _env(name, default, read_dotenv())


def _env_int(name: str, default: int, dotenv: dict[str, str] | None = None) -> int:
    try:
        return int(_env(name, str(default), dotenv))
    except ValueError:
        return default


def _env_float(name: str, default: float, dotenv: dict[str, str] | None = None) -> float:
    try:
        return float(_env(name, str(default), dotenv))
    except ValueError:
        return default


def _clean_key(raw: str) -> str:
    return raw.strip().strip('"').strip("'").replace("﻿", "")


def load_api_key(root: Path = ROOT_DIR) -> str | None:
    """GEMINI_API_KEY 환경 변수 → .env → gemini_key.txt → api_key.txt 순서로 찾는다 (프로젝트 루트 기준)."""
    key = _clean_key(os.getenv("GEMINI_API_KEY") or read_dotenv(root).get("GEMINI_API_KEY", ""))
    if key:
        return key
    for name in KEY_FILES:
        path = root / name
        if path.exists():
            key = _clean_key(path.read_text(encoding="utf-8", errors="replace"))
            if key:
                return key
    return None


@dataclass(frozen=True)
class Models:
    text: str
    text_fallback: str
    stt: str
    scenes: str


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    host: str
    port: int
    api_key: str | None
    ai_mode: str
    stt_engine: str
    scene_engine: str
    models: Models
    language: str
    whisper_model: str
    whisper_prompt: str
    ffmpeg_bin: str
    gemini_timeout: float
    gemini_retries: int
    max_upload_mb: int
    retention_days: int
    analyze_workers: int
    render_workers: int

    @property
    def ai_live(self) -> bool:
        """실제로 Gemini를 호출해도 되는가 (키가 있고 offline 모드가 아님)."""
        return self.ai_mode == "live" and bool(self.api_key)

    @property
    def web_dir(self) -> Path:
        """브라우저 화면 파일 (index.html, css, js)."""
        return self.root_dir / "web"

    def public_dict(self) -> dict:
        """화면에 보여 줘도 되는 설정 (키는 있는지만)."""
        return {
            "ai_mode": self.ai_mode if self.api_key else "offline",
            "has_api_key": bool(self.api_key),
            "stt_engine": self.stt_engine,
            "scene_engine": self.scene_engine,
            "models": self.models.__dict__,
            "language": self.language,
            "max_upload_mb": self.max_upload_mb,
        }


def load_settings(**overrides) -> Settings:
    """환경 변수로 Settings를 만든다. 테스트는 overrides로 일부 값만 바꾼다."""
    root = Path(overrides.pop("root_dir", ROOT_DIR))
    api_key = overrides.pop("api_key", load_api_key(root))
    dotenv = read_dotenv(root)
    mode = _env("VIBECUT_AI_MODE", "live" if api_key else "offline", dotenv).lower()
    if mode not in ("live", "offline"):        # 오타면 한도를 쓰는 쪽(live)이 아니라 안전한 쪽으로
        logging.getLogger("vibecut.settings").warning("VIBECUT_AI_MODE=%r을 알 수 없어 offline으로 씁니다.", mode)
        mode = "offline"
    values = dict(
        root_dir=root,
        data_dir=Path(_env("VIBECUT_DATA_DIR", str(root / "data"), dotenv)),
        host=_env("VIBECUT_HOST", "127.0.0.1", dotenv),
        port=_env_int("VIBECUT_PORT", 8000, dotenv),
        api_key=api_key,
        ai_mode=mode,
        stt_engine=_env("STT_ENGINE", "auto", dotenv).lower(),
        scene_engine=_env("SCENE_ENGINE", "auto", dotenv).lower(),
        models=Models(
            text=_env("GEMINI_MODEL", "gemini-3.5-flash", dotenv),
            text_fallback=_env("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite", dotenv),
            stt=_env("GEMINI_STT_MODEL", "gemini-3.5-transcribe", dotenv),
            scenes=_env("SCENE_MODEL", "gemini-3.5-flash-lite", dotenv),
        ),
        language=_env("VIBECUT_LANGUAGE", "ko", dotenv),
        whisper_model=_env("WHISPER_MODEL", "small", dotenv),
        whisper_prompt=_env("WHISPER_INITIAL_PROMPT", DEFAULT_WHISPER_PROMPT, dotenv),
        ffmpeg_bin=_env("FFMPEG_BIN", "", dotenv),
        gemini_timeout=_env_float("VIBECUT_GEMINI_TIMEOUT", 90.0, dotenv),
        gemini_retries=_env_int("VIBECUT_GEMINI_RETRIES", 2, dotenv),
        max_upload_mb=_env_int("VIBECUT_MAX_UPLOAD_MB", 2048, dotenv),
        retention_days=_env_int("VIBECUT_RETENTION_DAYS", 14, dotenv),
        analyze_workers=_env_int("VIBECUT_ANALYZE_WORKERS", 1, dotenv),
        render_workers=_env_int("VIBECUT_RENDER_WORKERS", 1, dotenv),
    )
    values.update(overrides)
    return Settings(**values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
