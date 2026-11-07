"""장면 분석 (클립 하나): 엔진 고르기·대체·캐시.

    gemini : 영상 이해 (scenes.gemini) — 키가 있고 live일 때
    local  : 화면 변화 감지 (scenes.local) — 오프라인·키 없음·Gemini 실패 시
같은 파일·모델이면 캐시를 쓴다 (data/cache/scenes).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from ...ai.client import GeminiClient
from ...errors import Canceled
from ...settings import Settings
from ...storage.cache import JsonCache
from .gemini import SceneOptions, describe_scenes
from .local import MIN_SCENE_SEC, local_scenes

log = logging.getLogger("vibecut.analysis.scenes")


def gemini_cache_name(sha1: str, model: str) -> str:
    return f"{sha1[:20]}_gemini_{model}.json"


def local_cache_name(sha1: str) -> str:
    return f"{sha1[:20]}_local_{MIN_SCENE_SEC}.json"


def analyze_clip_scenes(video: Path, sha1: str, duration: float, settings: Settings, cache_dir: Path,
                        work_dir: Path, prev_summary: str = "", known_people: str = "",
                        cancel: threading.Event | None = None, client: GeminiClient | None = None) -> dict:
    """{"scenes": [...클립 초 dict], "engine": ..., "warnings": [...], "usage": {...}}"""
    cache = JsonCache(cache_dir)
    warnings: list[str] = []
    model = settings.models.scenes
    if client is not None and settings.ai_live and settings.scene_engine in ("auto", "gemini"):
        name = gemini_cache_name(sha1, model)
        cached = cache.get(name)
        if cached is not None:
            return {"scenes": cached, "engine": f"gemini:{model}", "warnings": [], "usage": {}}
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            options = SceneOptions(model=model)
            scenes, usage = describe_scenes(client, video, work_dir / f"{video.stem}_{options.height}p.mp4",
                                            duration, options, prev_summary, known_people, cancel)
            cache.put(name, scenes)
            return {"scenes": scenes, "engine": f"gemini:{model}", "warnings": [], "usage": usage}
        except Canceled:
            raise
        except Exception as error:
            log.warning("Gemini 장면 분석 실패: %s", str(error)[:300])
            warnings.append(f"Gemini 영상 분석 실패 → 화면 변화 감지로 대신합니다: {str(error)[:150]}")
    name = local_cache_name(sha1)
    scenes = cache.get(name)
    if scenes is None:
        scenes = local_scenes(video, duration, cancel=cancel)
        cache.put(name, scenes)
    return {"scenes": scenes, "engine": "local", "warnings": warnings, "usage": {}}
