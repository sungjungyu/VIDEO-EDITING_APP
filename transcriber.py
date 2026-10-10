"""
VIBE CUT 1-2 소리 갈래: 받아쓰기 (문장 + 단어 단위 타임스탬프)

여러 클립을 scene_analyzer와 같은 규칙(촬영 시각 순)으로 정렬하고, 클립마다
16kHz 모노 WAV를 뽑아 받아쓰기한 뒤 문장(세그먼트)과 단어의 시각을
전체 타임라인 기준 초로 바꾼다. clip_id·offset이 scenes.json과 같아서
4단 트리(1-3)에서 장면 목록과 바로 합칠 수 있다.

사용 예:
    python transcriber.py --input ./raw_clips --out transcript.json
    python transcriber.py --input a.mp4 b.mp4 --model small
    python transcriber.py --input ./raw_clips --engine gemini --out transcript_gemini.json
    python transcriber.py --input ./raw_clips --dry-run      # 정렬·오디오 추출만

필요: Python 3.10+, openai-whisper, imageio-ffmpeg(또는 PATH의 ffmpeg), moviepy
gemini 엔진: httpx(google-genai 설치 시 함께 설치됨), API 키(GEMINI_API_KEY 또는 gemini_key.txt)
"""

import argparse
import json
import os
import re
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

# 클립 수집·길이/촬영 시각 읽기는 scene_analyzer와 같은 함수를 쓴다 (정렬 결과가 같아야 함)
from scene_analyzer import collect_inputs, fmt_time, probe, run

DEFAULT_INITIAL_PROMPT = os.getenv(
    "WHISPER_INITIAL_PROMPT",
    "다음은 자연스러운 한국어 영상 자막입니다. 고유명사, 제품명, 숫자와 단위를 정확히 표기하세요.",
)
EPS = 0.01  # 검증 허용 오차(초). clips[].offset이 소수 2자리로 저장되는 만큼
FRAME_SEC = 0.05  # 무음 감지용 음량 측정 단위(초)
MAX_WORD_SEC = 3.0  # 단어 하나가 이보다 길면 시각 오류로 보고 경고
NO_AUDIO_MARKERS = ("does not contain any stream", "matches no streams", "Output file is empty")


# ---------------------------------------------------------------- 클립 정렬

def order_clips(files: list[Path]) -> list[dict]:
    """촬영 시각 → 파일명 순으로 정렬하고 c01, c02… id와 전체 타임라인 offset을 붙인다.
    scene_analyzer.main()의 정렬 규칙과 반드시 같아야 한다."""
    clips = [{"file": p, **probe(p)} for p in files]
    clips.sort(key=lambda c: (c["created"], c["file"].name))
    offset = 0.0
    for i, c in enumerate(clips, 1):
        c["id"], c["offset"] = f"c{i:02d}", offset
        offset += c["duration"]
    return clips


# ---------------------------------------------------------------- 오디오 추출

def extract_audio(src: Path, dst: Path) -> bool:
    """16kHz 모노 PCM WAV로 뽑는다. 오디오 트랙이 없으면 False."""
    if dst.exists() and dst.stat().st_size > 0:
        return True
    try:
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)])
    except RuntimeError as e:
        if any(m in str(e) for m in NO_AUDIO_MARKERS):
            dst.unlink(missing_ok=True)
            return False
        raise
    return True


# ---------------------------------------------------------------- 받아쓰기 엔진
# 엔진은 {"segments": [...], "usage": {...} | None}을 돌려준다. segments는 "클립 기준 초"의 원본 세그먼트:
#   [{"start", "end", "text", "words": [{"word", "start", "end", "probability"?}], "speaker"?}]
# 새 엔진(예: Whisper API)은 같은 모양으로 만들어 ENGINES에 추가한다.

_whisper_models = {}


