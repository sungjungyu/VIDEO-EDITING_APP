#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scene_selector.py
=================

[이 파일의 역할]
----------------
"편집 시작" 버튼을 눌렀을 때 서버가 호출하는 '장면 선택기' 모듈이다.
사용자의 모드(manual/partial/auto)에 따라 다음 중 하나를 수행한다.

  1) manual 모드:
       사용자가 트리에서 체크해 보낸 selected_nodes를 그대로 결과로 삼고,
       validate_response만 돌려서 검증 결과를 함께 돌려준다.
       (Gemini 호출 없음)

  2) partial / auto 모드:
       prompt_builder.build_prompt로 지시문을 만들어 Gemini에 보낸 뒤
       응답(JSON)을 파싱하고 validate_response로 검증한다.
       검증 실패 시, 오류 내용을 지시문에 덧붙여 '한 번만' 재시도한다.

[데이터 흐름]
    요청(profile, request, tree)
             │
             ▼
    normalize_tree          ← 트리를 내부 포맷으로 통일
             │
             ├── manual 모드 ─→ _manual_selected_ids
             │                       │
             │                       ▼
             │                 validate_response
             │
             └── partial/auto ─→ build_prompt
                                    │
                                    ▼
                              Gemini 호출(_call_gemini)
                                    │
                                    ▼
                              _parse_response (JSON 파싱)
                                    │
                                    ▼
                              validate_response
                                    │
                                    ├── 통과 → 결과 반환
                                    │
                                    └── 실패 → 오류 피드백 덧붙여 1회 재시도
                                                 │
                                                 ▼
                                        최종 결과 반환

[반환 포맷]
    {
        "ok":          bool,                       # 최종 검증 통과 여부
        "selected_ids": [str, ...],                # 선택된 장면 id들
        "reasons":     {"<id>": "<이유 문자열>"},  # AI가 돌려준 선택 이유
        "validation":  {prompt_builder.validate_response의 결과 dict}
    }
