"""평가 벤치마크 명령 (v4 설계안 T1): 검수한 정답 묶음으로 컷 판단 방법들을 채점해 표로.

    vibecut bench --list                     저장한 정답 묶음 목록
    vibecut bench                            모든 정답 묶음, 모든 방법
    vibecut bench --split test               시험용만 (결과 보고용)
    vibecut bench --methods rule --offline   규칙만, Gemini 없이
    vibecut bench --split tune --methods hybrid@0.6,hybrid@0.7,hybrid@0.8
                                             조정용 정답으로 '물어볼 기준 확신도' 고르기

정답 묶음은 웹 화면 ④ 확인·수정의 '검수 완료'로 만든다 (data/bench/cases/).
결과 표는 화면에 찍고, 자세한 숫자(묶음별 점수 포함)는 data/bench/results/에 JSON으로 남긴다.
"""

from __future__ import annotations

import argparse

from ..ai.client import GeminiClient
from ..errors import VibecutError
from ..eval.bench import to_markdown
from ..services.bench import METHODS, case_summary, run_bench
from ..settings import get_settings
from ..storage.bench import BenchStore
from ..storage.projects import ProjectStore


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--list", action="store_true", help="저장한 정답 묶음 목록만 보기")
    ap.add_argument("--methods", default=",".join(METHODS),
                    help=f"쉼표로 구분 (기본: {','.join(METHODS)}). hybrid@0.7처럼 기준 확신도를 바꿔 볼 수 있음")
    ap.add_argument("--split", choices=["tune", "test"], help="조정용(tune) 또는 시험용(test)만")
    ap.add_argument("--case", action="append", dest="cases", help="정답 묶음 id (여러 번 쓸 수 있음)")
    ap.add_argument("--offline", action="store_true", help="Gemini를 쓰지 않음 (gemini·hybrid 방법은 건너뜀)")
    ap.add_argument("--rounds", type=int, default=1000, help="F1 95%% 구간 부트스트랩 횟수 (0이면 계산 안 함)")


def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    bench = BenchStore(settings.data_dir)
    if args.list:
        cases = bench.list_cases()
        if not cases:
            print("정답 묶음이 없습니다. 웹 화면 ④ 확인·수정에서 '검수 완료'로 저장하세요.")
        for c in map(case_summary, cases):
            print(f"{c['case_id']}  [{c['split']}] {c['name']}  {c['person'] or '-'}  "
                  f"문장 {c['sentences']} (자름 {c['gold_cut']}), {c['seconds']:.0f}초")
        return 0
    client = None if args.offline else GeminiClient(settings, ProjectStore(settings.data_dir).cache_dir / "ai")
    try:
        result = run_bench(bench, client, [m.strip() for m in args.methods.split(",") if m.strip()],
                           args.split, args.cases, args.rounds)
    except VibecutError as error:
        print(f"오류: {error}")
        return 1
    if client is not None:
        result["ai_usage"] = client.usage.to_dict()
    path = bench.save_result(result)
    total = sum(c["sentences"] for c in result["cases"])
    print(f"정답 묶음 {len(result['cases'])}개, 문장 {total}개{f' ({args.split})' if args.split else ''}\n")
    print(to_markdown(result["rows"]))
    for name in result["skipped"]:
        print(f"\n! {name}: Gemini를 쓸 수 없어 건너뜀 (키가 없거나 --offline)")
    print(f"\n자세한 결과: {path}")
    return 0
