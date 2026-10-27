"""받아쓰기 명령 (권용관): 여러 클립을 촬영 시각 순으로 정렬해 받아쓰고 전체 타임라인 기준 결과를 만든다.

    vibecut transcribe --input ./raw_clips --out transcript.json
    vibecut transcribe --input a.mp4 b.mp4 --model small
    vibecut transcribe --input ./raw_clips --engine gemini --out transcript_gemini.json
    vibecut transcribe --input ./raw_clips --dry-run      # 정렬·오디오 추출만

clip_id·offset이 장면 분석(vibecut scenes) 결과와 같아서 4단 트리에서 장면 목록과 바로 합칠 수 있다.
결과: transcript.json (문장·단어 시각, 환각 의심 제외 목록, 검증 경고) + transcript.md (읽기용 표)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from ..ai.client import GeminiClient
from ..analysis.audio import detect_silences
from ..analysis.stt.engines import GeminiSttOptions, WhisperOptions, transcribe_gemini, transcribe_whisper_local
from ..analysis.stt.postprocess import clean_segments, drop_hallucinations, refine_with_silence
from ..domain.text import squash
from ..media.convert import extract_audio
from ..settings import env, load_settings
from .clips import collect_inputs, fmt_time, order_clips, print_clip_table

EPS = 0.01  # 검증 허용 오차(초). clips[].offset이 소수 2자리로 저장되는 만큼
MAX_WORD_SEC = 3.0  # 단어 하나가 이보다 길면 시각 오류로 보고 경고
DEFAULT_MODELS = {
    "whisper-local": env("WHISPER_MODEL", "medium"),
    "gemini": "gemini-3.5-transcribe",
}


def _engine(args: argparse.Namespace):
    """--engine 값 → (wav → {"segments", "usage"}) 함수."""
    if args.engine == "gemini":
        settings = load_settings(ai_mode="live", gemini_retries=args.retries)
        if not settings.api_key:
            sys.exit("Gemini API 키가 없습니다. GEMINI_API_KEY 환경변수나 .env를 확인하세요.")
        client = GeminiClient(settings)
        options = GeminiSttOptions(model=args.model, language=args.language, diarize=args.diarize,
                                   vocab=tuple(v.strip() for v in args.vocab.split(",") if v.strip()),
                                   chunk_sec=args.chunk_sec)
        return lambda wav: transcribe_gemini(wav, client, options)
    options = WhisperOptions(model=args.model, language=args.language, initial_prompt=args.initial_prompt)
    return lambda wav: transcribe_whisper_local(wav, options)


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
        if words and squash(s["text"]) != squash("".join(w["word"] for w in words)):
            problems.append(f"{sid}: text와 words 불일치")
    return problems


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


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--input", nargs="+", required=True, help="클립 파일들 또는 폴더")
    ap.add_argument("--out", default="transcript.json")
    ap.add_argument("--engine", default="whisper-local", choices=sorted(DEFAULT_MODELS))
    ap.add_argument("--model", default=None,
                    help="whisper-local: tiny/base/small/medium/large-v3 (기본 medium) / "
                         "gemini: 기본 gemini-3.5-transcribe")
    ap.add_argument("--language", default="ko")
    ap.add_argument("--initial-prompt", default=None,
                    help="whisper-local 전용 안내 문구 (기본: 설정의 WHISPER_INITIAL_PROMPT)")
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


def run(args: argparse.Namespace) -> int:
    args.model = args.model or DEFAULT_MODELS[args.engine]
    if args.initial_prompt is None:
        args.initial_prompt = load_settings(api_key=None).whisper_prompt

    files = collect_inputs(args.input)
    if not files:
        sys.exit("영상 파일을 찾지 못했습니다.")
    clips = order_clips(files)
    print_clip_table(clips)

    cache = Path(args.cache)
    cache.mkdir(exist_ok=True)
    transcribe = None if args.dry_run else _engine(args)

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
                # 빈 결과로 넘어가면 '말이 없는 클립'처럼 보이므로 멈춘다.
                # 끝난 클립은 캐시에 있어 다시 돌리면 이어서 한다.
                sys.exit(f"\n받아쓰기 실패 ({c['file'].name}): {e}\n"
                         "끝난 클립은 캐시에 저장됐습니다. 원인을 해결한 뒤 같은 명령으로 다시 실행하세요.")
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
        return 0

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
    return 0
