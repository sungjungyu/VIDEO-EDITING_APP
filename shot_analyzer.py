"""
VIBE CUT 1-2 화면 갈래 (세밀): 4단 트리의 L4 장면(3~7초) 분석 (Gemini API)

scene_analyzer.py(조경우)는 장소·활동이 바뀔 때만 나누고 10초 미만 변화는 합쳐서 장면 하나가 L2~L3 크기다.
4단 트리의 맨 아래 L4 장면은 "카운터 앞에서 메뉴판을 올려다본다" 같은 3~7초 화면 단위라서,
같은 방식(저해상도·무음 영상 → Gemini)으로 더 잘게 보고 장면마다 화면 설명·장소·행동·인물·화면 글자를 뽑는다.
화면 글자(간판·메뉴판·표지판)는 4단 트리를 만들 때 받아쓰기 보정의 근거로 쓴다.

- 클립 정렬·길이·촬영 시각은 transcriber.order_clips(= scene_analyzer와 같은 규칙)를 쓴다.
  → shots.json의 clips가 transcript.json과 같아서 scene_tree.py에서 바로 합칠 수 있다.
- 긴 클립은 --chunk-sec(기본 5분) 조각으로 나눠 보낸다. 조각이 짧을수록 Gemini가 말하는 시각이 정확하다.
- 장면 경계는 아직 거칠다 (1초에 1장만 본다). 문장 사이로 옮기고 3~7초로 다듬는 일은 scene_tree.py가 한다.
- 모든 시각은 전체 타임라인 기준 초 (clip_start/clip_end는 클립 안 초).

사용 예:
    python shot_analyzer.py --input ./raw_clips --out shots.json
    python shot_analyzer.py --input a.mp4 --model gemini-3.5-flash --resolution medium

필요: scene_analyzer와 같음 (Python 3.10+, imageio-ffmpeg, moviepy, google-genai, API 키)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ffmpeg 실행·시각 변환·JSON 꺼내기는 scene_analyzer 함수를 그대로 쓴다 (파일은 수정하지 않음)
from scene_analyzer import extract_json_array, fmt_time, run, to_seconds

DEFAULT_MODEL = os.getenv("SHOT_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODEL = os.getenv("SHOT_FALLBACK_MODEL", "gemini-3.5-flash")   # 기본 모델 한도 초과(429) 때
MIN_SHOT_SEC = 2.0     # 이보다 짧은 장면은 이웃 장면에 합친다
CHUNK_SEC = 300.0      # 한 번에 보내는 최대 길이 (초)

_STR = {"type": "string"}
SHOT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["start", "end", "desc", "place", "action", "people", "visible_text", "event", "mood"],
        "properties": {
            "start": {"type": "number"},
            "end": {"type": "number"},
            "desc": _STR,
            "place": _STR,
            "action": _STR,
            "people": {"type": "array", "items": _STR},
            "visible_text": _STR,
            "event": _STR,
            "mood": _STR,
        },
    },
}

PROMPT_TEMPLATE = """당신은 브이로그 영상의 장면 기록자다. 소리는 없고 화면만 본다.
이 영상의 길이는 {duration:.1f}초다.{chunk_note}

[장면을 나누는 기준]
- 화면 속 사람의 행동, 카메라가 비추는 대상, 장소 중 하나라도 바뀌면 새 장면으로 나눈다.
- 장면 하나는 보통 3~7초다. 같은 장면이 10초 넘게 이어지면 그 안에서 달라지는 것
  (동작, 시선, 걸음, 카메라 방향, 화면에 들어오는 사람)을 기준으로 더 나눈다.
- {min_sec:.0f}초보다 짧은 변화는 앞 장면에 합친다.

[출력 규칙]
- 0초부터 {duration:.1f}초까지 빈틈없이, 겹치지 않게 나눈다. start, end는 이 영상 시작 기준 초 단위 숫자다.
- desc: 화면에 보이는 것을 주어와 동작이 드러나게 한 문장으로 쓴다. (예: "카운터 앞에서 메뉴판을 올려다본다")
- place: 장소를 짧은 한국어 명사구로 쓴다. (예: "카페 카운터", "해변 모래사장") [이미 쓴 장소 라벨]과 같은 곳이면 그 라벨을 그대로 쓴다.
- action: 주된 행동을 짧은 명사구로 쓴다. (예: "메뉴 보기", "결제", "바다 구경")
- people: 화면에 직접 보이는 인물을 옷차림·외형 라벨로 쓴다. (예: "검은 티셔츠 남성") 이름 추정이나 얼굴로 신원 판단은 절대 금지.
  [이미 쓴 인물 라벨]과 같은 사람으로 보이면 그 라벨을 그대로 쓴다. 아무도 없으면 빈 배열.
