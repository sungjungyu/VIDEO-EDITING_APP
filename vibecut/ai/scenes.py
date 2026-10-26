"""장면 분석 (클립 하나).

    gemini : scene_analyzer.py(조경우)의 저해상도 압축 + Gemini 영상 이해 + clean_scenes를 그대로 쓴다
             이전 클립 요약·등장인물 라벨을 다음 클립에 넘긴다 (클립이 끊겨도 같은 장소 판단)
    local  : 1초마다 화면을 작게 뽑아 앞 화면과의 차이로 장면 경계를 찾는다 (오프라인·키 없음·실패 시)
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ..media.ffmpeg import gray_frames
from ..settings import Settings

log = logging.getLogger("vibecut.ai.scenes")

MIN_SCENE_SEC = 8.0


def local_scenes(video: Path, duration: float, min_sec: float = MIN_SCENE_SEC,
                 cancel: threading.Event | None = None) -> list[dict]:
    """화면 변화 감지. 경계 = 앞 화면과 평균 밝기 차이가 '평균 + 2.5×표준편차'(최소 12)를 넘는 곳."""
    frames = gray_frames(video, fps=1.0, size=64, cancel=cancel).astype(np.float32)
    if len(frames) < 2:
        return [{"start": 0.0, "end": duration}]
    diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    threshold = max(12.0, float(diffs.mean() + 2.5 * diffs.std()))
    cuts = [0.0] + [float(i + 1) for i, d in enumerate(diffs) if d >= threshold] + [duration]
    scenes = []
    for s, e in zip(cuts, cuts[1:]):
        e = min(e, duration)
        if e <= s:
            continue
        if scenes and (e - s < min_sec or scenes[-1]["end"] - scenes[-1]["start"] < min_sec):
            scenes[-1]["end"] = e
        else:
            scenes.append({"start": s, "end": e})
    if len(scenes) > 1 and scenes[-1]["end"] - scenes[-1]["start"] < min_sec:
        last = scenes.pop()
        scenes[-1]["end"] = last["end"]
    return scenes


def gemini_scenes(video: Path, duration: float, settings: Settings, work_dir: Path, prev_summary: str,
                  known_people: str) -> tuple[list[dict], dict]:
    from google import genai

    import scene_analyzer
    args = SimpleNamespace(model=settings.models.scenes, mode="static", resolution="low", height=360,
                           min_sec=10.0, retries=settings.gemini_retries)
    work_dir.mkdir(parents=True, exist_ok=True)
    lowres = work_dir / f"{video.stem}_{args.height}p.mp4"
    scene_analyzer.make_lowres(video, lowres, args.height)
    raw, usage = scene_analyzer.analyze_clip(genai.Client(api_key=settings.api_key), lowres, duration, args,
                                             prev_summary, known_people)
    return scene_analyzer.clean_scenes(raw, duration, args.min_sec), usage


def analyze_clip_scenes(video: Path, sha1: str, duration: float, settings: Settings, cache_dir: Path,
                        work_dir: Path, prev_summary: str = "", known_people: str = "",
                        cancel: threading.Event | None = None) -> dict:
    """{"scenes": [...클립 초 dict], "engine": ..., "warnings": [...], "usage": {...}}"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    use_gemini = settings.ai_live and settings.scene_engine in ("auto", "gemini")
    if use_gemini:
        cache = cache_dir / f"{sha1[:20]}_gemini_{settings.models.scenes}.json"
        if cache.exists():
            return {"scenes": json.loads(cache.read_text(encoding="utf-8")),
                    "engine": f"gemini:{settings.models.scenes}", "warnings": [], "usage": {}}
        try:
            scenes, usage = gemini_scenes(video, duration, settings, work_dir, prev_summary, known_people)
            cache.write_text(json.dumps(scenes, ensure_ascii=False), encoding="utf-8")
            return {"scenes": scenes, "engine": f"gemini:{settings.models.scenes}", "warnings": [], "usage": usage}
        except Exception as error:
            log.warning("Gemini 장면 분석 실패: %s", str(error)[:300])
            warnings.append(f"Gemini 영상 분석 실패 → 화면 변화 감지로 대신합니다: {str(error)[:150]}")
    cache = cache_dir / f"{sha1[:20]}_local_{MIN_SCENE_SEC}.json"
    if cache.exists():
        scenes = json.loads(cache.read_text(encoding="utf-8"))
    else:
        scenes = local_scenes(video, duration, cancel=cancel)
        cache.write_text(json.dumps(scenes, ensure_ascii=False), encoding="utf-8")
    return {"scenes": scenes, "engine": "local", "warnings": warnings, "usage": {}}