"""

from __future__ import annotations

# json : Gemini 응답 문자열을 파이썬 dict로 바꿀 때 쓴다.
import json
# typing : 함수 시그니처의 타입 힌트. 동작엔 영향 없음.
from typing import Any, Dict, List

# Gemini SDK. experiment.py에서 쓴 것과 같다.
from google import genai
from google.genai import types

# prompt_builder의 공개 함수들만 가져온다.
from prompt_builder import build_prompt, normalize_tree, validate_response


# ---------------------------------------------------------------------------
# 설정 상수
# ---------------------------------------------------------------------------
# 모델명은 experiment.py와 같다.
MODEL_NAME = "gemini-3.5-flash"
# API 키 파일 경로. (gitignore 되어 있어야 함)
API_KEY_PATH = "gemini_key.txt"


# ---------------------------------------------------------------------------
# Gemini 호출 유틸
# ---------------------------------------------------------------------------

def _load_api_key() -> str:
    """gemini_key.txt에서 API 키를 읽어 문자열로 돌려준다.

    [입력]  없음
    [출력]  API 키 문자열 (예: "AIza...")
    [예시]  key = _load_api_key()
    """
    with open(API_KEY_PATH, "r", encoding="utf-8") as f:
        return f.read().strip()


def _make_gemini_client() -> genai.Client:
    """gemini_key.txt를 읽어 Gemini Client를 하나 만들어 돌려준다.

    [입력]  없음
    [출력]  genai.Client 객체
    [예시]  client = _make_gemini_client()
    """
    api_key = _load_api_key()
    return genai.Client(api_key=api_key)


def _call_gemini(client: genai.Client, prompt: str) -> str:
    """Gemini를 한 번 호출하고 응답 텍스트를 돌려준다.

    [입력]
      client : _make_gemini_client()이 돌려준 Client
      prompt : 보낼 지시문 문자열

    [출력]  Gemini의 응답 텍스트 (문자열)
    [예시]
      raw = _call_gemini(client, "...지시문...")
      → '{"selected_ids": ["intro-hook"], "reasons": {...}}'
    """
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    text = getattr(response, "text", "")
    if text is None:
        return ""
    return text


# ---------------------------------------------------------------------------
# 응답 파싱 유틸
# ---------------------------------------------------------------------------

def _strip_code_fence(text: str) -> str:
    """Gemini 응답이 ```json ... ``` 로 감싸져 있으면 벗겨 낸다.

    [입력]  "```json\\n{...}\\n```" 같은 문자열
    [출력]  코드 펜스가 제거된 깔끔한 문자열
    [예시]  "```json\\n{\"a\":1}\\n```" → '{"a":1}'
    """
    stripped = text.strip()
    if stripped.startswith("```json"):
        stripped = stripped[7:]
    elif stripped.startswith("```"):
        stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()


def _parse_response(raw_text: str) -> Dict[str, Any]:
    """Gemini의 응답 텍스트를 파이썬 dict로 바꿔서 돌려준다.

    [입력]  raw_text : Gemini가 돌려준 응답 문자열

    [출력]
      성공 시 : {
          "selected_ids": [str, ...],
          "reasons":      {str: str, ...},
          "parse_error":  None,
      }
      실패 시 : {
          "selected_ids": [],
          "reasons":      {},
          "parse_error":  "원인 설명",
      }

    [예시]
      _parse_response('{"selected_ids":["a"], "reasons":{"a":"좋음"}}')
        → {"selected_ids": ["a"], "reasons": {"a": "좋음"}, "parse_error": None}
    """
    if not raw_text or not raw_text.strip():
        return {"selected_ids": [], "reasons": {}, "parse_error": "빈 응답"}

    cleaned = _strip_code_fence(raw_text)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as error:
        return {
            "selected_ids": [],
            "reasons": {},
            "parse_error": f"JSON 파싱 실패: {error}",
        }

    if not isinstance(parsed, dict):
        return {
            "selected_ids": [],
            "reasons": {},
            "parse_error": "응답이 JSON 객체가 아님",
        }

    sel = parsed.get("selected_ids")
    if not isinstance(sel, list):
        return {
            "selected_ids": [],
            "reasons": {},
            "parse_error": "selected_ids 필드가 배열이 아님",
        }

    # 모든 id를 문자열로 통일한다. (Gemini가 숫자로 돌려줘도 str로 맞춤)
    selected_ids: List[str] = []
    for value in sel:
        selected_ids.append(str(value))

    # reasons는 dict가 아니면 빈 dict로.
    reasons: Dict[str, str] = {}
    reasons_raw = parsed.get("reasons")
    if isinstance(reasons_raw, dict):
        for key, value in reasons_raw.items():
            reasons[str(key)] = str(value)

    return {
        "selected_ids": selected_ids,
        "reasons": reasons,
        "parse_error": None,
    }


# ---------------------------------------------------------------------------
# manual 모드용 유틸
# ---------------------------------------------------------------------------

def _manual_selected_ids(request: Dict[str, Any]) -> List[str]:
    """manual 모드에서 '사용자가 고른 노드 id'들을 돌려준다.

    프론트엔드가 트리에서 체크한 노드 id를 request.selected_nodes에 담아
    보내므로, 그 값을 문자열 리스트로 그대로 돌려준다.

    [입력]
      request : 이번 요청 dict (selected_nodes 포함)

    [출력]
      사용자가 고른 노드 id들의 리스트 (문자열)

    [예시]
      request == {"selected_nodes": ["intro", "body"]}
      → ["intro", "body"]
    """
    selected_raw = request.get("selected_nodes") or []

    selected: List[str] = []
    for value in selected_raw:
        selected.append(str(value))
    return selected


# ---------------------------------------------------------------------------
# 재시도용 프롬프트 유틸
# ---------------------------------------------------------------------------

def _append_error_feedback(original_prompt: str, errors: List[str]) -> str:
    """검증 실패 시, 오류 내용을 지시문 뒤에 덧붙인 '재시도 지시문'을 만든다.

    [입력]
      original_prompt : 처음 보냈던 지시문
      errors          : validate_response가 돌려준 errors 리스트

    [출력]
      오류 피드백이 덧붙여진 새 지시문 문자열

    [예시]
      _append_error_feedback("지시문", ["고정 노드 누락: ['tip-2']"])
      → "지시문\\n\\n[이전 응답의 검증 오류]\\n- 고정 노드 누락: ['tip-2']\\n\\n..."
    """
    feedback_lines: List[str] = []
    feedback_lines.append("")
    feedback_lines.append("[이전 응답의 검증 오류]")
    for err in errors:
        feedback_lines.append(f"- {err}")
    feedback_lines.append("")
    feedback_lines.append(
        "위 오류를 모두 고쳐서 다시 selected_ids와 reasons를 JSON으로만 응답하라."
    )
    return original_prompt + "\n" + "\n".join(feedback_lines)


# ---------------------------------------------------------------------------
# 메인 함수
# ---------------------------------------------------------------------------

def _result_dict(
    ok: bool,
    selected_ids: List[str],
    reasons: Dict[str, str],
    validation: Dict[str, Any],
) -> Dict[str, Any]:
    """최종 반환 dict를 만들어 돌려준다.

    [무엇을 하는지]
      반환 포맷을 한 곳에서 조립해 "똑같은 모양"으로 돌려주기 위한 헬퍼.

    [입력]
      ok           : 최종 통과 여부
      selected_ids : 선택된 id들
      reasons      : 선택 이유 (id→문자열)
      validation   : prompt_builder.validate_response의 결과

    [출력]
      {"ok":..., "selected_ids":..., "reasons":..., "validation":...}
    """
    return {
        "ok": ok,
        "selected_ids": selected_ids,
        "reasons": reasons,
        "validation": validation,
    }


def _run_gemini_once(
    client: genai.Client,
    prompt: str,
    request: Dict[str, Any],
    normalized_tree: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Gemini 한 번 호출 + 파싱 + 검증까지 묶어서 결과를 돌려준다.

    [무엇을 하는지]
      "지시문 전송 → 응답 파싱 → 검증" 세 단계를 한 번에 처리한다.
      첫 호출과 재시도 호출이 똑같은 흐름이라 함수로 뽑아 두었다.

    [입력]
      client          : Gemini Client
      prompt          : 보낼 지시문
      request         : 이번 요청 dict (검증에 필요)
      normalized_tree : 정규화된 트리 (검증에 필요)

    [출력]
      {
        "selected_ids": [...],
        "reasons":      {...},
        "validation":   {...},   # 파싱 실패 시 errors에 그 이유가 들어감
      }
    """
    raw_text = _call_gemini(client, prompt)
    parsed = _parse_response(raw_text)

    # 파싱이 실패하면, "검증 실패" 모양으로 바꿔서 돌려준다.
    # 이렇게 하면 호출자가 파싱 실패와 검증 실패를 똑같이 다룰 수 있다.
    if parsed["parse_error"] is not None:
        fake_validation: Dict[str, Any] = {
            "ok": False,
            "errors": [parsed["parse_error"]],
            "warnings": [],
            "unknown_ids": [],
            "missing_locked": [],
            "included_excluded": [],
            "total_duration_sec": 0.0,
            "target_sec": 0.0,
            "duration_ratio": 0.0,
            "within_tolerance": False,
        }
        return {
            "selected_ids": [],
            "reasons": {},
            "validation": fake_validation,
        }

    selected_ids = parsed["selected_ids"]
    reasons = parsed["reasons"]
    validation = validate_response(selected_ids, request, normalized_tree)
    return {
        "selected_ids": selected_ids,
        "reasons": reasons,
        "validation": validation,
    }


