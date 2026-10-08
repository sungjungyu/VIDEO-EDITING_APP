#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiment.py
=============

[이 파일의 역할]
----------------
build_prompt로 만든 지시문을 Gemini(gemini-3.5-flash)에 바로 보내고
validate_response로 검증하는 "단순 실험 스크립트".

본 서비스가 아니라 "prompt_builder가 Gemini에 잘 통하는지" 확인하기 위한
실험 도구다. 그래서 복잡한 추상화를 없애고 아래 규칙만 지킨다.

- Gemini 호출은 google.genai를 직접 사용 (main.py 재사용 X)
- 연결 확인/스레드/타임아웃/토큰 제한 전부 없음
- 4개 조건을 순서대로 실행하고 조건마다 응답 원문 + 검증 결과를 즉시 출력
- 마지막에 요약 표 출력 + experiment_results.json 저장

[데이터 흐름]
    gemini_key.txt
         │
         ▼
    genai.Client 생성
         │
         ▼
    for 조건 in CONDITIONS:
       build_prompt(PROFILE, 조건, RAW_TREE)   ── prompt_builder.py 사용
             │
             ▼
       client.models.generate_content(...)    ── 실제 Gemini 호출
             │
             ▼
       JSON 파싱 → validate_response(...)     ── prompt_builder.py 사용
             │
             ▼
       결과 축적
         │
         ▼
    요약 표 출력 + experiment_results.json 저장
