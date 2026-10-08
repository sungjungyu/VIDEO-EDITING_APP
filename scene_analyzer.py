
"""
VIBE CUT 1-2 화면 갈래: 영상 장면 이해 (Gemini API)

여러 클립을 촬영 시각 순으로 정렬하고, 클립마다 저해상도·무음으로 압축한 뒤
Gemini에 보내 "장소·활동이 바뀔 때마다 한 항목"인 장면 목록 JSON을 만든다.
모든 시각은 전체 타임라인 기준 초 단위로 변환된다.

사용 예:
    python scene_analyzer.py --input ./raw_clips --out scenes.json
    python scene_analyzer.py --input a.mp4 b.mp4 --model gemini-3.8-flash --mode agentic --resolution medium

필요: Python 3.10+, imageio-ffmpeg, moviepy, pip install -U google-genai
API 키: 환경변수 GEMINI_API_KEY 또는 gemini_key.txt
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

# ffmpeg PATH 없이도 동작하도록 imageio-ffmpeg 경로 우선 사용
try:
    import imageio_ffmpeg as _iio_ffmpeg
    _FFMPEG = _iio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    _FFMPEG = "ffmpeg"

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"}

# response_format에 넘길 JSON 스키마 (Structured outputs)
_SCENE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["start", "end", "place", "activity", "people", "background_people", "event", "summary"],
        "properties": {
            "start":             {"type": "number"},
            "end":               {"type": "number"},
            "place":             {"type": "string"},
            "activity":          {"type": "string"},
            "people":            {"type": "string"},
            "background_people": {"type": "boolean"},
            "event":             {"type": "string"},
            "mood":              {"type": "string"},
            "summary":           {"type": "string"},
        },
    },
}

PROMPT_TEMPLATE = """당신은 브이로그 영상의 장면 기록자다. 소리는 없고 화면만 본다.
이 클립의 길이는 {duration:.1f}초다.

[장면을 나누는 기준]
- 장소가 바뀌거나 주된 활동이 바뀔 때 새 장면으로 나눈다.
- 같은 장소·활동에서 카메라 방향(셀카↔풍경)이나 화각만 바뀐 것은 같은 장면이다.
- {min_sec}초 미만의 짧은 변화는 앞 장면에 합친다.

[출력 규칙]
- 클립의 0초부터 {duration:.1f}초까지 빈틈없이, 겹치지 않게 나눈다.
- start, end는 이 클립 시작 기준 초 단위 숫자다.
- place, activity는 짧은 한국어 명사구로 쓴다. (예: "카페 실내", "음료 주문")
- people은 화면에 직접 등장하는 인물만 옷차림·외형 라벨로 쓴다. (예: "빨간 후드 촬영자", "남색 패딩") 아무도 없으면 빈 문자열. 이름 추정이나 얼굴로 신원 판단은 절대 금지.
- 이전 클립 인물과 같은 사람으로 보이면 반드시 같은 라벨을 재사용한다.
- background_people은 배경에 행인·군중이 보이면 true, 없으면 false.
- event는 눈에 띄는 화면 사건이 있으면 쓰고, 없으면 빈 문자열로 둔다.
- mood는 장면 분위기를 한 단어로 쓴다. (예: 차분, 활기, 긴장, 설렘, 무거움) 판단하기 어려우면 빈 문자열로 둔다.
- summary는 그 장면을 한 문장으로 요약한다.

[이전 클립 등장인물 라벨]
{known_people}

[이전 클립 요약]
{prev_summary}

