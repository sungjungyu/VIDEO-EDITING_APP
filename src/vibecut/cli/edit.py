"""명령줄로 한 번에 편집하기. 웹 화면과 같은 서비스(services)를 그대로 쓴다.

    vibecut edit                                     input.mp4 → output.mp4
    vibecut edit a.mp4 b.mp4 -o vlog.mp4             여러 클립 (지정한 순서대로)
    vibecut edit raw/*.mp4 --sort --target 90 --prompt "카페 장면 위주로"
    vibecut edit input.mp4 --offline                 Gemini 없이 (규칙 기반 판단)

결과 영상과 함께 평가 지표 표를 출력한다. 작업 내용은 data/projects/에 남아 웹 화면에서 이어서 열 수 있다.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import uuid
from pathlib import Path

from ..ai.client import GeminiClient
from ..eval.metrics import project_metrics, to_markdown
from ..log import setup_logging
from ..media.probe import file_sha1, probe
from ..services import editing, projects
from ..services.analysis import run_analysis
from ..services.context import ConsoleContext
from ..services.rendering import run_render
from ..settings import ROOT_DIR, load_api_key, load_settings
from ..storage.projects import ProjectStore


def ask_api_key() -> None:
    """키가 없고 사람이 직접 실행했으면 한 번 묻고 .env에 저장한다."""
    if load_api_key() or not sys.stdin.isatty():
        return
    try:
        key = input("Gemini API 키 (없으면 Enter → 오프라인 모드): ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if key:
        env = ROOT_DIR / ".env"
        lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
        lines = [line for line in lines if not line.strip().startswith("GEMINI_API_KEY")]
        env.write_text("\n".join([*lines, f"GEMINI_API_KEY={key}"]) + "\n", encoding="utf-8")
        print(".env에 저장했습니다. 다음부터 자동으로 불러옵니다.")


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("inputs", nargs="*", default=["input.mp4"], help="영상 파일들 (기본 input.mp4)")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("--target", type=float, default=None, help="목표 분량(초). 주면 AI 가편집으로 장면을 고른다")
    ap.add_argument("--prompt", default="", help="AI 가편집 요청 (예: '카페 장면 위주로')")
    ap.add_argument("--aspect", choices=["16:9", "9:16"], default=None,
                    help="결과 비율 (기본: 영상 방향에 맞춰 자동 — 세로 영상이 많으면 9:16)")
    ap.add_argument("--quality", choices=["final", "preview"], default="final")
    ap.add_argument("--sort", action="store_true", help="촬영 시각 순으로 정렬 (기본은 입력 순서)")
    ap.add_argument("--no-subtitles", action="store_true")
    ap.add_argument("--offline", action="store_true", help="Gemini를 쓰지 않는다")


def run(args: argparse.Namespace) -> int:
    setup_logging("WARNING")
    files = [Path(p) for p in args.inputs]
    missing = [str(p) for p in files if not p.exists()]
    if missing:
        print(f"입력 파일을 찾을 수 없습니다: {', '.join(missing)}")
        print("사용법: vibecut edit 영상1.mp4 [영상2.mp4 …] -o 결과.mp4")
        return 1
    if not args.offline:
        ask_api_key()
    settings = load_settings(**({"ai_mode": "offline"} if args.offline else {}))
    print(f"AI 모드: {'live (Gemini)' if settings.ai_live else 'offline (규칙 기반)'}")

    store = ProjectStore(settings.data_dir)
    pid = store.create(files[0].stem).project_id
    try:
        return _edit(args, settings, store, pid, files)
    finally:                                   # 영상 복사본·렌더·오디오는 남기지 않는다 (결과는 -o 파일로 이미 복사)
        sha1s = [c.sha1 for c in store.get(pid).clips]
        store.delete(pid)
        for sha1 in sha1s:                     # 이 영상의 오디오만 (서버가 같은 폴더로 다른 영상을 분석 중일 수 있다)
            (store.audio_dir / f"{sha1[:20]}.wav").unlink(missing_ok=True)


def _edit(args, settings, store: ProjectStore, pid: str, files: list[Path]) -> int:
    for src in files:
        tmp = store.project_dir(pid) / "clips" / f".cli_{uuid.uuid4().hex[:8]}{src.suffix.lower()}"
        shutil.copyfile(src, tmp)
        projects.import_clip(store, pid, tmp, src.name, tmp.stat().st_size, file_sha1(tmp), probe(tmp),
                             add_to_timeline=True)
    if args.sort:
        projects.sort_timeline_by_shooting_time(store, pid)

    ctx = ConsoleContext()
    client = GeminiClient(settings, store.cache_dir / "ai")
    summary = run_analysis(ctx, store, settings, pid, {}, client)
    print(f"\n분석: 문장 {summary['lines']}개 (자름 제안 {summary['cut_suggested']}), 장면 {summary['scenes']}개")
    for w in summary["warnings"]:
        print(f"  ! {w}")

    plan = store.load_plan(pid)
    output = plan.output if args.aspect is None else \
        plan.output.model_copy(update={"aspect": args.aspect, "aspect_source": "user"})
    options = plan.options.model_copy(update={"subtitles": not args.no_subtitles})
    editing.update_plan(store, pid, output=output, options=options)
    if args.target:
        _, plan, engine, warnings = editing.select(store, client.with_usage(ctx.usage), pid, "auto", args.target,
                                                   args.prompt)
        print(f"AI 가편집({engine}): 장면 {len(plan.selection.beat_ids)}개 선택")
        for w in warnings:
            print(f"  ! {w}")
    _, plan = editing.current_plan(store, pid)
    print(f"편집 계획: 구간 {len(plan.keep)}개, {plan.duration:.1f}초")

    result = run_render(ctx, store, pid, args.quality)
    out = Path(args.output)
    shutil.copyfile(store.render_path(pid, result["render"]["file"]), out)
    print(f"\n완성: {out} ({result['render']['duration']:.1f}초, 계획과 차이 {result['render']['error_ms']:+.0f}ms)")
    project, plan = editing.current_plan(store, pid)
    print()
    print(to_markdown(project.name, project_metrics(project, store.load_analysis(pid), plan, [])))
    return 0