def select_scenes(
    profile: Dict[str, Any],
    request: Dict[str, Any],
    tree: Any,
) -> Dict[str, Any]:
    """편집 시작 버튼이 눌렸을 때 서버가 호출하는 메인 함수.

    [무엇을 하는지]
      모드(manual/partial/auto)에 따라 아래를 수행한다.
        - manual : Gemini 호출 없이, 사용자가 고른 노드로 validate_response만 돌림
        - partial/auto : prompt_builder로 지시문을 조립 → Gemini 호출
                         → 응답 파싱 → 검증 → 실패하면 한 번만 재시도

    [입력]
      profile : 사용자 편집 스타일 dict (예: {"cut_tempo": "빠름"})
      request : 이번 요청 dict (예: {"mode":"partial","target_minutes":3,...})
      tree    : 장면 트리 (정규화 전/후 모두 OK)

    [출력]
      {
        "ok":          bool,
        "selected_ids": [str, ...],
        "reasons":     {"<id>": "<이유 문자열>"},
        "validation":  {prompt_builder.validate_response의 결과 dict}
      }

    [예시]
      result = select_scenes({}, {"mode": "manual", "target_minutes": 2}, tree)
      result["selected_ids"] → ["intro", "body", ...]
      result["ok"]           → True / False
    """
    # 1) 입력 정리.
    safe_profile: Dict[str, Any] = profile or {}
    safe_request: Dict[str, Any] = request or {}
    mode = safe_request.get("mode", "auto")
    normalized_tree = normalize_tree(tree)

    # 2) manual 모드: Gemini를 쓰지 않고 사용자가 고른 id로 바로 검증한다.
    #    (selected_nodes를 그대로 결과로 쓰고 validate_response만 실행)
    if mode == "manual":
        manual_ids = _manual_selected_ids(safe_request)
        manual_validation = validate_response(
            manual_ids, safe_request, normalized_tree
        )
        return _result_dict(
            ok=manual_validation["ok"],
            selected_ids=manual_ids,
            reasons={},
            validation=manual_validation,
        )

    # 3) partial / auto 모드: Gemini에 지시문을 보낸다.
    prompt = build_prompt(safe_profile, safe_request, normalized_tree)
    if prompt is None:
        # build_prompt가 None을 돌려주는 경우는 지금은 manual뿐이지만,
        # 혹시 모를 "지원 안 되는 모드" 상황을 안전하게 거른다.
        empty_validation: Dict[str, Any] = {
            "ok": False,
            "errors": [f"지원하지 않는 모드: {mode}"],
            "warnings": [],
            "unknown_ids": [],
            "missing_locked": [],
            "included_excluded": [],
            "total_duration_sec": 0.0,
            "target_sec": 0.0,
            "duration_ratio": 0.0,
            "within_tolerance": False,
        }
        return _result_dict(
            ok=False,
            selected_ids=[],
            reasons={},
            validation=empty_validation,
        )

    client = _make_gemini_client()

    # 4) 첫 호출.
    first = _run_gemini_once(client, prompt, safe_request, normalized_tree)
    if first["validation"]["ok"]:
        return _result_dict(
            ok=True,
            selected_ids=first["selected_ids"],
            reasons=first["reasons"],
            validation=first["validation"],
        )

    # 5) 검증 실패 → 오류 피드백을 덧붙여 '한 번만' 재시도.
    retry_prompt = _append_error_feedback(prompt, first["validation"]["errors"])
    retry = _run_gemini_once(client, retry_prompt, safe_request, normalized_tree)
    return _result_dict(
        ok=retry["validation"]["ok"],
        selected_ids=retry["selected_ids"],
        reasons=retry["reasons"],
        validation=retry["validation"],
    )


# "from scene_selector import *" 했을 때 바깥에 노출되는 이름 목록.
__all__ = ["select_scenes"]