JSON 배열만 출력한다. 다른 설명은 쓰지 않는다.
[{{"start": 0, "end": 0, "place": "", "activity": "", "people": "", "background_people": false, "event": "", "mood": "", "summary": ""}}]
"""


# ---------------------------------------------------------------- ffmpeg 유틸

def run(cmd):
    # "ffmpeg" 자리에 imageio-ffmpeg 경로 치환
    if cmd[0] == "ffmpeg":
        cmd = [_FFMPEG] + cmd[1:]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"명령 실패: {' '.join(cmd)}\n{r.stderr[-800:]}")
    return r.stdout


def probe(path: Path) -> dict:
    """길이와 촬영 시각을 읽는다. ffprobe 대신 moviepy + ffmpeg stderr 파싱 사용."""
    from moviepy import VideoFileClip
    with VideoFileClip(str(path)) as clip:
        duration = float(clip.duration)

    # 촬영 시각: ffmpeg -i stderr에서 creation_time 태그 파싱 시도
    result = subprocess.run(
        [_FFMPEG, "-v", "quiet", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    created = None
    for key in ("com.apple.quicktime.creationdate", "creation_time"):
        m = re.search(rf"{re.escape(key)}\s*:\s*(\S+)", result.stderr, re.IGNORECASE)
        if m:
            try:
                created = datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp()
                break
            except ValueError:
                pass
    if created is None:
        created = path.stat().st_mtime
    return {"duration": duration, "created": created}


def make_lowres(src: Path, dst: Path, height: int):
    """초당 1장, 무음, 고압축. Gemini API 전송 크기를 줄인다."""
    if dst.exists() and dst.stat().st_size > 0:
        return
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-vf", f"scale=-2:{height},fps=1", "-an",
         "-c:v", "libx264", "-crf", "32", "-preset", "veryfast", str(dst)])


# ---------------------------------------------------------------- 결과 파싱·검증

def to_seconds(v) -> float:
    """숫자, "MM:SS", "HH:MM:SS"를 모두 초로 바꾼다."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    parts = [float(p) for p in s.split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def extract_json_array(text: str) -> list:
    """response_format이 적용돼도, 마크다운 펜스가 붙어도 모두 처리."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("응답에서 JSON 배열을 찾지 못함")
    return json.loads(text[start:end + 1])


def clean_scenes(raw: list, duration: float, min_sec: float) -> list:
    """LLM 출력을 믿지 않고 코드로 정리: 범위 자르기, 정렬, 겹침·빈틈 처리, 짧은 장면·같은 장면 합치기."""
    scenes = []
    for s in raw:
        try:
            st, en = to_seconds(s.get("start", 0)), to_seconds(s.get("end", 0))
        except (ValueError, TypeError):
            continue
        st, en = max(0.0, min(st, duration)), max(0.0, min(en, duration))
        if en <= st:
            continue
        scenes.append({
            "start": st, "end": en,
            "place": str(s.get("place", "")).strip(),
            "activity": str(s.get("activity", "")).strip(),
            "people": str(s.get("people", "")).strip(),
            "background_people": bool(s.get("background_people", False)),
            "event": str(s.get("event", "")).strip(),
            "mood": str(s.get("mood", "")).strip(),
            "summary": str(s.get("summary", "")).strip(),
        })
    if not scenes:
        return [{"start": 0.0, "end": duration, "place": "", "activity": "",
                 "people": "", "background_people": False, "event": "", "mood": "",
                 "summary": "(장면 인식 실패)", "flag": "empty"}]

    scenes.sort(key=lambda x: x["start"])
    scenes[0]["start"] = 0.0
    for prev, cur in zip(scenes, scenes[1:]):
        boundary = (prev["end"] + cur["start"]) / 2 if prev["end"] != cur["start"] else cur["start"]
        prev["end"] = cur["start"] = boundary
    scenes[-1]["end"] = duration

    merged = [scenes[0]]
    for cur in scenes[1:]:
        last = merged[-1]
        same = (cur["place"], cur["activity"]) == (last["place"], last["activity"])
        if same or (cur["end"] - cur["start"]) < min_sec:
            last["end"] = cur["end"]
            if cur["event"] and cur["event"] not in last["event"]:
                last["event"] = (last["event"] + "; " + cur["event"]).strip("; ")
        else:
            merged.append(cur)
    return merged


# ---------------------------------------------------------------- Gemini 호출

def analyze_clip(client, lowres: Path, duration: float, args, prev_summary: str, known_people: str) -> tuple[list, dict]:
    f = client.files.upload(file=str(lowres))
    try:
        while not f.state or f.state.name != "ACTIVE":
            if f.state and f.state.name == "FAILED":
                raise RuntimeError("Gemini 파일 처리 실패")
            time.sleep(3)
            f = client.files.get(name=f.name)

        prompt = PROMPT_TEMPLATE.format(duration=duration, min_sec=args.min_sec,
                                        prev_summary=prev_summary or "(첫 클립)",
                                        known_people=known_people or "(없음)")
        last_err = None
        for attempt in range(args.retries + 1):
            try:
                inter = client.interactions.create(
                    model=args.model,
                    input=[
                        {
                            "type": "video",
                            "uri": f.uri,
                            "mime_type": f.mime_type,
                            "resolution": args.resolution,   # "low"|"medium"|"high"|"ultra_high"
                            "processing": args.mode,         # "static"|"agentic" (공식 docs 기준)
                        },
                        {"type": "text", "text": prompt},
                    ],
                    # JSON 스키마 강제 적용 (Structured outputs)
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": _SCENE_SCHEMA,
                    },
                )
                raw = extract_json_array(inter.output_text)
                usage = getattr(inter, "usage", None)
                usage = usage.model_dump() if hasattr(usage, "model_dump") else (usage or {})
                return raw, usage
            except Exception as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"분석 실패: {last_err}")
    finally:
        try:
            client.files.delete(name=f.name)
        except Exception:
            pass


# ---------------------------------------------------------------- 메인

def collect_inputs(paths: list[str]) -> list[Path]:
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            files += [x for x in p.iterdir() if x.suffix.lower() in VIDEO_EXT]
        elif p.suffix.lower() in VIDEO_EXT:
            files.append(p)
    return files


def fmt_time(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def main():
    ap = argparse.ArgumentParser(description="VIBE CUT 장면 이해 (Gemini)")
    ap.add_argument("--input", nargs="+", required=True, help="클립 파일들 또는 폴더")
    ap.add_argument("--out", default="scenes.json")
    ap.add_argument("--model", default="gemini-3.5-flash-lite",
                    help="기본: gemini-3.5-flash-lite / 비교: gemini-3.8-flash")
    ap.add_argument("--mode", default="static", choices=["static", "agentic"],
                    help="영상 처리 방식 (VideoContent.processing)")
    ap.add_argument("--resolution", default="low", choices=["low", "medium", "high", "ultra_high"],
                    help="Gemini가 영상을 볼 해상도 (VideoContent.resolution)")
    ap.add_argument("--height", type=int, default=360, help="전처리 세로 해상도")
    ap.add_argument("--min-sec", type=float, default=10.0, help="이보다 짧은 장면은 합침")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--cache", default=".vibecut_cache")
    ap.add_argument("--dry-run", action="store_true", help="정렬·전처리만 하고 API는 호출 안 함")
    args = ap.parse_args()

    files = collect_inputs(args.input)
    if not files:
        sys.exit("영상 파일을 찾지 못했습니다.")

    clips = []
    for path in files:
        info = probe(path)
        clips.append({"file": path, **info})
    clips.sort(key=lambda c: (c["created"], c["file"].name))
    offset = 0.0
    for i, c in enumerate(clips, 1):
        c["id"], c["offset"] = f"c{i:02d}", offset
        offset += c["duration"]

    # 정렬 순서 출력 (촬영 순서 확인용)
    print(f"\n{'─'*60}")
    print(f"{'ID':>4}  {'파일명':<30}  {'촬영시각':<22}  {'길이':>6}")
    print(f"{'─'*60}")
    for c in clips:
        ts = datetime.fromtimestamp(c["created"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{c['id']:>4}  {c['file'].name:<30}  {ts:<22}  {fmt_time(c['duration']):>6}")
    print(f"{'─'*60}")
    print(f"총 {len(clips)}개, {fmt_time(offset)}\n")

    cache = Path(args.cache)
    cache.mkdir(exist_ok=True)

    client = None
    if not args.dry_run:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            try:
                sys.path.insert(0, str(Path(__file__).parent))
                from config import config as _cfg
                api_key = _cfg.load_api_key()
            except Exception:
                pass
        if not api_key:
            sys.exit("GEMINI_API_KEY 환경변수 또는 gemini_key.txt 파일이 필요합니다.")
        client = genai.Client(api_key=api_key)

    all_scenes, usage_log, prev_summary, known_people = [], [], "", ""
    t0 = time.time()
    for c in clips:
        lowres = cache / f"{c['id']}_{c['file'].stem}_{args.height}p.mp4"
        print(f"[{c['id']}] {c['file'].name} ({fmt_time(c['duration'])}) 전처리…", end=" ", flush=True)
        make_lowres(c["file"], lowres, args.height)
        if args.dry_run:
            print("완료 (dry-run)")
            continue
        print("분석…", end=" ", flush=True)
        try:
            raw, usage = analyze_clip(client, lowres, c["duration"], args, prev_summary, known_people)
            scenes = clean_scenes(raw, c["duration"], args.min_sec)
        except Exception as e:
            print(f"실패: {e}")
            scenes = [{"start": 0.0, "end": c["duration"], "place": "", "activity": "",
                       "people": "", "background_people": False, "event": "", "mood": "",
                       "summary": "(분석 실패)", "flag": "error"}]
            usage = {}
        for s in scenes:
            s["clip_id"] = c["id"]
            s["clip_start"], s["clip_end"] = round(s["start"], 2), round(s["end"], 2)
            s["start"], s["end"] = round(s["start"] + c["offset"], 2), round(s["end"] + c["offset"], 2)
        all_scenes += scenes
        usage_log.append({"clip_id": c["id"], "usage": usage})
        prev_summary = " / ".join(f"{s['place']}: {s['summary']}" for s in scenes[-3:])
        # 다음 클립에 전달할 인물 라벨 목록 (중복 제거, 빈 값 제외)
        seen = []
        for s in scenes:
            for label in s["people"].split(","):
                label = label.strip()
                if label and label not in seen:
                    seen.append(label)
        known_people = ", ".join(seen) if seen else ""
        print(f"장면 {len(scenes)}개")

    if args.dry_run:
        return

    for i, s in enumerate(all_scenes, 1):
        s["scene_id"] = f"v{i:03d}"

    result = {
        "meta": {
            "model": args.model, "mode": args.mode,
            "resolution": args.resolution, "height": args.height,
            "min_sec": args.min_sec, "elapsed_sec": round(time.time() - t0, 1),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
        "clips": [{"id": c["id"], "file": c["file"].name, "duration": round(c["duration"], 2),
                   "offset": round(c["offset"], 2)} for c in clips],
        "scenes": [{k: s[k] for k in ("scene_id", "clip_id", "start", "end", "clip_start", "clip_end",
                                       "place", "activity", "people", "background_people",
                                       "event", "mood", "summary", "flag")
                    if k in s} for s in all_scenes],
        "usage": usage_log,
    }
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    md = Path(args.out).with_suffix(".md")
    lines = [f"# 장면 목록 ({args.model}, mode={args.mode}, res={args.resolution}, {args.height}p)", "",
             "| 장면 | 클립 | 시작 | 끝 | 장소 | 활동 | 인물 | 배경행인 | 사건 | 분위기 | 요약 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in result["scenes"]:
        bp = "O" if s.get("background_people") else "-"
        lines.append(f"| {s['scene_id']} | {s['clip_id']} | {fmt_time(s['start'])} | {fmt_time(s['end'])} | "
                     f"{s['place']} | {s['activity']} | {s.get('people','')} | {bp} | "
                     f"{s['event']} | {s.get('mood','')} | {s['summary']} |")
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n완료: {args.out}, {md} (장면 {len(all_scenes)}개, {result['meta']['elapsed_sec']}초)")


if __name__ == "__main__":
    main()