"""

from __future__ import annotations

# json : Gemini 응답 문자열을 파이썬 dict로 바꾸거나, 결과 파일을 저장할 때.
import json
# sys  : 프로그램 종료 코드를 전달할 때(sys.exit).
import sys
# typing: 함수의 타입 힌트용. 동작엔 영향 없음.
from typing import Any, Dict, List, Optional

# Gemini 공식 SDK. "google-genai" 패키지를 설치해 두면 쓸 수 있다.
#   genai        : Client 등 주요 입구
#   genai.types  : GenerateContentConfig 등 설정 객체
from google import genai
from google.genai import types

# prompt_builder.py에서 두 가지만 가져온다.
#   build_prompt     : 지시문을 조립하는 함수
#   validate_response: Gemini 답을 검증하는 함수
from prompt_builder import build_prompt, validate_response
# test_prompt_builder.py에 들어있는 가짜 PROFILE/RAW_TREE를 재활용.
# (실제 서비스에서는 미디어 엔진 + UI 입력에서 받아올 것)
from test_prompt_builder import PROFILE, RAW_TREE


# ---------------------------------------------------------------------------
# 설정 상수
# ---------------------------------------------------------------------------

# Gemini 모델명. 사용자가 터미널에서 직접 확인한 "응답이 바로 오는" 모델.
MODEL = "gemini-3.5-flash"
# API 키를 담은 평문 파일의 경로. gitignore 되어 있어야 함.
KEY_PATH = "gemini_key.txt"


# ---------------------------------------------------------------------------
# 실험 조건 - 4가지
# ---------------------------------------------------------------------------
# 하나의 조건 = { "label": 표시용 이름, "request": prompt_builder가 받는 request dict }
# 조건을 바꿔보면서 "같은 트리/프로필에 대해 Gemini가 어떻게 다르게 고르는지"를
# 비교해 볼 수 있다.
CONDITIONS: List[Dict[str, Any]] = [
    {
        "label": "1) partial / 3분",
        "request": {
            # partial 모드: 꼭 넣을 노드/뺄 노드를 사용자가 지정한 상태로 보완 편집.
            "mode": "partial",
            "locked_nodes": ["intro-hook", "tip-2"],   # 반드시 포함
            "excluded_nodes": ["outro-next"],           # 반드시 제외
            "purpose": "쇼츠용 핵심 요약",
            "target_minutes": 3,
            "tone": "경쾌하고 빠르게",
            "must_include": ["꿀팁"],
            "must_exclude": ["광고"],
        },
    },
    {
        "label": "2) auto / 2분 / 임팩트",
        "request": {
            # auto 모드: Gemini에게 전부 맡김 (locked/excluded는 비움).
            "mode": "auto",
            "locked_nodes": [],
            "excluded_nodes": [],
            "purpose": "틱톡용 하이라이트 자동 선정",
            "target_minutes": 2,
            "tone": "임팩트 있게",
            "must_include": [],
            "must_exclude": [],
        },
    },
    {
        "label": "3) auto / 4분 / 임팩트",
        "request": {
            # 같은 톤이지만 목표 분량만 2 → 4분으로 늘려본다.
            "mode": "auto",
            "locked_nodes": [],
            "excluded_nodes": [],
            "purpose": "틱톡용 하이라이트 자동 선정",
            "target_minutes": 4,
            "tone": "임팩트 있게",
            "must_include": [],
            "must_exclude": [],
        },
    },
    {
        "label": "4) auto / 2분 / 차분한 정보 전달",
        "request": {
            # 2번 조건과 분량은 같지만 톤/목적이 다르다 → 선택되는 장면이 달라지는지 비교.
            "mode": "auto",
            "locked_nodes": [],
            "excluded_nodes": [],
            "purpose": "차분한 정보 전달용 요약",
            "target_minutes": 2,
            "tone": "차분하게 정보 전달",
            "must_include": [],
            "must_exclude": [],
        },
    },
]


# ---------------------------------------------------------------------------
# 응답 전처리 유틸
# ---------------------------------------------------------------------------

def _strip_code_fence(text: str) -> str:
    """Gemini가 응답을 ```json ... ``` 로 감쌀 경우를 대비한 간단한 벗기기.

    [무엇을 하는지]
      문자열 앞뒤의 코드 펜스(```json ... ```)를 제거한다.
      JSON 강제 옵션을 썼더라도 가끔 모델이 코드블록을 두르는 경우가 있어서
      파싱 전에 한 번 다듬어 둔다.
    """
    s = text.strip()
    if s.startswith("```json"):
        s = s[7:]      # "```json" 길이 = 7
    elif s.startswith("```"):
        s = s[3:]      # "```" 길이 = 3
    if s.endswith("```"):
        s = s[:-3]     # 끝의 "```" 떼기
    return s.strip()


def _parse_selected_ids(raw: str) -> (Optional[List[str]], Optional[Dict[str, str]], Optional[str]):
    """(selected_ids, reasons, parse_error) 반환.

    [무엇을 하는지]
      Gemini의 raw 응답 문자열을 JSON으로 파싱해서 selected_ids / reasons를
      꺼낸다. 실패하면 (None, None, "에러 설명")을 돌려줘서 호출자가
      "파싱 실패"임을 알 수 있게 한다.

    [반환]
      (selected_ids, reasons, parse_error)
      · 성공: (["intro-hook", ...], {"intro-hook": "...", ...}, None)
      · 실패: (None, None, "원인 설명")
    """
    if not raw or not raw.strip():
        return None, None, "빈 응답"
    try:
        # 코드블록을 벗기고 json.loads로 파이썬 객체로 바꾼다.
        obj = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as e:
        return None, None, f"JSONDecodeError: {e}"
    if not isinstance(obj, dict):
        return None, None, f"응답이 JSON 객체가 아님 (type={type(obj).__name__})"
    sel = obj.get("selected_ids")
    if not isinstance(sel, list):
        return None, None, "selected_ids 필드가 배열이 아님"
    reasons = obj.get("reasons")
    # reasons가 dict가 아니면 None으로 통일. (안전하게 쓰기 위함)
    reasons = {str(k): str(v) for k, v in reasons.items()} if isinstance(reasons, dict) else None
    # 모든 id를 str로 통일해서 돌려준다. (Gemini가 숫자로 뱉어도 str로 맞춤)
    return [str(x) for x in sel], reasons, None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    """실험 스크립트의 입구.

    [무엇을 하는지]
      1) gemini_key.txt에서 API 키를 읽어 Client를 만든다.
      2) CONDITIONS를 하나씩 돌면서 Gemini에 지시문을 보내고 결과를 모은다.
      3) 결과를 콘솔에 표로 요약하고, experiment_results.json으로 저장한다.
    """
    # 1) API 키 로드 + Client 생성.
    #    (가장 단순한 방식 - 사용자가 터미널에서 확인한 그 호출 패턴 그대로)
    api_key = open(KEY_PATH).read().strip()
    client = genai.Client(api_key=api_key)
    print(f"🤖 사용 모델: {MODEL}")

    results: List[Dict[str, Any]] = []
    # 2) 조건마다 하나씩 Gemini 호출.
    for cond in CONDITIONS:
        label = cond["label"]
        request = cond["request"]
        print(f"\n--- {label} ---")

        # 2-a) 지시문 조립. manual 모드면 None이 돌아와서 스킵.
        prompt = build_prompt(PROFILE, request, RAW_TREE)
        if prompt is None:
            print("  (manual 모드 - 스킵)")
            results.append({"label": label, "request": request, "skipped": True})
            continue

        # 2-b) 실제 Gemini 호출. response_mime_type="application/json"으로
        #      "JSON만 뱉어라"를 강제. (코드 펜스로 감싸는 경우는 _strip_code_fence로 흡수)
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        # getattr(obj, "text", 기본값): obj.text가 있으면 그 값, 없으면 "" 반환.
        # "or """: None이거나 빈 문자열이면 ""로 통일.
        raw = getattr(response, "text", "") or ""

        print("  [응답 원문]")
        print(raw)

        # 2-c) 파싱. 실패해도 "원문은 이미 출력했으니" 그걸로 디버깅 가능.
        selected_ids, reasons, parse_error = _parse_selected_ids(raw)
        validation = None
        if selected_ids is not None:
            # 2-d) 검증. prompt_builder의 validate_response를 그대로 사용.
            validation = validate_response(selected_ids, request, RAW_TREE)
            print(
                f"  [검증] selected_ids={selected_ids} "
                f"total={validation['total_duration_sec']}s "
                f"ratio={validation['duration_ratio']} ok={validation['ok']}"
            )
        else:
            print(f"  ⚠️ 파싱 실패: {parse_error}")

        # 이 조건의 결과를 통째로 저장.
        results.append({
            "label": label,
            "request": request,
            "prompt": prompt,
            "raw_response": raw,
            "selected_ids": selected_ids,
            "reasons": reasons,
            "parse_error": parse_error,
            "validation": validation,
        })

    # 3-a) 요약 표 출력
    print("\n" + "=" * 72)
    print("  실험 결과 요약")
    print("=" * 72)
    headers = ("조건", "선택된 id", "총 길이(s)", "목표비율", "검증")
    rows = []
    for r in results:
        if r.get("skipped"):
            rows.append((r["label"], "(skipped)", "-", "-", "-"))
            continue
        if r.get("selected_ids") is None:
            rows.append((r["label"], "(parse_error)", "-", "-", "FAIL"))
            continue
        v = r["validation"] or {}
        rows.append((
            r["label"],
            # 선택된 id가 비었으면 "(비어있음)"으로 표시.
            ", ".join(r["selected_ids"]) or "(비어있음)",
            f"{v.get('total_duration_sec', 0):.1f}",
            f"{v.get('duration_ratio', 0):.2f}",
            "PASS" if v.get("ok") else "FAIL",
        ))
    # 각 컬럼 폭을 "제일 긴 셀 길이"로 맞춰 표를 정렬.
    all_rows = [headers] + rows
    widths = [max(len(str(row[i])) for row in all_rows) for i in range(len(headers))]
    # lambda는 "한 줄짜리 익명 함수". 여기선 "한 행을 가지런한 문자열로 만드는" 함수.
    fmt = lambda row: "  ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers)))
    print(fmt(headers))
    print("-" * (sum(widths) + 2 * (len(headers) - 1)))
    for row in rows:
        print(fmt(row))

    # 3-b) 결과 저장
    #      with open(...) 블록을 벗어나면 파일이 자동으로 닫힌다 → 깔끔.
    out = "experiment_results.json"
    with open(out, "w", encoding="utf-8") as f:
        # ensure_ascii=False: 한글이 \uXXXX 로 깨지지 않고 그대로 저장되도록.
        # indent=2: 사람이 읽기 좋게 2칸 들여쓰기.
        json.dump({"model": MODEL, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"\n💾 결과를 '{out}'에 저장했습니다.")

    return 0


if __name__ == "__main__":
    # python experiment.py 로 직접 실행했을 때만 main()을 돈다.
    # (다른 파일에서 import할 때는 자동으로 실행되지 않음)
    sys.exit(main())
