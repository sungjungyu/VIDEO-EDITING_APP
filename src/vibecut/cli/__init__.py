"""명령줄 입구: vibecut <명령>.

    vibecut serve [--host --port --reload]         웹 화면 서버
    vibecut edit a.mp4 b.mp4 -o out.mp4 …          한 번에 편집 (분석 → 가편집 → 렌더)
    vibecut transcribe --input ./raw_clips …       받아쓰기만 (transcript.json)
    vibecut scenes --input ./raw_clips …           장면 분석만 (scenes.json)
    vibecut metrics [project_id]                   평가 지표 표
    vibecut bench [--split test] [--methods …]     컷 판단 채점 (검수한 정답 vs 규칙·Gemini·…)
"""

from __future__ import annotations

import argparse
import sys
from importlib import import_module

COMMANDS = {
    "serve": ("웹 화면 서버", None),
    "edit": ("영상 한 번에 편집 (분석 → AI 가편집 → 렌더)", "edit"),
    "transcribe": ("받아쓰기 (단어 단위 타임스탬프)", "transcribe"),
    "scenes": ("장면 분석 (Gemini 영상 이해)", "scenes"),
    "metrics": ("평가 지표 표", "metrics"),
    "bench": ("컷 판단 채점 (검수한 정답과 비교)", "bench"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vibecut", description="VIBE CUT 영상 편집 도구")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<명령>")
    for name, (help_text, module) in COMMANDS.items():
        cmd = sub.add_parser(name, help=help_text, description=help_text)
        if module is None:
            cmd.add_argument("--host", default=None, help="주소 (기본: 설정의 VIBECUT_HOST)")
            cmd.add_argument("--port", type=int, default=None, help="포트 (기본: 설정의 VIBECUT_PORT)")
            cmd.add_argument("--reload", action="store_true", help="코드를 고치면 자동으로 다시 시작 (개발용)")
        else:
            import_module(f".{module}", __name__).add_arguments(cmd)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        from ..server.app import serve
        serve(args.host, args.port, args.reload)
        return 0
    return import_module(f".{COMMANDS[args.command][1]}", __name__).run(args)


if __name__ == "__main__":
    sys.exit(main())
