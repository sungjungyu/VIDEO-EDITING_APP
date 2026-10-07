#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiment.py

build_prompt로 만든 지시문을 Gemini(gemini-3.5-flash)에 바로 보내고
validate_response로 검증하는 단순 실험 스크립트.

- Gemini 호출은 google.genai를 직접 사용 (main.py 재사용 X)
- 연결 확인/스레드/타임아웃/토큰 제한 전부 없음
- 4개 조건을 순서대로 실행하고 조건마다 응답 원문 + 검증 결과를 즉시 출력
- 마지막에 요약 표 출력 + experiment_results.json 저장
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

from prompt_builder import build_prompt, validate_response
from test_prompt_builder import PROFILE, RAW_TREE


MODEL = "gemini-3.5-flash"
KEY_PATH = "gemini_key.txt"


CONDITIONS: List[Dict[str, Any]] = [
    {
        "label": "1) partial / 3분",
        "request": {
            "mode": "partial",
            "locked_nodes": ["intro-hook", "tip-2"],
            "excluded_nodes": ["outro-next"],
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


def _strip_code_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


def _parse_selected_ids(raw: str) -> (Optional[List[str]], Optional[Dict[str, str]], Optional[str]):
    """(selected_ids, reasons, parse_error) 반환."""
    if not raw or not raw.strip():
        return None, None, "빈 응답"
    try:
        obj = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as e:
        return None, None, f"JSONDecodeError: {e}"
    if not isinstance(obj, dict):
        return None, None, f"응답이 JSON 객체가 아님 (type={type(obj).__name__})"
    sel = obj.get("selected_ids")
    if not isinstance(sel, list):
        return None, None, "selected_ids 필드가 배열이 아님"
    reasons = obj.get("reasons")
    reasons = {str(k): str(v) for k, v in reasons.items()} if isinstance(reasons, dict) else None
    return [str(x) for x in sel], reasons, None


def main() -> int:
    api_key = open(KEY_PATH).read().strip()
    client = genai.Client(api_key=api_key)
    print(f"🤖 사용 모델: {MODEL}")

    results: List[Dict[str, Any]] = []
    for cond in CONDITIONS:
        label = cond["label"]
        request = cond["request"]
        print(f"\n--- {label} ---")

        prompt = build_prompt(PROFILE, request, RAW_TREE)
        if prompt is None:
            print("  (manual 모드 - 스킵)")
            results.append({"label": label, "request": request, "skipped": True})
            continue

        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        raw = getattr(response, "text", "") or ""

        print("  [응답 원문]")
        print(raw)

        selected_ids, reasons, parse_error = _parse_selected_ids(raw)
        validation = None
        if selected_ids is not None:
            validation = validate_response(selected_ids, request, RAW_TREE)
            print(
                f"  [검증] selected_ids={selected_ids} "
                f"total={validation['total_duration_sec']}s "
                f"ratio={validation['duration_ratio']} ok={validation['ok']}"
            )
        else:
            print(f"  ⚠️ 파싱 실패: {parse_error}")

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

    # 요약 표
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
            ", ".join(r["selected_ids"]) or "(비어있음)",
            f"{v.get('total_duration_sec', 0):.1f}",
            f"{v.get('duration_ratio', 0):.2f}",
            "PASS" if v.get("ok") else "FAIL",
        ))
    all_rows = [headers] + rows
    widths = [max(len(str(row[i])) for row in all_rows) for i in range(len(headers))]
    fmt = lambda row: "  ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers)))
    print(fmt(headers))
    print("-" * (sum(widths) + 2 * (len(headers) - 1)))
    for row in rows:
        print(fmt(row))

    # 저장
    out = "experiment_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"model": MODEL, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"\n💾 결과를 '{out}'에 저장했습니다.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
