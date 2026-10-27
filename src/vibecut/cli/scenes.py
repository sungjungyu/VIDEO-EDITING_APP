"""장면 분석 명령 (조경우): 여러 클립을 촬영 시각 순으로 정렬하고 Gemini 영상 이해로 장면 목록을 만든다.

    vibecut scenes --input ./raw_clips --out scenes.json
    vibecut scenes --input a.mp4 b.mp4 --model gemini-3.8-flash --mode agentic --resolution medium

모든 시각은 전체 타임라인 기준 초. 결과: scenes.json + scenes.md (읽기용 표)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from ..ai.client import GeminiClient
from ..analysis.scenes.gemini import SceneOptions, describe_scenes
from ..media.convert import make_lowres
from ..settings import load_settings
from .clips import collect_inputs, fmt_time, order_clips, print_clip_table


def add_arguments(ap: argparse.ArgumentParser) -> None:
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


def run(args: argparse.Namespace) -> int:

    files = collect_inputs(args.input)
    if not files:
        sys.exit("영상 파일을 찾지 못했습니다.")

    clips = order_clips(files)
    print_clip_table(clips)

    cache = Path(args.cache)
    cache.mkdir(exist_ok=True)

    client = None
    options = SceneOptions(model=args.model, mode=args.mode, resolution=args.resolution, height=args.height,
                           min_sec=args.min_sec)
    if not args.dry_run:
        settings = load_settings(ai_mode="live", gemini_retries=args.retries)
        if not settings.api_key:
            sys.exit("GEMINI_API_KEY 환경변수 또는 .env 파일이 필요합니다.")
        client = GeminiClient(settings)

    all_scenes, usage_log, prev_summary, known_people = [], [], "", ""
    t0 = time.time()
    for c in clips:
        lowres = cache / f"{c['id']}_{c['file'].stem}_{args.height}p.mp4"
        print(f"[{c['id']}] {c['file'].name} ({fmt_time(c['duration'])}) 전처리…", end=" ", flush=True)
        if args.dry_run:
            make_lowres(c["file"], lowres, args.height)
            print("완료 (dry-run)")
            continue
        print("분석…", end=" ", flush=True)
        try:
            scenes, usage = describe_scenes(client, c["file"], lowres, c["duration"], options, prev_summary,
                                            known_people)
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
        return 0

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
    return 0
