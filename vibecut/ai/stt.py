"""받아쓰기 (클립 하나). 엔진 코드는 transcriber.py(권용관)를 그대로 쓰고, 고르는 규칙과 대체만 여기서 정한다.

    auto → Gemini 받아쓰기(키 있고 live) → 실패/한도 초과면 로컬 Whisper → 그것도 없으면 음량 기반 말소리 구간
    결과는 transcriber.clean_segments + 무음 기준 단어 경계 보정을 거친 '클립 초' 세그먼트
    같은 파일·엔진·설정이면 캐시를 쓴다 (data/cache/stt)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ..media.ffmpeg import Canceled
from ..settings import Settings

log = logging.getLogger("vibecut.ai.stt")

MIN_SILENCE = 0.25


def whisper_available() -> bool:
    try:
        import importlib.util
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


def wav_duration(wav: Path) -> float:
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


def speech_regions(wav: Path) -> tuple[list[dict], list[tuple[float, float]]]:
    """받아쓰기 없이 말소리가 있는 구간만 찾는다 (오프라인 최후 수단). 글자는 비워 둔다."""
    import transcriber
    duration = wav_duration(wav)
    silences, _ = transcriber.detect_silences(wav, MIN_SILENCE)
    regions, cursor = [], 0.0
    for a, b in silences + [(duration, duration)]:
        if a - cursor >= 0.3:
            regions.append((cursor, a))
        cursor = b
    segments = []
    for s, e in regions:            # 긴 구간은 4초 안팎으로 나눈다 (문장 단위처럼 고르고 자를 수 있게)
        n = max(1, round((e - s) / 4))
        step = (e - s) / n
        for i in range(n):
            segments.append({"start": s + i * step, "end": s + (i + 1) * step, "text": "", "words": []})
    return segments, silences


def split_into_sentences(segments: list[dict]) -> list[dict]:
    """Whisper는 2~3문장을 한 덩어리로 묶는다 ("음. 라떼가 유명하다고. 아 다시 할게. …").
    덩어리째 자르면 살려야 할 문장까지 잘리므로, 단어 시각과 문장부호·쉼으로 문장 단위로 다시 나눈다
    (Gemini 받아쓰기와 같은 기준: transcriber.split_sentences)."""
    import transcriber
    out = []
    for seg in segments:
        words = seg.get("words") or []
        if len(words) < 2:
            out.append(seg)
            continue
        for group in transcriber.split_sentences(words):
            item = {"start": group[0]["start"], "end": group[-1]["end"],
                    "text": " ".join(w["word"] for w in group), "words": group}
            if seg.get("speaker"):
                item["speaker"] = seg["speaker"]
            out.append(item)
    return out


def _run_engine(engine: str, wav: Path, settings: Settings, vocab: list[str]) -> list[dict]:
    import transcriber
    if engine == "gemini":
        args = SimpleNamespace(model=settings.models.stt, language=settings.language, diarize=False,
                               vocab=",".join(vocab), chunk_sec=600, retries=settings.gemini_retries)
        return transcriber.transcribe_gemini(wav, args)["segments"]
    if engine == "whisper-local":
        if not whisper_available():
            raise RuntimeError("openai-whisper가 설치되어 있지 않습니다 (requirements-whisper.txt).")
        args = SimpleNamespace(model=settings.whisper_model, language=settings.language,
                               initial_prompt=transcriber.DEFAULT_INITIAL_PROMPT)
        raw = transcriber.transcribe_whisper_local(wav, args)["segments"]
        kept, dropped = transcriber.drop_hallucinations(raw, args.initial_prompt)
        if dropped:
            log.info("환각 의심 %d개 제외", len(dropped))
        return kept
    raise ValueError(engine)


def transcribe_clip(wav: Path, sha1: str, settings: Settings, cache_dir: Path, vocab: list[str] | None = None,
                    cancel: threading.Event | None = None) -> dict:
    """{"segments": [...클립 초], "silences": [(s, e)], "engine": "gemini:모델", "warnings": [...]}"""
    import transcriber
    vocab = vocab or []
    duration = wav_duration(wav)
    warnings: list[str] = []
    cache_dir.mkdir(parents=True, exist_ok=True)
    for engine in engine_chain(settings):
        if cancel is not None and cancel.is_set():
            raise Canceled("사용자가 작업을 취소했습니다.")
        model = {"gemini": settings.models.stt, "whisper-local": settings.whisper_model}.get(engine, "-")
        vocab_key = hashlib.sha1(",".join(vocab).encode("utf-8")).hexdigest()[:8]
        cache = cache_dir / f"{sha1[:20]}_{engine}_{model}_{settings.language}_{vocab_key}.json"
        if engine == "energy":
            raw, silences = speech_regions(wav)
            return {"segments": raw, "silences": silences, "engine": "energy",
                    "warnings": warnings + ["받아쓰기 엔진을 쓸 수 없어 말소리 구간만 찾았습니다 (자막 없음)."]}
        if cache.exists():
            raw = json.loads(cache.read_text(encoding="utf-8"))
        else:
            try:
                raw = _run_engine(engine, wav, settings, vocab)
            except Exception as error:
                text = str(error)
                if "429" in text or "RESOURCE_EXHAUSTED" in text:
                    text = "Gemini 받아쓰기 사용 한도를 다 썼습니다 (무료 키는 하루 25회)."
                warnings.append(f"{engine} 받아쓰기 실패 → 다음 엔진 사용: {text[:200]}")
                log.warning("받아쓰기 %s 실패: %s", engine, text[:300])
                continue
            cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        segments = transcriber.clean_segments(raw, duration)
        silences, _ = transcriber.detect_silences(wav, MIN_SILENCE)
        if any(s["words"] for s in segments):
            segments = split_into_sentences(transcriber.refine_with_silence(segments, silences))
        segments = [s for s in segments if s["end"] - s["start"] > 0.05]
        return {"segments": segments, "silences": silences, "engine": f"{engine}:{model}", "warnings": warnings}
    raw, silences = speech_regions(wav)
    return {"segments": raw, "silences": silences, "engine": "energy", "warnings": warnings}


def levels(wav: Path) -> np.ndarray:
    import transcriber
    return transcriber.frame_levels(wav)
