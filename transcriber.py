"""
VIBE CUT 1-2 소리 갈래: 받아쓰기 (문장 + 단어 단위 타임스탬프)

여러 클립을 scene_analyzer와 같은 규칙(촬영 시각 순)으로 정렬하고, 클립마다
16kHz 모노 WAV를 뽑아 받아쓰기한 뒤 문장(세그먼트)과 단어의 시각을
전체 타임라인 기준 초로 바꾼다. clip_id·offset이 scenes.json과 같아서
4단 트리(1-3)에서 장면 목록과 바로 합칠 수 있다.

사용 예:
    python transcriber.py --input ./raw_clips --out transcript.json
    python transcriber.py --input a.mp4 b.mp4 --model small
    python transcriber.py --input ./raw_clips --dry-run      # 정렬·오디오 추출만

필요: Python 3.10+, openai-whisper, imageio-ffmpeg(또는 PATH의 ffmpeg), moviepy
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 클립 수집·길이/촬영 시각 읽기는 scene_analyzer와 같은 함수를 쓴다 (정렬 결과가 같아야 함)
from scene_analyzer import _FFMPEG, collect_inputs, fmt_time, probe, run

DEFAULT_INITIAL_PROMPT = os.getenv(
    "WHISPER_INITIAL_PROMPT",
    "다음은 자연스러운 한국어 영상 자막입니다. 고유명사, 제품명, 숫자와 단위를 정확히 표기하세요.",
)
EPS = 0.01  # 검증 허용 오차(초). clips[].offset이 소수 2자리로 저장되는 만큼
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
# 엔진은 "클립 기준 초"의 원본 세그먼트 리스트를 돌려준다.
#   [{"start", "end", "text", "words": [{"word", "start", "end", "probability"}]}]
# 비교 실험(계획서 Step 3)용 엔진은 같은 모양으로 ENGINES에 추가한다.

_whisper_models = {}


def transcribe_whisper_local(wav: Path, args) -> list[dict]:
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
    return [{
        "start": s["start"], "end": s["end"], "text": s["text"],
        "words": s.get("words", []),
        "avg_logprob": s.get("avg_logprob"), "no_speech_prob": s.get("no_speech_prob"),
    } for s in result["segments"]]


ENGINES = {
    "whisper-local": transcribe_whisper_local,
}


# ---------------------------------------------------------------- 결과 정리·검증

def clean_segments(raw: list, duration: float) -> list[dict]:
    """엔진 출력을 믿지 않고 코드로 정리한다 (클립 기준 초).
    - 단어 앞뒤 공백 제거, 빈 단어·시각 없는 단어 제거
    - 모든 시각을 0~duration으로 자르기
    - 세그먼트 경계를 넘어서도 단어 시각이 줄어들지 않게(단조 증가) 맞추기
    - 단어가 있으면 세그먼트 start/end를 첫 단어 시작·마지막 단어 끝으로 맞추기
    - 내용 없는 세그먼트 제거, 시작 순 정렬
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
        segs.append({"start": st, "end": max(st, en), "text": text, "words": words})

    segs.sort(key=lambda x: x["start"])
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

