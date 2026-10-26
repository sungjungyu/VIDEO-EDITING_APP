"""VIBE CUT 설정.

환경 변수는 이 파일에서만 읽는다. 다른 모듈은 get_settings()로 가져다 쓴다.
모델 이름이 파일마다 달랐던 문제(main.py, scene_selector.py, scene_analyzer.py …)를 여기서 한 번에 정한다.

주요 환경 변수 (괄호는 기본값)
    GEMINI_API_KEY            Gemini 키 (없으면 gemini_key.txt → api_key.txt)
    VIBECUT_AI_MODE           live | offline  (키가 있으면 live)
                              offline: 네트워크를 쓰지 않는다. 저장해 둔 AI 응답이 있으면 그대로 쓰고,
                              없으면 규칙 기반 판단으로 대신한다 (시연·테스트용)
    GEMINI_MODEL              글 판단용 (gemini-3.5-flash)
    GEMINI_FALLBACK_MODEL     혼잡·한도 초과 시 대체 (gemini-3.5-flash-lite)
    GEMINI_STT_MODEL          받아쓰기 (gemini-3.5-transcribe)
    SCENE_MODEL               영상 장면 이해 (gemini-3.5-flash-lite)
    STT_ENGINE                auto | gemini | whisper-local | energy
    SCENE_ENGINE              auto | gemini | local
    VIBECUT_DATA_DIR          프로젝트·작업·캐시 폴더 (./data)
    VIBECUT_HOST / PORT       서버 주소 (127.0.0.1 / 8000)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
KEY_FILES = ("gemini_key.txt", "api_key.txt")


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _clean_key(raw: str) -> str:
    return raw.strip().strip('"').strip("'").replace("﻿", "")


def load_api_key(root: Path = ROOT_DIR) -> str | None:
    """GEMINI_API_KEY → gemini_key.txt → api_key.txt 순서로 찾는다 (프로젝트 루트 기준 절대 경로)."""
    key = _clean_key(os.getenv("GEMINI_API_KEY", ""))
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
    def static_dir(self) -> Path:
        return self.root_dir / "static"

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
    mode = _env("VIBECUT_AI_MODE", "live" if api_key else "offline").lower()
    values = dict(
        root_dir=root,
        data_dir=Path(_env("VIBECUT_DATA_DIR", str(root / "data"))),
        host=_env("VIBECUT_HOST", "127.0.0.1"),
        port=_env_int("VIBECUT_PORT", 8000),
        api_key=api_key,
        ai_mode=mode if mode in ("live", "offline") else "live",
        stt_engine=_env("STT_ENGINE", "auto").lower(),
        scene_engine=_env("SCENE_ENGINE", "auto").lower(),
        models=Models(
            text=_env("GEMINI_MODEL", "gemini-3.5-flash"),
            text_fallback=_env("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite"),
            stt=_env("GEMINI_STT_MODEL", "gemini-3.5-transcribe"),
            scenes=_env("SCENE_MODEL", "gemini-3.5-flash-lite"),
        ),
        language=_env("VIBECUT_LANGUAGE", "ko"),
        whisper_model=_env("WHISPER_MODEL", "small"),
        gemini_timeout=_env_float("VIBECUT_GEMINI_TIMEOUT", 90.0),
        gemini_retries=_env_int("VIBECUT_GEMINI_RETRIES", 2),
        max_upload_mb=_env_int("VIBECUT_MAX_UPLOAD_MB", 2048),
        retention_days=_env_int("VIBECUT_RETENTION_DAYS", 14),
        analyze_workers=_env_int("VIBECUT_ANALYZE_WORKERS", 1),
        render_workers=_env_int("VIBECUT_RENDER_WORKERS", 1),
    )
    values.update(overrides)
    return Settings(**values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