def transcribe_whisper_local(wav: Path, args) -> dict:
    import torch
    import whisper

    if args.model not in _whisper_models:
        print(f"\n  Whisper {args.model} 모델 로딩…", end=" ", flush=True)
        _whisper_models[args.model] = whisper.load_model(args.model)
    result = _whisper_models[args.model].transcribe(
        str(wav),
        language=args.language,
        task="transcribe",
        initial_prompt=args.initial_prompt or None,
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


# Gemini 받아쓰기 전용 모델. google-genai SDK(2.13)는 응답의 audioTranscription 필드를 버리므로 REST로 직접 부른다.
# 설정(generationConfig.audioTranscriptionConfig)은 공식 API 스키마 기준:
#   wordTimestamp(단어 시각), diarization(화자 구분), customVocabulary(고유명사 힌트), mode(VERBATIM|SMART)
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
SENTENCE_END = re.compile(r"[.?!…。？！]$")


def load_gemini_key() -> str:
    """config.py와 같은 순서(GEMINI_API_KEY → gemini_key.txt)로 키를 읽는다.
    config.py는 이모지를 print해서 한글(cp949) 콘솔에서 오류가 나므로 출력은 버린다."""
    import contextlib
    import io
    from config import config
    with contextlib.redirect_stdout(io.StringIO()):
        key = config.load_api_key()
    if not key:
        raise RuntimeError("Gemini API 키가 없습니다. GEMINI_API_KEY 환경변수 또는 gemini_key.txt를 확인하세요.")
    return key


def _offset_sec(value) -> float | None:
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
                st, en = _offset_sec(w.get("startOffset")), _offset_sec(w.get("endOffset"))
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


def _gemini_request(audio: Path, args, key: str) -> dict:
    import base64
    import httpx

    cfg = {"wordTimestamp": True, "mode": "VERBATIM"}
    if args.language:
        cfg["languageCodes"] = [args.language]
    if args.diarize:
        cfg["diarization"] = True
    if args.vocab:
        cfg["customVocabulary"] = [v.strip() for v in args.vocab.split(",") if v.strip()]
    body = {"contents": [{"role": "user", "parts": [{"inline_data": {
                "mime_type": "audio/flac", "data": base64.b64encode(audio.read_bytes()).decode()}}]}],
            "generationConfig": {"temperature": 0, "audioTranscriptionConfig": cfg}}   # 같은 입력 → 같은 결과
    last = None
    for attempt in range(args.retries + 1):
        try:
            r = httpx.post(GEMINI_URL.format(model=args.model), headers={"x-goog-api-key": key},
                           json=body, timeout=600)
        except httpx.HTTPError as e:
            last = f"네트워크 오류: {e}"
        else:
            if r.status_code == 200:
                return r.json()
            try:
                msg = r.json().get("error", {}).get("message", "")
            except ValueError:
                msg = r.text[:300]
            last = f"Gemini 오류 {r.status_code}: {msg}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(last)


def transcribe_gemini(wav: Path, args) -> dict:
    """긴 오디오는 inline 요청 크기(약 20MB) 안에 들도록 무음 지점에서 나눠 FLAC으로 보낸다."""
    key = load_gemini_key()
    points = choose_split_points(frame_levels(wav), args.chunk_sec)
    with wave.open(str(wav)) as w:
        total = w.getnframes() / w.getframerate()
    bounds = [0.0] + points + [total]
    segments, usage = [], {"requests": 0, "audio_tokens": 0, "total_tokens": 0}
    for i, (st, en) in enumerate(zip(bounds, bounds[1:])):
        flac = wav.with_name(f"{wav.stem}_part{i}.flac")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ss", f"{st:.3f}", "-to", f"{en:.3f}",
             "-c:a", "flac", str(flac)])
        try:
            resp = _gemini_request(flac, args, key)
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


ENGINES = {
    "whisper-local": transcribe_whisper_local,
    "gemini": transcribe_gemini,
}
DEFAULT_MODELS = {
    "whisper-local": os.getenv("WHISPER_MODEL", "medium"),
    "gemini": "gemini-3.5-transcribe",
}