- visible_text: 화면에서 읽을 수 있는 글자(간판, 메뉴판, 표지판, 상표)를 그대로 옮긴다. 없으면 빈 문자열.
- event: 눈에 띄는 화면 사건(도착, 건배, 넘어짐 등). 없으면 빈 문자열.
- mood: 장면 분위기를 한 단어로 쓴다. (예: 차분, 활기, 설렘) 판단하기 어려우면 빈 문자열.

[이미 쓴 장소 라벨]
{known_places}

[이미 쓴 인물 라벨]
{known_people}

[바로 앞 장면]
{prev}

JSON 배열만 출력한다. 다른 설명은 쓰지 않는다."""


# ---------------------------------------------------------------- 조각 나누기·저해상도 만들기

def chunk_bounds(duration: float, chunk_sec: float = CHUNK_SEC, min_last: float = 30.0) -> list[tuple[float, float]]:
    """클립을 chunk_sec 이하 조각으로 나눈다. 마지막 조각이 min_last초보다 짧아지면 앞 조각에 붙인다."""
    bounds, start = [], 0.0
    while duration - start > chunk_sec + min_last:
        bounds.append((start, start + chunk_sec))
        start += chunk_sec
    bounds.append((start, duration))
    return bounds


def make_chunk_lowres(src: Path, dst: Path, start: float, length: float, height: int):
    """조각 하나를 초당 1장, 무음, 고압축으로 만든다 (scene_analyzer.make_lowres와 같은 설정, 구간만 자름)."""
    if dst.exists() and dst.stat().st_size > 0:
        return
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(src),
         "-vf", f"scale=-2:{height},fps=1", "-an",
         "-c:v", "libx264", "-crf", "32", "-preset", "veryfast", str(dst)])


# ---------------------------------------------------------------- 결과 정리

def _text(value) -> str:
    return " ".join(str(value or "").split())


def _labels(value) -> list[str]:
    """["a", "b"] 또는 "a, b" → 중복 없는 라벨 목록."""
    items = value if isinstance(value, list) else str(value or "").split(",")
    out = []
    for item in items:
        label = _text(item)
        if label and label not in out:
            out.append(label)
    return out


def empty_shot(start: float, end: float, desc: str, flag: str) -> dict:
    return {"start": start, "end": end, "desc": desc, "place": "", "action": "", "people": [],
            "visible_text": "", "event": "", "mood": "", "flag": flag}


def merge_shot(a: dict, b: dict) -> dict:
    """이웃한 두 장면을 하나로. 설명·장소·행동은 더 긴 쪽을 따르고, 인물·글자·사건은 합친다."""
    main = a if a["end"] - a["start"] >= b["end"] - b["start"] else b
    merged = {**main, "start": a["start"], "end": b["end"],
              "people": _labels(a.get("people", []) + b.get("people", []))}
    for key in ("visible_text", "event"):
        parts = [x for x in (a.get(key, ""), b.get(key, "")) if x]
        merged[key] = "; ".join(dict.fromkeys(parts))
    return merged


def _same(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ("desc", "place", "action"))


def clean_shots(raw: list, duration: float, min_sec: float = MIN_SHOT_SEC) -> list[dict]:
    """LLM 출력을 믿지 않고 코드로 정리한다 (조각 안 초 기준).
    - 범위 자르기, 시작 순 정렬, 같은 시작 중복 제거
    - 빈틈은 가운데에서, 겹침은 뒤 장면 시작에서 잘라 0~duration을 빈틈없이 덮게 만든다
    - min_sec보다 짧은 장면, 설명·장소·행동이 똑같은 이웃 장면은 합친다"""
    shots = []
    for s in raw or []:
        if not isinstance(s, dict):
            continue
        try:
            st, en = to_seconds(s.get("start", 0)), to_seconds(s.get("end", 0))
        except (ValueError, TypeError):
            continue
        st, en = max(0.0, min(st, duration)), max(0.0, min(en, duration))
        if en <= st:
            continue
        shot = {"start": st, "end": en, "desc": _text(s.get("desc")), "place": _text(s.get("place")),
                "action": _text(s.get("action")), "people": _labels(s.get("people")),
                "visible_text": _text(s.get("visible_text")), "event": _text(s.get("event")),
                "mood": _text(s.get("mood"))}
        if s.get("flag"):
            shot["flag"] = str(s["flag"])
        shots.append(shot)
    if not shots:
        return [empty_shot(0.0, duration, "(장면 인식 실패)", "empty")]

    shots.sort(key=lambda x: (x["start"], -x["end"]))
    unique = [shots[0]]
    for cur in shots[1:]:
        if cur["start"] > unique[-1]["start"] + 0.05:
            unique.append(cur)
    # 경계: 빈틈이면 가운데, 겹치면 뒤 장면 시작. 항상 앞 장면 시작보다 뒤라서 순서가 유지된다.
    for prev, cur in zip(unique, unique[1:]):
        boundary = (prev["end"] + cur["start"]) / 2 if prev["end"] <= cur["start"] else cur["start"]
        prev["end"] = cur["start"] = boundary
    unique[0]["start"], unique[-1]["end"] = 0.0, duration

    merged = [unique[0]]
    for cur in unique[1:]:
        if _same(merged[-1], cur):
            merged[-1] = merge_shot(merged[-1], cur)
        else:
            merged.append(cur)
    return merge_short(merged, min_sec)


def merge_short(shots: list[dict], min_sec: float) -> list[dict]:
    """min_sec보다 짧은 장면을 앞뒤 중 더 짧은 이웃과 합친다 (가장 짧은 것부터)."""
    shots = list(shots)
    while len(shots) > 1:
        lengths = [s["end"] - s["start"] for s in shots]
        i = min(range(len(shots)), key=lengths.__getitem__)
        if lengths[i] >= min_sec - 1e-6:
            break
        if i == 0:
            j = 1
        elif i == len(shots) - 1:
            j = i - 1
        else:
            j = i - 1 if lengths[i - 1] <= lengths[i + 1] else i + 1
        lo, hi = min(i, j), max(i, j)
        shots[lo:hi + 1] = [merge_shot(shots[lo], shots[hi])]
    return shots


# ---------------------------------------------------------------- Gemini 호출

def build_prompt(duration: float, chunk_start: float, total: float, known: dict, min_sec: float) -> str:
    chunk_note = (f"\n(원본 클립 {total:.1f}초 중 {fmt_time(chunk_start)}부터 이어지는 부분이다.)"
                  if chunk_start > 0 or duration < total - 0.5 else "")
    return PROMPT_TEMPLATE.format(
        duration=duration, chunk_note=chunk_note, min_sec=min_sec,
        known_places=", ".join(known.get("places", [])) or "(없음)",
        known_people=", ".join(known.get("people", [])) or "(없음)",
        prev=known.get("prev") or "(처음)",
    )


def remember(known: dict, shots: list[dict]):
    """다음 조각·클립 프롬프트에 넘길 라벨을 모은다 (같은 장소·인물에 같은 라벨을 쓰게)."""
    for key, values in (("places", [s["place"] for s in shots]), ("people", [p for s in shots for p in s["people"]])):
        seen = known.setdefault(key, [])
        for v in values:
            if v and v not in seen:
                seen.append(v)
        del seen[:-30]
    known["prev"] = " / ".join(s["desc"] for s in shots[-2:] if s["desc"])


def _is_quota(error: Exception) -> bool:
    return "429" in str(error) or "RESOURCE_EXHAUSTED" in str(error)


def ask_video(client, video: Path, prompt: str, model: str, resolution: str = "low",
              retries: int = 2, fallback: str | None = FALLBACK_MODEL) -> tuple[list, dict, str]:
    """scene_analyzer.analyze_clip과 같은 방식(파일 업로드 → interactions → 삭제)이고 프롬프트·스키마만 다르다.
    한도 초과(429)면 fallback 모델로 넘어간다 (무료 한도는 모델마다 따로). 반환: (원본 장면 목록, 사용량, 쓴 모델)"""
    f = client.files.upload(file=str(video))
    try:
        while not f.state or f.state.name != "ACTIVE":
            if f.state and f.state.name == "FAILED":
                raise RuntimeError("Gemini 파일 처리 실패")
            time.sleep(2)
            f = client.files.get(name=f.name)
        last_err = None
        for name in [model] + ([fallback] if fallback and fallback != model else []):
            for attempt in range(retries + 1):
                try:
                    inter = client.interactions.create(
                        model=name,
                        input=[
                            {"type": "video", "uri": f.uri, "mime_type": f.mime_type,
                             "resolution": resolution, "processing": "static"},
                            {"type": "text", "text": prompt},
                        ],
                        response_format={"type": "text", "mime_type": "application/json", "schema": SHOT_SCHEMA},
                        generation_config={"temperature": 0},   # 같은 영상 → 같은 결과
                    )
                    raw = extract_json_array(inter.output_text)
                    usage = getattr(inter, "usage", None)
                    usage = usage.model_dump() if hasattr(usage, "model_dump") else (usage or {})
                    return raw, usage, name
                except Exception as e:
                    last_err = e
                    if _is_quota(e) or "INVALID_ARGUMENT" in str(e):   # 같은 모델로 다시 해도 소용없음
                        break
                    time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"장면 분석 실패: {last_err}")
    finally:
        try:
            client.files.delete(name=f.name)
        except Exception:
            pass


def analyze_clip_shots(client, src: Path, duration: float, work_dir: Path, args, known: dict,
                       log=print) -> tuple[list[dict], list[dict]]:
    """클립 하나 → 장면 목록 (클립 안 초). 조각마다 Gemini를 한 번 부른다.
    조각이 실패하면 그 조각만 "(분석 실패)" 장면 하나로 두고 계속한다."""
    shots, usage = [], []
    stem = f"{src.stem}_{src.stat().st_size}"
    for st, en in chunk_bounds(duration, args.chunk_sec):
        tag = f"{st:.0f}-{en:.0f}"
        raw_cache = work_dir / f"{stem}_{tag}_{args.model}_{args.resolution}.shots.json"
        try:
            if raw_cache.exists() and not getattr(args, "refresh", False):
                raw, u = json.loads(raw_cache.read_text(encoding="utf-8")), {"cached": True}
            else:
                low = work_dir / f"{stem}_{tag}_{args.height}p.mp4"
                make_chunk_lowres(src, low, st, en - st, args.height)
                prompt = build_prompt(en - st, st, duration, known, args.min_sec)
                raw, u, used = ask_video(client, low, prompt, args.model, args.resolution, args.retries)
                u = {**u, "model": used}
                raw_cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            part = clean_shots(raw, en - st, args.min_sec)
        except Exception as e:
            log(f"  조각 {fmt_time(st)}~{fmt_time(en)} 실패: {e}")
            part, u = [empty_shot(0.0, en - st, "(분석 실패)", "error")], {"error": str(e)[:300]}
        for s in part:
            s["start"], s["end"] = s["start"] + st, s["end"] + st
        shots += part
        usage.append({"chunk": [round(st, 2), round(en, 2)], **u})
        remember(known, part)
    return shots, usage


def load_api_key() -> str:
    """config.py와 같은 순서(GEMINI_API_KEY → gemini_key.txt)로 키를 읽는다."""
    import contextlib
    import io
    sys.path.insert(0, str(Path(__file__).parent))
    from config import config as _cfg
    with contextlib.redirect_stdout(io.StringIO()):   # config.py의 이모지 print가 cp949 콘솔에서 오류
        key = os.environ.get("GEMINI_API_KEY") or _cfg.load_api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY 환경변수 또는 gemini_key.txt 파일이 필요합니다.")
    return key


def make_client(api_key: str | None = None, timeout_ms: int | None = None):
    from google import genai
    from google.genai import types
    options = types.HttpOptions(timeout=timeout_ms) if timeout_ms else None
    return genai.Client(api_key=api_key or load_api_key(), http_options=options)


def analyze_video_shots(video_path: str, api_key: str, work_dir: str, duration: float | None = None) -> list[dict]:
    """앱용: 영상 하나 → L4 장면 목록 (영상 안 초). 실패하면 예외 (앱은 대사만으로 트리를 만든다)."""
    from types import SimpleNamespace
    from scene_analyzer import probe

    args = SimpleNamespace(model=DEFAULT_MODEL, resolution=os.getenv("SHOT_RESOLUTION", "low"), height=360,
                           min_sec=MIN_SHOT_SEC, chunk_sec=float(os.getenv("SHOT_CHUNK_SEC", CHUNK_SEC)),
                           retries=2, refresh=False)
    src = Path(video_path)
    duration = float(duration or probe(src)["duration"])
    print(f"🎬 장면 분석({args.model}) 시작: {fmt_time(duration)}, 조각 {len(chunk_bounds(duration, args.chunk_sec))}개")
    shots, usage = analyze_clip_shots(make_client(api_key), src, duration, Path(work_dir), args, {})
    if all(s.get("flag") == "error" for s in shots):
        raise RuntimeError(usage[-1].get("error") or "장면 분석 실패")
    print(f"✅ 장면 분석 완료: {len(shots)}개 장면")
    return shots


# ---------------------------------------------------------------- 메인

def main():
    if hasattr(sys.stdout, "reconfigure"):     # 진행 로그의 이모지가 한글(cp949) 콘솔에서 오류 나지 않게 (app.py와 같음)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from scene_analyzer import collect_inputs
    from transcriber import order_clips

    ap = argparse.ArgumentParser(description="VIBE CUT L4 장면(3~7초) 분석 (Gemini)")
    ap.add_argument("--input", nargs="+", required=True, help="클립 파일들 또는 폴더")
    ap.add_argument("--out", default="shots.json")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"기본 {DEFAULT_MODEL}")
    ap.add_argument("--resolution", default="low", choices=["low", "medium", "high", "ultra_high"],
                    help="Gemini가 영상을 볼 해상도")
    ap.add_argument("--height", type=int, default=360, help="전처리 세로 해상도")
    ap.add_argument("--chunk-sec", type=float, default=CHUNK_SEC, help="한 번에 보낼 최대 길이(초)")
    ap.add_argument("--min-sec", type=float, default=MIN_SHOT_SEC, help="이보다 짧은 장면은 합침")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--cache", default=".vibecut_cache")
    ap.add_argument("--refresh", action="store_true", help="장면 분석 캐시를 무시하고 다시 실행")
    args = ap.parse_args()

    files = collect_inputs(args.input)
    if not files:
        sys.exit("영상 파일을 찾지 못했습니다.")
    clips = order_clips(files)
    print(f"\n총 {len(clips)}개, {fmt_time(sum(c['duration'] for c in clips))}")

    cache = Path(args.cache)
    cache.mkdir(exist_ok=True)
    client = make_client()
    all_shots, usage_log, known, t0 = [], [], {}, time.time()
    for c in clips:
        print(f"[{c['id']}] {c['file'].name} ({fmt_time(c['duration'])}) 분석…", flush=True)
        shots, usage = analyze_clip_shots(client, c["file"], c["duration"], cache, args, known)
        for s in shots:
            s["clip_id"] = c["id"]
            s["clip_start"], s["clip_end"] = round(s["start"], 3), round(s["end"], 3)
            s["start"], s["end"] = round(s["start"] + c["offset"], 3), round(s["end"] + c["offset"], 3)
        all_shots += shots
        usage_log.append({"clip_id": c["id"], "chunks": usage})
        print(f"  장면 {len(shots)}개")

    for i, s in enumerate(all_shots, 1):
        s["shot_id"] = f"v{i:04d}"
    result = {
        "meta": {"model": args.model, "resolution": args.resolution, "height": args.height,
                 "chunk_sec": args.chunk_sec, "min_sec": args.min_sec,
                 "elapsed_sec": round(time.time() - t0, 1), "created_at": datetime.now().isoformat(timespec="seconds")},
        "clips": [{"id": c["id"], "file": c["file"].name, "duration": round(c["duration"], 2),
                   "offset": round(c["offset"], 2),
                   "created_at": datetime.fromtimestamp(c["created"]).isoformat(timespec="seconds")} for c in clips],
        "shots": [{k: s[k] for k in ("shot_id", "clip_id", "start", "end", "clip_start", "clip_end", "desc", "place",
                                     "action", "people", "visible_text", "event", "mood", "flag") if k in s}
                  for s in all_shots],
        "usage": usage_log,
    }
    out = Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# L4 장면 목록 ({args.model}, res={args.resolution}, {args.height}p)", "",
             "| 장면 | 클립 | 시작 | 길이 | 장소 | 행동 | 화면 | 인물 | 화면 글자 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in result["shots"]:
        lines.append(f"| {s['shot_id']} | {s['clip_id']} | {fmt_time(s['start'])} | {s['end'] - s['start']:.1f}초 | "
                     f"{s['place']} | {s['action']} | {s['desc']} | {', '.join(s['people'])} | {s['visible_text']} |")
    out.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n완료: {out}, {out.with_suffix('.md')} (장면 {len(all_shots)}개, {result['meta']['elapsed_sec']}초)")


if __name__ == "__main__":
    main()
