"""받아쓰기 엔진. 모두 '클립 초'의 원본 세그먼트를 돌려준다:
    [{"start", "end", "text", "words": [{"word", "start", "end", "probability"?}], "speaker"?}]

    whisper-local  로컬 openai-whisper (선택 설치: pip install -e ".[whisper]")
    gemini         Gemini 받아쓰기 전용 모델 (ai.client.transcribe_audio). 긴 오디오는 무음 지점에서 나눠 보낸다
    energy         받아쓰기 없이 음량으로 말소리 구간만 찾는다 (오프라인 최후 수단, 글자 없음)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ...ai.client import GeminiClient
from ...media.convert import cut_audio
from ..audio import (
    FRAME_SEC,
    Silence,
    auto_threshold,
    detect_silences,
    find_silences,
    frame_levels,
    read_samples,
    wav_duration,
)

log = logging.getLogger("vibecut.analysis.stt")

SENTENCE_END = re.compile(r"[.?!…。？！]$")
MIN_SILENCE = 0.25       # 이보다 짧은 쉼은 무음으로 보지 않는다 (초)


@dataclass(frozen=True)
class GeminiSttOptions:
    model: str
    language: str = "ko"
    diarize: bool = False
    vocab: tuple[str, ...] = ()
    chunk_sec: float = 300


@dataclass(frozen=True)
class WhisperOptions:
    model: str
    language: str = "ko"
    initial_prompt: str = ""


# ---------------------------------------------------------------- whisper-local

_whisper_models: dict = {}


def transcribe_whisper_local(wav: Path, options: WhisperOptions) -> dict:
    import torch
    import whisper

    if options.model not in _whisper_models:
        log.info("Whisper %s 모델 로딩", options.model)
        _whisper_models[options.model] = whisper.load_model(options.model)
    # 파일 경로를 넘기면 whisper가 시스템 ffmpeg를 다시 불러 PATH에 ffmpeg가 없는 PC에서 실패한다
    # (imageio-ffmpeg만 있는 경우). 이미 16kHz 모노 WAV이므로 배열로 읽어 바로 넘긴다.
    audio, _sr = read_samples(wav)
    result = _whisper_models[options.model].transcribe(
        audio,
        language=options.language,
        task="transcribe",
        initial_prompt=options.initial_prompt or None,
        temperature=0,
        beam_size=5,
        best_of=5,
        condition_on_previous_text=True,
        word_timestamps=True,
        fp16=torch.cuda.is_available(),
        verbose=None,
    )
    return {"segments": [{
        "start": s["start"], "end": s["end"], "text": s["text"],
        "words": s.get("words", []),
        "avg_logprob": s.get("avg_logprob"), "no_speech_prob": s.get("no_speech_prob"),
    } for s in result["segments"]], "usage": None}


# ---------------------------------------------------------------- gemini

def offset_sec(value) -> float | None:
    """API의 duration 문자열 "1.100s" → 1.1"""
    if value is None:
        return None
    try:
        return float(str(value).rstrip("s"))
    except ValueError:
        return None


def split_sentences(words: list[dict], max_gap: float = 1.5) -> list[list[dict]]:
    """단어 목록을 문장으로 나눈다: 문장부호로 끝나는 단어 뒤, 또는 max_gap초 이상 쉰 곳."""
    groups, cur = [], []
    for w in words:
        if cur and w["start"] - cur[-1]["end"] >= max_gap:
            groups.append(cur)
            cur = []
        cur.append(w)
        if SENTENCE_END.search(w["word"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def parse_gemini_response(resp: dict, offset: float, chunk_end: float) -> list[dict]:
    """generateContent 응답 → 원본 세그먼트 리스트 (offset만큼 시각을 민다).
    단어 시각이 없으면 조각 전체를 한 세그먼트로 둔다."""
    segs = []
    for cand in (resp.get("candidates") or [])[:1]:
        for part in (cand.get("content") or {}).get("parts") or []:
            at = part.get("audioTranscription")
            if not at:
                continue
            words = []
            for w in at.get("words") or []:
                st, en = offset_sec(w.get("startOffset")), offset_sec(w.get("endOffset"))
                if st is None or en is None:
                    continue
                words.append({"word": w.get("word", ""), "start": st + offset, "end": en + offset})
            extra = {"speaker": at["speakerLabel"]} if at.get("speakerLabel") else {}
            if not words:
                if str(at.get("text", "")).strip():
                    segs.append({"start": offset, "end": chunk_end, "text": at["text"], "words": [], **extra})
                continue
            for group in split_sentences(words):
                segs.append({"start": group[0]["start"], "end": group[-1]["end"],
                             "text": " ".join(w["word"] for w in group), "words": group, **extra})
    return segs


def choose_split_points(db: np.ndarray, chunk_sec: float, search_sec: float = 30.0,
                        frame_sec: float = FRAME_SEC) -> list[float]:
    """조각이 chunk_sec를 넘지 않게 자를 지점을 고른다. 목표 지점 앞 search_sec 안에서 가장 긴 무음의
    가운데를 고르고, 무음이 없으면 목표 지점에서 그냥 자른다 (말 도중에 잘리는 것을 줄이기 위해)."""
    total = len(db) * frame_sec
    if total <= chunk_sec:
        return []
    silences = find_silences(db, 0.2, auto_threshold(db), frame_sec)
    points, cursor = [], 0.0
    while total - cursor > chunk_sec:
        target = cursor + chunk_sec
        near = [(e - s, (s + e) / 2) for s, e in silences
                if target - search_sec <= (s + e) / 2 <= target and (s + e) / 2 > cursor + 1]
        cut = round(max(near)[1] if near else target, 3)
        points.append(cut)
        cursor = cut
    return points


def transcribe_gemini(wav: Path, client: GeminiClient, options: GeminiSttOptions,
                      levels: np.ndarray | None = None) -> dict:
    """긴 오디오는 inline 요청 크기(약 20MB) 안에 들도록 무음 지점에서 나눠 FLAC으로 보낸다.
    levels: 이미 잰 frame_levels 결과 (없으면 여기서 잰다)."""
    points = choose_split_points(levels if levels is not None else frame_levels(wav), options.chunk_sec)
    bounds = [0.0] + points + [wav_duration(wav)]
    segments, usage = [], {"requests": 0, "audio_tokens": 0, "total_tokens": 0}
    for i, (st, en) in enumerate(zip(bounds, bounds[1:])):
        flac = wav.with_name(f"{wav.stem}_part{i}.flac")
        cut_audio(wav, flac, st, en)
        try:
            resp = client.transcribe_audio(flac, model=options.model, language=options.language,
                                           diarize=options.diarize, vocab=options.vocab)
        except Exception as error:
            error.chunk = (i + 1, len(bounds) - 1)      # 몇 번째 조각에서 실패했는지 (경고 문구용)
            raise
        finally:
            flac.unlink(missing_ok=True)
        segments += parse_gemini_response(resp, st, en)
        meta = resp.get("usageMetadata") or {}
        usage["requests"] += 1
        usage["total_tokens"] += meta.get("totalTokenCount", 0)
        usage["audio_tokens"] += sum(d.get("tokenCount", 0) for d in meta.get("promptTokensDetails", [])
                                     if d.get("modality") == "AUDIO")
    usage["chunks"] = [round(b, 3) for b in bounds]
    return {"segments": segments, "usage": usage}


# ---------------------------------------------------------------- energy

def speech_regions(wav: Path, levels: np.ndarray | None = None) -> tuple[list[dict], list[Silence]]:
    """받아쓰기 없이 말소리가 있는 구간만 찾는다 (오프라인 최후 수단). 글자는 비워 둔다."""
    duration = wav_duration(wav)
    silences, _ = detect_silences(levels if levels is not None else wav, MIN_SILENCE)
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