# ---------------------------------------------------------------- 결과 정리·검증

def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _bigram_overlap(text: str, ref: str) -> float:
    """text의 글자 2개 묶음 중 ref에도 있는 비율 (0~1). 문장부호·공백은 무시."""
    a, b = re.sub(r"[\W_]+", "", text), re.sub(r"[\W_]+", "", ref)
    grams = [a[i:i + 2] for i in range(len(a) - 1)]
    if not grams:
        return 0.0
    ref_grams = {b[i:i + 2] for i in range(len(b) - 1)}
    return sum(g in ref_grams for g in grams) / len(grams)


def hallucination_reason(seg: dict, initial_prompt: str = "") -> str | None:
    """말소리가 없는데 Whisper가 지어낸 세그먼트면 이유를, 아니면 None을 돌려준다 (원본 세그먼트 기준).
    실측: 소음만 있는 10초 클립에서 initial_prompt 문구를 섞어 그대로 출력함
    (no_speech_prob 0.59, 평균 단어 확률 0.17. 실제 말소리는 소음이 있어도 0.93)."""
    text = str(seg.get("text", ""))
    if initial_prompt and len(_squash(text)) >= 6 and _bigram_overlap(text, initial_prompt) >= 0.6:
        return "안내 문구(initial_prompt) 반복"
    probs = [float(w["probability"]) for w in seg.get("words") or [] if w.get("probability") is not None]
    no_speech = seg.get("no_speech_prob")
    if probs and no_speech is not None:
        mean_p = sum(probs) / len(probs)
        if mean_p < 0.4 and no_speech >= 0.4:
            return f"말소리 아님 (단어 확률 {mean_p:.2f}, 무음 확률 {no_speech:.2f})"
    return None


def drop_hallucinations(raw: list, initial_prompt: str = "") -> tuple[list, list]:
    """(남길 세그먼트, 버린 세그먼트)로 나눈다. 버린 것도 결과 파일에 이유와 함께 남긴다."""
    kept, dropped = [], []
    for s in raw or []:
        reason = hallucination_reason(s, initial_prompt)
        if reason:
            dropped.append({"start": s.get("start"), "end": s.get("end"),
                            "text": str(s.get("text", "")).strip(), "reason": reason})
        else:
            kept.append(s)
    return kept, dropped


def clean_segments(raw: list, duration: float) -> list[dict]:
    """엔진 출력을 믿지 않고 코드로 정리한다 (클립 기준 초).
    - 단어 앞뒤 공백 제거, 빈 단어·시각 없는 단어 제거
    - 모든 시각을 0~duration으로 자르기
    - 세그먼트 경계를 넘어서도 단어 시각이 줄어들지 않게(단조 증가) 맞추기
    - 단어가 있으면 세그먼트 start/end를 첫 단어 시작·마지막 단어 끝으로 맞추기
    - 내용 없는 세그먼트 제거, 끝 시각 순 정렬
      (엔진은 문장 첫 단어의 시작을 크게 틀리는 경우가 있다. 실측: Gemini가 첫 단어 시작을 10초 앞당김,
       Whisper가 1.1초 앞당김. 시작 순으로 정렬하면 순서가 뒤바뀌어 앞 문장이 찌그러진다.)
    """
    def clamp(x: float) -> float:
        return max(0.0, min(x, duration))

    segs = []
    for s in raw or []:
        try:
            st, en = clamp(float(s.get("start", 0))), clamp(float(s.get("end", 0)))
        except (TypeError, ValueError):
            continue
        words = []
        for w in s.get("words") or []:
            text = str(w.get("word", "")).strip()
            if not text:
                continue
            try:
                ws, we = clamp(float(w["start"])), clamp(float(w["end"]))
            except (KeyError, TypeError, ValueError):
                continue
            word = {"word": text, "start": ws, "end": we}
            if w.get("probability") is not None:
                word["probability"] = round(float(w["probability"]), 3)
            words.append(word)
        text = str(s.get("text", "")).strip() or " ".join(w["word"] for w in words)
        if not text:
            continue
        seg = {"start": st, "end": max(st, en), "text": text, "words": words}
        if s.get("speaker"):
            seg["speaker"] = str(s["speaker"])
        segs.append(seg)

    segs.sort(key=lambda x: (x["end"], x["start"]))
    prev_end = 0.0
    for seg in segs:
        for w in seg["words"]:
            w["start"] = max(w["start"], prev_end)
            w["end"] = max(w["end"], w["start"])
            prev_end = w["end"]
        if seg["words"]:
            seg["start"], seg["end"] = seg["words"][0]["start"], seg["words"][-1]["end"]
        else:
            seg["start"] = max(seg["start"], prev_end)
            seg["end"] = max(seg["end"], seg["start"])
            prev_end = seg["end"]
    return segs


