"""받아쓰기 (클립 하나): 엔진 고르기·대체·캐시.

    auto → Gemini 받아쓰기(키 있고 live) → 실패/한도 초과면 로컬 Whisper → 그것도 없으면 음량 기반 말소리 구간
    결과는 clean_segments + 무음 기준 단어 경계 보정 + 문장 재분할을 거친 '클립 초' 세그먼트
    같은 파일·엔진·설정이면 캐시를 쓴다 (data/cache/stt)
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import threading
from pathlib import Path

from ...ai.client import GeminiClient, classify_error
from ...errors import Canceled
from ...settings import Settings
from ...storage.cache import JsonCache
from ..audio import detect_silences, frame_levels, wav_duration
from .engines import (
    MIN_SILENCE,
    GeminiSttOptions,
    WhisperOptions,
    speech_regions,
    transcribe_gemini,
    transcribe_whisper_local,
)
from .postprocess import clean_segments, drop_hallucinations, refine_with_silence, split_into_sentences

log = logging.getLogger("vibecut.analysis.stt")


def whisper_available() -> bool:
    try:
        return importlib.util.find_spec("whisper") is not None
    except Exception:
        return False


def engine_chain(settings: Settings) -> list[str]:
    choice = settings.stt_engine
    if choice == "gemini":
        return ["gemini", "whisper-local", "energy"] if settings.ai_live else ["whisper-local", "energy"]
    if choice == "whisper-local":
        return ["whisper-local", "energy"]
    if choice == "energy":
        return ["energy"]
    chain = ["gemini"] if settings.ai_live else []
    return chain + ["whisper-local", "energy"]


def cache_name(sha1: str, engine: str, model: str, language: str, vocab: list[str]) -> str:
    """받아쓰기 캐시 파일 이름 (이 규칙을 바꾸면 저장해 둔 받아쓰기를 못 쓴다)."""
    vocab_key = hashlib.sha1(",".join(vocab).encode("utf-8")).hexdigest()[:8]
    return f"{sha1[:20]}_{engine}_{model}_{language}_{vocab_key}.json"


def _run_engine(engine: str, wav: Path, settings: Settings, client: GeminiClient | None, vocab: list[str],
                levels) -> list[dict]:
    if engine == "gemini":
        if client is None:
            raise RuntimeError("Gemini 클라이언트가 없습니다.")
        options = GeminiSttOptions(model=settings.models.stt, language=settings.language, vocab=tuple(vocab))
        return transcribe_gemini(wav, client, options, levels)["segments"]
    if engine == "whisper-local":
        if not whisper_available():
            raise RuntimeError("openai-whisper가 설치되어 있지 않습니다 (pip install -e '.[whisper]').")
        options = WhisperOptions(model=settings.whisper_model, language=settings.language,
                                 initial_prompt=settings.whisper_prompt)
        raw = transcribe_whisper_local(wav, options)["segments"]
        kept, dropped = drop_hallucinations(raw, options.initial_prompt)
        if dropped:
            log.info("환각 의심 %d개 제외", len(dropped))
        return kept
    raise ValueError(engine)


def transcribe_clip(wav: Path, sha1: str, settings: Settings, cache_dir: Path, vocab: list[str] | None = None,
                    cancel: threading.Event | None = None, client: GeminiClient | None = None) -> dict:
    """{"segments": [...클립 초], "silences": [(s, e)], "engine": "gemini:모델", "warnings": [...]}"""
    vocab = vocab or []
    duration = wav_duration(wav)
    levels = frame_levels(wav)                   # 분할 지점·무음·말소리 구간이 함께 쓴다 (WAV를 한 번만 읽음)
    warnings: list[str] = []
    cache = JsonCache(cache_dir)
    for engine in engine_chain(settings):
        if cancel is not None and cancel.is_set():
            raise Canceled()
        if engine == "energy":
            raw, silences = speech_regions(wav, levels)
            return {"segments": raw, "silences": silences, "engine": "energy",
                    "warnings": warnings + ["받아쓰기 엔진을 쓸 수 없어 말소리 구간만 찾았습니다 (자막 없음)."]}
        model = {"gemini": settings.models.stt, "whisper-local": settings.whisper_model}[engine]
        name = cache_name(sha1, engine, model, settings.language, vocab)
        raw = cache.get(name)
        if raw is None:
            try:
                raw = _run_engine(engine, wav, settings, client, vocab, levels)
            except Exception as error:
                text = str(error)
                if classify_error(error) == "quota":
                    text = "Gemini 받아쓰기 사용 한도를 다 썼습니다 (무료 키는 하루 25회)."
                warnings.append(f"{engine} 받아쓰기 실패 → 다음 엔진 사용: {text[:200]}")
                log.warning("받아쓰기 %s 실패: %s", engine, text[:300])
                continue
            cache.put(name, raw)
        segments = clean_segments(raw, duration)
        silences, _ = detect_silences(levels, MIN_SILENCE)
        if any(s["words"] for s in segments):
            segments = split_into_sentences(refine_with_silence(segments, silences))
        segments = [s for s in segments if s["end"] - s["start"] > 0.05]
        return {"segments": segments, "silences": silences, "engine": f"{engine}:{model}", "warnings": warnings}
    raise AssertionError("엔진 목록은 항상 energy로 끝난다")
