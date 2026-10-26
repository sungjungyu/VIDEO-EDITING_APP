#!/usr/bin/env python3
"""명령줄로 한 번에 편집하기. 웹 화면과 같은 파이프라인(vibecut)을 쓴다.

    python main.py                                   input.mp4 → output.mp4
    python main.py a.mp4 b.mp4 -o vlog.mp4           여러 클립 (지정한 순서대로)
    python main.py raw/*.mp4 --sort --target 90 --prompt "카페 장면 위주로"
    python main.py input.mp4 --offline               Gemini 없이 (규칙 기반 판단)

결과 영상과 함께 평가 지표 표를 출력한다. 작업 내용은 data/projects/에 남아 웹 화면에서 이어서 열 수 있다.
"""

import argparse
import hashlib
import logging
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

from vibecut.ai.gemini import GeminiClient, Usage
from vibecut.ai.select import select_scenes
from vibecut.edit.planner import compile_plan, effective_decisions
from vibecut.eval.metrics import project_metrics, to_markdown
from vibecut.log import setup_logging
from vibecut.media.ffmpeg import probe
from vibecut.server import pipeline
from vibecut.server.storage import ProjectStore
from vibecut.settings import load_api_key, load_settings

log = logging.getLogger("vibecut.cli")


class CliContext:
    """JobContext와 같은 모양 (작업 큐 없이 바로 실행할 때)."""

    def __init__(self):
        self.job_id = uuid.uuid4().hex[:12]
        self.cancel = threading.Event()
        self.log = log
        self.usage = Usage()
        self.metrics: dict = {"stages": {}}
        self._last = ""

    def progress(self, percent, stage=None, message=None):
        line = f"{percent:5.1f}%  {stage or ''} {message or ''}".rstrip()
        if line != self._last:
            print(f"\r{line[:100]:<100}", end="", flush=True)
            self._last = line

    def sub(self, lo, hi, stage=None):
        return lambda fraction: self.progress(lo + (hi - lo) * fraction, stage)

    def check(self):
        pass

    def stage(self, name):
        ctx = self

        class _Timer:
            def __enter__(self):
                self.t = time.time()

            def __exit__(self, *exc):
                ctx.metrics["stages"][name] = round(time.time() - self.t, 2)
        return _Timer()


def ask_api_key() -> None:
    """키가 없고 사람이 직접 실행했으면 한 번 묻는다 (README의 '자동 설정')."""
    if load_api_key() or not sys.stdin.isatty():
        return
    try:
        key = input("Gemini API 키 (없으면 Enter → 오프라인 모드): ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if key:
        Path(__file__).with_name("gemini_key.txt").write_text(key, encoding="utf-8")
        print("gemini_key.txt에 저장했습니다. 다음부터 자동으로 불러옵니다.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VIBE CUT 명령줄 편집")
    ap.add_argument("inputs", nargs="*", default=["input.mp4"], help="영상 파일들 (기본 input.mp4)")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("--target", type=float, default=None, help="목표 분량(초). 주면 AI 가편집으로 장면을 고른다")
    ap.add_argument("--prompt", default="", help="AI 가편집 요청 (예: '카페 장면 위주로')")
    ap.add_argument("--aspect", choices=["16:9", "9:16"], default="16:9")
    ap.add_argument("--quality", choices=["final", "preview"], default="final")
    ap.add_argument("--sort", action="store_true", help="촬영 시각 순으로 정렬 (기본은 입력 순서)")
    ap.add_argument("--no-subtitles", action="store_true")
    ap.add_argument("--offline", action="store_true", help="Gemini를 쓰지 않는다")
    args = ap.parse_args(argv)

    setup_logging("WARNING")
    files = [Path(p) for p in args.inputs]
    missing = [str(p) for p in files if not p.exists()]
    if missing:
        print(f"입력 파일을 찾을 수 없습니다: {', '.join(missing)}")
        print("사용법: python main.py 영상1.mp4 [영상2.mp4 …] -o 결과.mp4")
        return 1
    if not args.offline:
        ask_api_key()
    settings = load_settings(**({"ai_mode": "offline"} if args.offline else {}))
    print(f"AI 모드: {'live (Gemini)' if settings.ai_live else 'offline (규칙 기반)'}")

    store = ProjectStore(settings.data_dir)
    project = store.create(files[0].stem)
    pid = project.project_id
    for src in files:
        tmp = store.project_dir(pid) / "clips" / f".cli_{uuid.uuid4().hex[:8]}{src.suffix.lower()}"
        shutil.copyfile(src, tmp)
        digest = hashlib.sha1(tmp.read_bytes()).hexdigest()
        pipeline.add_clip(store, pid, tmp, src.name, tmp.stat().st_size, digest, probe(tmp), add_to_timeline=True)
    if args.sort:
        store.update(pid, lambda p: setattr(p, "timeline", [c.clip_id for c in sorted(
            p.timeline_clips(), key=lambda c: (c.created_at or 0, c.filename))]))

    ctx = CliContext()
    summary = pipeline.run_analysis(ctx, store, settings, pid, {})
    print(f"\n분석: 문장 {summary['lines']}개 (자름 제안 {summary['cut_suggested']}), 장면 {summary['scenes']}개")
    for w in summary["warnings"]:
        print(f"  ! {w}")

    plan = store.load_plan(pid)
    plan.output.aspect = args.aspect
    plan.options.subtitles = not args.no_subtitles
    project = store.get(pid)
    analysis = store.load_analysis(pid)
    if args.target:
        clips = {c.clip_id: c for c in project.timeline_clips()}
        client = GeminiClient(settings, store.cache_dir / "ai", usage=ctx.usage)
        selection, engine, warnings = select_scenes(analysis, clips, plan, effective_decisions(plan, analysis),
                                                    args.target, args.prompt, [], {}, client)
        plan.selection = selection
        print(f"AI 가편집({engine}): 장면 {len(selection.node_ids)}개 선택")
        for w in warnings:
            print(f"  ! {w}")
    plan = compile_plan(plan, project.timeline_clips(), analysis)
    store.save_plan(pid, plan)
    print(f"편집 계획: 구간 {len(plan.keep)}개, {plan.duration:.1f}초")

    result = pipeline.run_render(ctx, store, pid, args.quality)
    out = Path(args.output)
    shutil.copyfile(store.render_path(pid, result["render"]["file"]), out)
    print(f"\n완성: {out} ({result['render']['duration']:.1f}초, 계획과 차이 {result['render']['error_ms']:+.0f}ms)")
    project = store.get(pid)
    print()
    print(to_markdown(project.name, project_metrics(project, store.load_analysis(pid), store.load_plan(pid), [])))
    print(f"\n웹 화면에서 이어서 편집: python app.py → 프로젝트 {pid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