# ---------------------------------------------------------------- 무음 기준 단어 경계 보정
# Whisper 단어 시각은 문장 앞뒤에서 크게 틀린다 (실측: 첫 단어 시작이 앞 무음까지 최대 1.1초 당겨짐,
# 문장 끝이 뒤 무음까지 0.6초 늘어남, 말 시작보다 0.2초 늦게 시작해 앞소리가 잘림).
# 오디오에서 무음 구간을 직접 찾아, 무음 경계에 단어 경계를 맞춘다.
#
# 무음 기준을 고정값(-35dB 등)으로 두면 배경 소음이 있을 때 무음이 잘게 쪼개지거나 아예 안 잡힌다.
# 그래서 클립마다 음량 분포를 보고 기준을 자동으로 정한다:
#   배경 소음 = 하위 10% 음량, 말소리 = 상위 10% 음량, 기준 = 소음 + max(6dB, 둘 차이의 30%)


def frame_levels(wav: Path, frame_sec: float = FRAME_SEC) -> np.ndarray:
    """16bit 모노 WAV를 frame_sec 단위로 잘라 프레임별 음량(RMS, dB)을 돌려준다."""
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    n = int(sr * frame_sec)
    if len(x) < n:
        return np.zeros(0)
    x = x[: len(x) // n * n].reshape(-1, n)
    return 20 * np.log10(np.sqrt((x ** 2).mean(axis=1)) + 1e-10)


def auto_threshold(db: np.ndarray, ratio: float = 0.3, min_gap_db: float = 6.0, below_loud_db: float = 10.0) -> float:
    """쉬는 구간이 10%도 안 되게 계속 말하면 '하위 10%'가 말소리가 되어 기준이 말소리보다 높아지고
    전체가 무음으로 잡힌다. 그래서 기준은 말소리보다 최소 below_loud_db 아래로 제한한다."""
    floor = max(float(np.percentile(db, 10)), -70.0)
    loud = float(np.percentile(db, 90))
    return min(floor + max(min_gap_db, (loud - floor) * ratio), loud - below_loud_db)


def find_silences(db: np.ndarray, min_sec: float, threshold: float,
                  frame_sec: float = FRAME_SEC) -> list[tuple[float, float]]:
    """threshold보다 작은 프레임이 min_sec 이상 이어지는 구간 [(start, end), ...] (초)."""
    out, start = [], None
    for i, quiet in enumerate(np.append(db < threshold, False)):
        if quiet and start is None:
            start = i
        elif not quiet and start is not None:
            if (i - start) * frame_sec >= min_sec - 1e-9:
                out.append((round(start * frame_sec, 3), round(i * frame_sec, 3)))
            start = None
    return out


def detect_silences(wav: Path, min_sec: float,
                    noise_db: float | None = None) -> tuple[list[tuple[float, float]], float | None]:
    """무음 구간과 실제로 쓴 기준(dB)을 돌려준다. noise_db를 주면 자동 대신 그 값을 쓴다."""
    db = frame_levels(wav)
    if db.size == 0:
        return [], None
    threshold = noise_db if noise_db is not None else auto_threshold(db)
    return find_silences(db, min_sec, threshold), round(threshold, 1)


def refine_with_silence(segs: list[dict], silences: list[tuple[float, float]], reach: float = 0.3) -> list[dict]:
    """무음 경계에 단어 경계를 맞춘다 (clean_segments 결과를 받아 제자리에서 고친다).
    - 단어 시작이 무음 안에 있으면 → 무음이 끝나는 시점으로 미룬다
    - 단어 끝이 무음 안에 있으면   → 무음이 시작하는 시점으로 당긴다
    - 단어 시작 직전(reach초 이내)에 무음이 끝나면 → 그때부터 말한 것이므로 시작을 당긴다
    - 단어 끝 직후(reach초 이내)에 무음이 시작하면 → 그때까지 말한 것이므로 끝을 늘린다
    - 단어가 무음을 통째로 품고 있고 그 무음이 단어 앞쪽(reach초 이내)에 있으면 → 무음 뒤에서 시작한 것으로 본다
      (끝 쪽도 같은 방식. 실측: Gemini가 "오후에는"을 앞 문장 끝에 붙여 0.8초 무음까지 포함시킴)
    앞뒤 단어를 넘어서지 않으므로 단어 시각 순서는 유지된다.
    한 단어를 고치면 이웃 단어의 판단이 바뀔 수 있어 두 번 돌린다."""
    words = [w for s in segs for w in s["words"]]
    for _ in range(2):
        for i, w in enumerate(words):
            prev_end = words[i - 1]["end"] if i else 0.0
            next_start = words[i + 1]["start"] if i + 1 < len(words) else float("inf")
            for s, e in silences:
                if s <= w["start"] < e:
                    w["start"] = min(e, w["end"])
                elif prev_end <= e < w["start"] <= e + reach:
                    w["start"] = e
                elif w["start"] <= s and e < w["end"] and s - w["start"] <= reach:
                    w["start"] = e
                if s < w["end"] <= e:
                    w["end"] = max(s, w["start"])
                elif w["end"] < s <= min(w["end"] + reach, next_start):
                    w["end"] = s
                elif w["start"] < s and e <= w["end"] and w["end"] - e <= reach:
                    w["end"] = s
    for seg in segs:
        if seg["words"]:
            seg["start"], seg["end"] = seg["words"][0]["start"], seg["words"][-1]["end"]
    return segs


def globalize(segs: list[dict], clip: dict) -> list[dict]:
    """클립 기준 초 → 전체 타임라인 초. clip_start/clip_end는 클립 기준으로 남긴다."""
    off = clip["offset"]
    out = []
    for s in segs:
        out.append({
            "clip_id": clip["id"],
            "start": round(s["start"] + off, 3), "end": round(s["end"] + off, 3),
            "clip_start": round(s["start"], 3), "clip_end": round(s["end"], 3),
            "text": s["text"],
            "words": [{**w, "start": round(w["start"] + off, 3), "end": round(w["end"] + off, 3)}
                      for w in s["words"]],
            **({"speaker": s["speaker"]} if s.get("speaker") else {}),
        })
    return out


def validate_transcript(transcript: dict) -> list[str]:
    """transcript.json 규칙 검사. 문제 목록(빈 리스트면 통과)을 돌려준다.
    Gemini 교정 등으로 text를 바꾼 뒤에도 다시 돌려서 words와 어긋났는지 확인한다."""
    problems = []
    clips = {c["id"]: c for c in transcript.get("clips", [])}
    prev_end = 0.0
    for s in transcript.get("segments", []):
        sid = s.get("seg_id", "?")
        clip = clips.get(s.get("clip_id"))
        if clip is None:
            problems.append(f"{sid}: 없는 clip_id {s.get('clip_id')}")
        elif not (clip["offset"] - EPS <= s["start"] <= s["end"] <= clip["offset"] + clip["duration"] + EPS):
            problems.append(f"{sid}: 클립 범위 밖 ({s['start']}~{s['end']})")
        if s["start"] < prev_end - EPS:
            problems.append(f"{sid}: 앞 세그먼트와 겹침 ({s['start']} < {prev_end})")
        prev_end = max(prev_end, s["end"])
        words = s.get("words") or []
        if words and s["end"] - s["start"] < EPS:
            problems.append(f"{sid}: 길이 0 세그먼트")
        for w in words:
            if w["end"] - w["start"] > MAX_WORD_SEC:
                problems.append(f"{sid}: 비정상적으로 긴 단어 '{w['word']}' ({w['end'] - w['start']:.1f}초)")
        w_prev = s["start"]
        for w in words:
            if w["start"] < w_prev - EPS or w["end"] < w["start"]:
                problems.append(f"{sid}: 단어 시각 역전 '{w['word']}' ({w['start']}~{w['end']})")
            if not (s["start"] - EPS <= w["start"] and w["end"] <= s["end"] + EPS):
                problems.append(f"{sid}: 세그먼트 밖 단어 '{w['word']}'")
            w_prev = w["end"]
        if words and _squash(s["text"]) != _squash("".join(w["word"] for w in words)):
            problems.append(f"{sid}: text와 words 불일치")
    return problems


# ---------------------------------------------------------------- 다른 모듈로 넘기기

def to_subtitles(transcript: dict, clip_id: str | None = None) -> list[dict]:
    """media_engine `subtitles` / backend `SubtitleItem` 형식으로 변환한다.
    clip_id를 주면 그 클립만, 클립 기준 초로 돌려준다 (현재 단일 클립 렌더용).
    [{"start", "end", "text", "words": [{"word", "start", "end"}]}]"""
    out = []
    for s in transcript["segments"]:
        if clip_id is not None and s["clip_id"] != clip_id:
            continue
        # clips[].offset은 소수 2자리로 저장되므로, 세그먼트의 clip_start로 정확한 차이를 구한다
        off = s["start"] - s["clip_start"] if clip_id is not None else 0.0
        out.append({
            "start": round(s["start"] - off, 3), "end": round(s["end"] - off, 3),
            "text": s["text"],
            "words": [{"word": w["word"], "start": round(w["start"] - off, 3), "end": round(w["end"] - off, 3)}
                      for w in s.get("words") or []],
        })
    return out


def write_markdown(result: dict, path: Path, low_prob: float = 0.5):
    m = result["meta"]
    refine = "무음 보정" if m.get("refine") else "보정 없음"
    took = f"엔진 처리 {m['engine_sec']}초" if m.get("engine_sec") is not None else f"{m['elapsed_sec']}초"
    lines = [f"# 받아쓰기 ({m['engine']}, {m['model']}, {refine}, {took})", "",
             "| 세그먼트 | 클립 | 시작 | 끝 | 문장 | 단어 수 | 확신 낮은 단어 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for s in result["segments"]:
        low = [w["word"] for w in s["words"] if w.get("probability", 1.0) < low_prob]
        lines.append(f"| {s['seg_id']} | {s['clip_id']} | {fmt_time(s['start'])} | {fmt_time(s['end'])} | "
                     f"{s['text']} | {len(s['words'])} | {', '.join(low)} |")
    if result.get("dropped"):
        lines += ["", "## 환각 의심으로 제외한 세그먼트 (클립 안 초)", "",
                  "| 클립 | 시작 | 끝 | 문장 | 이유 |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {d['clip_id']} | {d['start']:.2f} | {d['end']:.2f} | {d['text']} | {d['reason']} |"
                  for d in result["dropped"]]
    if result["warnings"]:
        lines += ["", "## 검증 경고", ""] + [f"- {p}" for p in result["warnings"]]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- 메인

def main():
    ap = argparse.ArgumentParser(description="VIBE CUT 받아쓰기 (단어 단위 타임스탬프)")
    ap.add_argument("--input", nargs="+", required=True, help="클립 파일들 또는 폴더")
    ap.add_argument("--out", default="transcript.json")
    ap.add_argument("--engine", default="whisper-local", choices=sorted(ENGINES))
    ap.add_argument("--model", default=None,
                    help="whisper-local: tiny/base/small/medium/large-v3 (기본 medium) / gemini: 기본 gemini-3.5-transcribe")
    ap.add_argument("--language", default="ko")
    ap.add_argument("--initial-prompt", default=DEFAULT_INITIAL_PROMPT, help="whisper-local 전용 안내 문구")
    ap.add_argument("--vocab", default="", help="gemini 전용: 고유명사 힌트, 쉼표로 구분 (예: \"성수동,소금빵\")")
    ap.add_argument("--diarize", action="store_true", help="gemini 전용: 화자 구분 (segments[].speaker)")
    ap.add_argument("--chunk-sec", type=float, default=600, help="gemini 전용: 한 번에 보낼 최대 길이(초)")
    ap.add_argument("--retries", type=int, default=2, help="gemini 전용: 일시 오류 시 재시도 횟수")
    ap.add_argument("--no-refine", action="store_true", help="무음 기준 단어 경계 보정을 끔 (비교용)")
    ap.add_argument("--silence-db", type=float, default=None,
                    help="무음 기준(dB, RMS). 안 주면 클립마다 배경 소음을 보고 자동으로 정함")
    ap.add_argument("--min-silence", type=float, default=0.25, help="이보다 짧은 무음은 무시 (초)")
    ap.add_argument("--keep-hallucinations", action="store_true", help="환각 의심 세그먼트를 버리지 않음 (비교용)")
    ap.add_argument("--cache", default=".vibecut_cache")
    ap.add_argument("--refresh", action="store_true", help="받아쓰기 캐시 무시하고 다시 실행")
    ap.add_argument("--dry-run", action="store_true", help="정렬·오디오 추출만 하고 받아쓰기는 안 함")
    args = ap.parse_args()
    args.model = args.model or DEFAULT_MODELS[args.engine]

    files = collect_inputs(args.input)
    if not files:
        sys.exit("영상 파일을 찾지 못했습니다.")
    clips = order_clips(files)

    print(f"\n{'─'*60}")
    print(f"{'ID':>4}  {'파일명':<30}  {'촬영시각':<22}  {'길이':>6}")
    print(f"{'─'*60}")
    for c in clips:
        ts = datetime.fromtimestamp(c["created"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{c['id']:>4}  {c['file'].name:<30}  {ts:<22}  {fmt_time(c['duration']):>6}")
    print(f"{'─'*60}")
    print(f"총 {len(clips)}개, {fmt_time(sum(c['duration'] for c in clips))}\n")

    cache = Path(args.cache)
    cache.mkdir(exist_ok=True)
    transcribe = ENGINES[args.engine]

    segments, dropped, t0 = [], [], time.time()
    for c in clips:
        key = f"{c['file'].stem}_{c['file'].stat().st_size}"
        wav = cache / f"{key}_16k.wav"
        raw_cache = cache / f"{key}_{args.engine}_{args.model}_{args.language}.stt.json"
        print(f"[{c['id']}] {c['file'].name} ({fmt_time(c['duration'])}) 오디오…", end=" ", flush=True)
        c["has_audio"] = extract_audio(c["file"], wav)
        if not c["has_audio"]:
            print("오디오 트랙 없음, 건너뜀")
            continue
        if args.dry_run:
            print("완료 (dry-run)")
            continue
        if raw_cache.exists() and not args.refresh:
            print("받아쓰기(캐시)…", end=" ", flush=True)
            out = json.loads(raw_cache.read_text(encoding="utf-8"))
            if isinstance(out, list):                      # 이전 형식 캐시 (세그먼트 리스트만)
                out = {"segments": out, "usage": None, "engine_sec": None}
        else:
            print("받아쓰기…", end=" ", flush=True)
            t1 = time.time()
            try:
                out = transcribe(wav, args)
            except RuntimeError as e:
                # 빈 결과로 넘어가면 '말이 없는 클립'처럼 보이므로 멈춘다. 끝난 클립은 캐시에 있어 다시 돌리면 이어서 한다.
                sys.exit(f"\n받아쓰기 실패 ({c['file'].name}): {e}\n끝난 클립은 캐시에 저장됐습니다. 원인을 해결한 뒤 같은 명령으로 다시 실행하세요.")
            out["engine_sec"] = round(time.time() - t1, 1)
            raw_cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        c["engine_sec"], c["usage"] = out.get("engine_sec"), out.get("usage")
        raw, gone = out["segments"], []
        if not args.keep_hallucinations:
            prompt = args.initial_prompt if args.engine == "whisper-local" else ""
            raw, gone = drop_hallucinations(raw, prompt)
            dropped += [{"clip_id": c["id"], **d} for d in gone]
        segs = clean_segments(raw, c["duration"])
        if not args.no_refine:
            silences, c["silence_db"] = detect_silences(wav, args.min_silence, args.silence_db)
            segs = refine_with_silence(segs, silences)
        segs = globalize(segs, c)
        segments += segs
        print(f"세그먼트 {len(segs)}개, 단어 {sum(len(s['words']) for s in segs)}개"
              + (f", 환각 의심 {len(gone)}개 제외" if gone else ""))

    if args.dry_run:
        return

    for i, s in enumerate(segments, 1):
        s["seg_id"] = f"t{i:04d}"

    # 엔진 처리 시간·사용량 합계 (캐시를 써도 처음 받아쓴 때의 값으로 계산한다)
    done = [c for c in clips if c.get("has_audio")]
    engine_sec = (round(sum(c["engine_sec"] for c in done), 1)
                  if done and all(c.get("engine_sec") is not None for c in done) else None)
    usages = [c["usage"] for c in done if c.get("usage")]
    usage = ({k: sum(u.get(k, 0) for u in usages) for k in ("requests", "audio_tokens", "total_tokens")}
             if usages else None)

    result = {
        "meta": {
            "engine": args.engine, "model": args.model, "language": args.language,
            "refine": None if args.no_refine else {"silence_db": "auto" if args.silence_db is None else args.silence_db,
                                                   "min_silence": args.min_silence},
            "elapsed_sec": round(time.time() - t0, 1),
            "engine_sec": engine_sec,
            "usage": usage,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
        "clips": [{"id": c["id"], "file": c["file"].name, "duration": round(c["duration"], 2),
                   "offset": round(c["offset"], 2), "has_audio": c["has_audio"],
                   **({"silence_db": c["silence_db"]} if c.get("silence_db") is not None else {}),
                   **({"engine_sec": c["engine_sec"]} if c.get("engine_sec") is not None else {})}
                  for c in clips],
        "segments": [{k: s[k] for k in ("seg_id", "clip_id", "start", "end", "clip_start", "clip_end",
                                         "text", "words", "speaker") if k in s} for s in segments],
        "dropped": dropped,
    }
    result["warnings"] = validate_transcript(result)

    out = Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(result, out.with_suffix(".md"))
    print(f"\n완료: {out}, {out.with_suffix('.md')} (세그먼트 {len(segments)}개, "
          f"환각 의심 제외 {len(dropped)}개, {result['meta']['elapsed_sec']}초, 경고 {len(result['warnings'])}건)")


if __name__ == "__main__":
    main()
