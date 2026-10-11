#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_prompt_builder.py

prompt_builder 모듈의 수동 테스트 스크립트.
두 모드(manual / auto)에 대한 가짜 입력으로 지시문을 조립해 보고,
일부러 틀린 AI 응답(없는 id, 분량 초과/부족)에 대해 validate_response가
오류를 잡는지 확인한다.
"""

from __future__ import annotations

import json

from prompt_builder import (
    build_prompt,
    calc_duration,
    normalize_tree,
    validate_response,
)


# ---------------------------------------------------------------------------
# 가짜 데이터
# ---------------------------------------------------------------------------

PROFILE = {
    "subtitle_style": "굵은 노랑, 하단 중앙, 2줄 최대",
    "cut_tempo": "빠름 (평균 3~5초)",
    "filler_removal": "강 (음, 어, 그니까 전부 제거)",
    "frequent_words": ["꿀팁", "레전드", "결론부터"],
    "aspect_ratio": "9:16",
}

# 외부에서 들어온다고 가정한 raw 트리 (일부러 alias 섞어서 넣음)
RAW_TREE = [
    {
        "node_id": "intro",
        "name": "오프닝",
        "start_sec": 0,
        "end_sec": 30,
        "description": "채널 소개 및 오늘 주제 티저",
        "tags": ["opening", "hook"],
        "children": [
            {"id": "intro-hook", "title": "훅 멘트", "start": 0, "end": 10, "tags": ["hook"]},
            {"id": "intro-topic", "title": "오늘 주제", "start": 10, "end": 30},
        ],
    },
    {
        "id": "body",
        "title": "본론: 영상편집 꿀팁 3가지",
        "start": 30,
        "end": 330,  # 5분
        "summary": "핵심 꿀팁 세 가지를 순서대로 설명",
        "children": [
            {
                "id": "tip-1",
                "title": "꿀팁 1 - 컷편집",
                "start": 30,
                "end": 120,
                "children": [
                    {"id": "tip-1-demo", "title": "데모", "start": 60, "end": 100},
                ],
            },
            {"id": "tip-2", "title": "꿀팁 2 - 자막", "start": 120, "end": 220},
            {"id": "tip-3", "title": "꿀팁 3 - 색보정", "start": 220, "end": 330},
        ],
    },
    {
        "id": "outro",
        "title": "엔딩",
        "start": 330,
        "end": 390,  # 1분
        "children": [
            {"id": "outro-cta", "title": "구독 유도", "start": 330, "end": 360},
            {"id": "outro-next", "title": "다음 영상 예고", "start": 360, "end": 390},
        ],
    },
]

# 요청 두 가지 (새 포맷)
REQUEST_MANUAL = {
    "mode": "manual",
    "target_minutes": 3,
    "user_prompt": "사용자가 직접 체크한 장면으로 편집",
    "selected_nodes": ["intro-hook", "tip-2", "outro-cta"],
}

REQUEST_AUTO = {
    "mode": "auto",
    "target_minutes": 2,
    "user_prompt": "틱톡용 하이라이트, 임팩트 있게",
    "selected_nodes": [],
}


# ---------------------------------------------------------------------------
# 출력 유틸
# ---------------------------------------------------------------------------

def _hr(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def _show_prompt(label: str, prompt):
    _hr(f"[{label}] build_prompt 결과")
    if prompt is None:
        print("(None 반환 - AI 호출 불필요)")
    else:
        print(prompt)


def _show_validation(label: str, result: dict) -> None:
    _hr(f"[{label}] validate_response 결과")
    print(json.dumps(result, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main() -> None:
    # 트리 정규화 확인
    tree = normalize_tree(RAW_TREE)
    _hr("normalize_tree 결과 (내부 포맷)")
    print(json.dumps(tree, ensure_ascii=False, indent=2))

    # 전체 트리 길이 참고용
    all_ids = ["intro", "body", "outro"]
    print(f"\n[참고] 루트 3개(intro+body+outro) 총 길이 = {calc_duration(all_ids, tree):.1f}s")
    # 부모+자식 중복 선택 테스트
    dedup_check = calc_duration(["body", "tip-1", "tip-1-demo"], tree)
    print(f"[참고] body + tip-1 + tip-1-demo 중복 선택 길이 = {dedup_check:.1f}s (body 300s 기대)")

    # 1) manual
    prompt_manual = build_prompt(PROFILE, REQUEST_MANUAL, tree)
    _show_prompt("manual", prompt_manual)

    # 2) auto
    prompt_auto = build_prompt(PROFILE, REQUEST_AUTO, tree)
    _show_prompt("auto", prompt_auto)

    # ---------------------------------------------------------------
    # 검증 테스트 (일부러 틀린 답도 넣는다)
    # ---------------------------------------------------------------

    # (A) auto - 분량 초과 (목표 2분=120s인데 300s 짜리 body 통째로 선택)
    over_auto = ["body"]
    _show_validation(
        "auto - 분량 초과(목표 2분인데 body 전체 선택)",
        validate_response(over_auto, REQUEST_AUTO, tree),
    )

    # (B) auto - 분량 부족 (목표 2분인데 10초짜리만)
    under_auto = ["intro-hook"]
    _show_validation(
        "auto - 분량 부족(10초만 선택)",
        validate_response(under_auto, REQUEST_AUTO, tree),
    )

    # (C) auto - 길이 적정 (목표 2분=120s, tip-2 100s + outro-cta 30s = 130s → 1.08 OK)
    ok_auto = ["tip-2", "outro-cta"]
    _show_validation(
        "auto - 길이 적정",
        validate_response(ok_auto, REQUEST_AUTO, tree),
    )

    # (D) auto - 없는 id가 섞인 응답
    bad_auto = ["tip-2", "ghost-node"]
    _show_validation(
        "auto - 없는 id 섞임",
        validate_response(bad_auto, REQUEST_AUTO, tree),
    )

    # (E) manual - 사용자가 고른 nodes의 총 길이 검증
    #     intro-hook(10) + tip-2(100) + outro-cta(30) = 140s, 목표 180s → 0.78 → 부족
    _show_validation(
        "manual - 사용자 선택 길이 검증 (부족 예상)",
        validate_response(REQUEST_MANUAL["selected_nodes"], REQUEST_MANUAL, tree),
    )


if __name__ == "__main__":
    main()