def detect_silences(wav: Path, noise_db: float, min_sec: float, duration: float) -> list[tuple[float, float]]:
    """FFmpeg silencedetect로 무음 구간 [(start, end), ...]을 찾는다 (클립 기준 초)."""
    r = subprocess.run(
        [_FFMPEG, "-hide_banner", "-nostats", "-i", str(wav),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_sec}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return parse_silences(r.stderr, duration)


def parse_silences(log: str, duration: float) -> list[tuple[float, float]]:
    silences, start = [], None
    for kind, value in re.findall(r"silence_(start|end): (-?[\d.]+)", log):
        if kind == "start":
            start = max(0.0, float(value))
        elif start is not None:
            silences.append((start, min(float(value), duration)))
            start = None
    if start is not None:                       # 파일이 무음으로 끝나면 end가 안 찍힌다
        silences.append((start, duration))
    return silences


def refine_with_silence(segs: list[dict], silences: list[tuple[float, float]], reach: float = 0.3) -> list[dict]:
    """무음 경계에 단어 경계를 맞춘다 (clean_segments 결과를 받아 제자리에서 고친다).
    - 단어 시작이 무음 안에 있으면 → 무음이 끝나는 시점으로 미룬다
    - 단어 끝이 무음 안에 있으면   → 무음이 시작하는 시점으로 당긴다
    - 단어 시작 직전(reach초 이내)에 무음이 끝나면 → 그때부터 말한 것이므로 시작을 당긴다
    - 단어 끝 직후(reach초 이내)에 무음이 시작하면 → 그때까지 말한 것이므로 끝을 늘린다
    앞뒤 단어를 넘어서지 않으므로 단어 시각 순서는 유지된다."""
    words = [w for s in segs for w in s["words"]]
    for i, w in enumerate(words):
        prev_end = words[i - 1]["end"] if i else 0.0
        next_start = words[i + 1]["start"] if i + 1 < len(words) else float("inf")
        for s, e in silences:
            if s <= w["start"] < e:
                w["start"] = min(e, w["end"])
            elif prev_end <= e < w["start"] <= e + reach:
                w["start"] = e
            if s < w["end"] <= e:
                w["end"] = max(s, w["start"])
            elif w["end"] < s <= min(w["end"] + reach, next_start):
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
        })
    return out


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


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
    lines = [f"# 받아쓰기 ({m['engine']}, {m['model']}, {refine}, {m['elapsed_sec']}초)", "",
             "| 세그먼트 | 클립 | 시작 | 끝 | 문장 | 단어 수 | 확신 낮은 단어 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for s in result["segments"]:
        low = [w["word"] for w in s["words"] if w.get("probability", 1.0) < low_prob]
        lines.append(f"| {s['seg_id']} | {s['clip_id']} | {fmt_time(s['start'])} | {fmt_time(s['end'])} | "
                     f"{s['text']} | {len(s['words'])} | {', '.join(low)} |")
    if result["warnings"]:
        lines += ["", "## 검증 경고", ""] + [f"- {p}" for p in result["warnings"]]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- 메인

def main():
    ap = argparse.ArgumentParser(description="VIBE CUT 받아쓰기 (단어 단위 타임스탬프)")
    ap.add_argument("--input", nargs="+", required=True, help="클립 파일들 또는 폴더")
    ap.add_argument("--out", default="transcript.json")
    ap.add_argument("--engine", default="whisper-local", choices=sorted(ENGINES))
    ap.add_argument("--model", default=os.getenv("WHISPER_MODEL", "medium"),
                    help="whisper-local 모델 (tiny/base/small/medium/large-v3)")
    ap.add_argument("--language", default="ko")
    ap.add_argument("--initial-prompt", default=DEFAULT_INITIAL_PROMPT)
    ap.add_argument("--no-refine", action="store_true", help="무음 기준 단어 경계 보정을 끔 (비교용)")
    ap.add_argument("--silence-db", type=float, default=-35.0, help="이보다 작은 소리를 무음으로 봄")
    ap.add_argument("--min-silence", type=float, default=0.25, help="이보다 짧은 무음은 무시 (초)")
    ap.add_argument("--cache", default=".vibecut_cache")
    ap.add_argument("--refresh", action="store_true", help="받아쓰기 캐시 무시하고 다시 실행")
    ap.add_argument("--dry-run", action="store_true", help="정렬·오디오 추출만 하고 받아쓰기는 안 함")
    args = ap.parse_args()

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

    segments, t0 = [], time.time()
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
            raw = json.loads(raw_cache.read_text(encoding="utf-8"))
        else:
            print("받아쓰기…", end=" ", flush=True)
            raw = transcribe(wav, args)
            raw_cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        segs = clean_segments(raw, c["duration"])
        if not args.no_refine:
            segs = refine_with_silence(segs, detect_silences(wav, args.silence_db, args.min_silence, c["duration"]))
        segs = globalize(segs, c)
        segments += segs
        print(f"세그먼트 {len(segs)}개, 단어 {sum(len(s['words']) for s in segs)}개")

    if args.dry_run:
        return

    for i, s in enumerate(segments, 1):
        s["seg_id"] = f"t{i:04d}"

    result = {
        "meta": {
            "engine": args.engine, "model": args.model, "language": args.language,
            "refine": None if args.no_refine else {"silence_db": args.silence_db, "min_silence": args.min_silence},
            "elapsed_sec": round(time.time() - t0, 1),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
        "clips": [{"id": c["id"], "file": c["file"].name, "duration": round(c["duration"], 2),
                   "offset": round(c["offset"], 2), "has_audio": c["has_audio"]} for c in clips],
        "segments": [{k: s[k] for k in ("seg_id", "clip_id", "start", "end", "clip_start", "clip_end",
                                         "text", "words")} for s in segments],
    }
    result["warnings"] = validate_transcript(result)

    out = Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(result, out.with_suffix(".md"))
    print(f"\n완료: {out}, {out.with_suffix('.md')} "
          f"(세그먼트 {len(segments)}개, {result['meta']['elapsed_sec']}초, 경고 {len(result['warnings'])}건)")


if __name__ == "__main__":
    main()
