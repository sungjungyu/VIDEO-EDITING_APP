#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_builder.py
==================

[이 파일의 역할 - 큰 그림]
---------------------------
VIBECUT(영상 자동 편집) 서비스에서 "Gemini에게 어떤 장면을 고르라고 시킬지"
지시문(= 프롬프트)을 만들어 주는 모듈이다.

사용자가 영상을 올리면 미디어 엔진이 "장면 트리"를 뽑아내고, 사용자는 UI에서
"3분짜리 쇼츠로", "친구 얼굴 나오는 부분은 빼줘" 같은 요청을 자유 글(user_prompt)
로 입력한다. 이 모듈은 그 둘(장면 트리 + 요청)을 합쳐서 Gemini가 읽기 좋은
하나의 긴 문자열로 조립한다. 그리고 Gemini가 돌려준 답(selected_ids)이 요청에
맞는지도 여기서 검증한다.

[요청(request) 형식 - 아주 단순해졌음]
---------------------------------------
    {
        "mode":           "auto" | "manual",
        "target_minutes": 3,
        "user_prompt":    "쇼츠용으로 재밌는 장면 위주로, 친구 얼굴은 빼줘",
        "selected_nodes": ["intro-hook", "tip-2", ...]   # manual 모드에서만 의미
    }

- auto 모드: Gemini가 user_prompt와 목표 분량에 맞춰 전부 고른다.
- manual 모드: 사용자가 트리에서 직접 체크한 selected_nodes가 결과가 된다.

[전체 서비스에서 이 파일이 하는 일 - 흐름]
------------------------------------------
    [미디어 엔진]              [사용자 UI 입력]
   (장면 트리 뽑기)         (목표 분량, 사용자 요청 글)
         │                           │
         └────────┬──────────────────┘
                  ▼
          [prompt_builder]
            build_prompt()  ← 이 파일의 핵심
                  │
                  ▼
            [Gemini API] ── 긴 지시문을 보내면 selected_ids를 돌려줌
                  │
                  ▼
          [prompt_builder]
         validate_response() ← Gemini 답이 올바른지 검사
                  │
                  ▼
        [미디어 엔진이 선택된 장면을 실제로 자름]


[내부 트리 노드 스키마 - 이 모듈이 다루는 "정규화된" 노드 형태]
--------------------------------------------------------------
    {
        "id":       str,           # 고유 식별자 (예: "intro-hook")
        "title":    str,           # 장면/구간 제목
        "start":    float,         # 시작 초
        "end":      float,         # 종료 초
        "summary":  str (optional),
        "tags":     list[str] (optional),
        "children": list[node]     # 하위 장면들 (재귀 구조)
    }
"""

from __future__ import annotations

# typing은 함수 시그니처에 타입 힌트를 적기 위한 import.
#   Any       = 아무 타입이나 가능
#   Dict      = 딕셔너리(사전)
#   Iterable  = 한 개씩 꺼낼 수 있는 것 (list/tuple/set 등)
#   List      = 리스트
#   Optional  = None도 될 수 있음
#   Set       = 집합(중복 없는 모음)
#   Tuple     = 튜플(길이 고정 모음)
from typing import Any, Dict, Iterable, List, Optional, Tuple, Set


# ---------------------------------------------------------------------------
# 트리 정규화
# ---------------------------------------------------------------------------
# ★ 공부 포인트: 왜 "정규화"가 필요한가?
#   팀 A는 노드 id를 "id"라고 부르고, 팀 B는 "node_id"라고 부를 수 있다.
#   매번 코드에서 if "id" in n elif "node_id" in n ... 로 분기하면 금방
#   지저분해진다. 그래서 "데이터가 들어오자마자 한 번만" 우리 내부 포맷으로
#   바꾸고, 그 뒤의 모든 함수는 내부 포맷만 가정하도록 하면 깔끔해진다.
#   → 외부 포맷이 바뀌면 아래 _FIELD_ALIASES 표만 바꾸면 끝.

# 외부 포맷에서 받을 수 있는 필드명 후보.
_FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "id":       ("id", "node_id", "uid", "key"),
    "title":    ("title", "name", "label"),
    "start":    ("start", "start_sec", "start_time", "from"),
    "end":      ("end", "end_sec", "end_time", "to"),
    "summary":  ("summary", "description", "desc"),
    "tags":     ("tags", "labels", "keywords"),
    "children": ("children", "nodes", "subs", "sub_nodes"),
}


def _pick(raw: Dict[str, Any], key: str, default: Any = None) -> Any:
    """raw 딕셔너리에서 key에 해당하는 값을 별칭들까지 포함해 찾는다.

    [무엇을 하는지]
      raw에 "id"가 없어도 "node_id"가 있으면 그 값을 돌려준다.
      즉, _FIELD_ALIASES에 정의된 별칭들 중 가장 먼저 발견되는 걸 반환.

    [입력]
      raw     : 노드 하나 (dict)        예) {"node_id": "intro", ...}
      key     : 내부 포맷 이름           예) "id", "start"
      default : 어떤 별명으로도 못 찾았을 때 돌려줄 기본값

    [출력]
      찾은 값, 또는 default
    """
    for alias in _FIELD_ALIASES[key]:
        if alias in raw:
            return raw[alias]
    return default


def _normalize_node(raw: Dict[str, Any]) -> Dict[str, Any]:
    """한 노드를 내부 포맷으로 변환한다.

    [무엇을 하는지]
      외부 노드 하나를 받아 우리 내부 포맷(id/title/start/end/children)의
      "새 딕셔너리"를 만들어 돌려준다. children이 있으면 재귀적으로 각 자식도
      똑같이 변환한다.

    [입력]  외부 포맷의 노드 하나 (dict)
            예) {"node_id": "intro", "name": "오프닝", "start_sec": 0, "end_sec": 30}
    [출력]  내부 포맷의 노드 하나 (새로 만든 dict)
            예) {"id": "intro", "title": "오프닝", "start": 0.0, "end": 30.0, "children": []}
    """
    node_id = _pick(raw, "id")
    title = _pick(raw, "title", "")
    start = _pick(raw, "start", 0)
    end = _pick(raw, "end", 0)
    summary = _pick(raw, "summary")
    tags = _pick(raw, "tags")
    children = _pick(raw, "children", []) or []

    # 타입 보정: 문자열로 들어와도 float으로.
    try:
        start = float(start) if start is not None else 0.0
    except (TypeError, ValueError):
        start = 0.0
    try:
        end = float(end) if end is not None else 0.0
    except (TypeError, ValueError):
        end = 0.0

    normalized: Dict[str, Any] = {
        "id": str(node_id) if node_id is not None else "",
        "title": str(title) if title is not None else "",
        "start": start,
        "end": end,
        "children": [_normalize_node(c) for c in children],
    }
    if summary is not None:
        normalized["summary"] = str(summary)
    if tags is not None:
        if isinstance(tags, (list, tuple, set)):
            normalized["tags"] = [str(t) for t in tags]
        else:
            normalized["tags"] = [str(tags)]
    return normalized


def normalize_tree(raw_tree: Any) -> List[Dict[str, Any]]:
    """외부에서 받은 트리를 내부 포맷(루트 노드들의 리스트)으로 변환.

    [입력]  노드 하나(dict) 또는 노드들의 리스트
    [출력]  루트 노드들의 리스트 (항상 list[dict])

    [중요한 성질 - 멱등성]
      이미 내부 포맷인 트리에 또 돌려도 결과가 똑같다.

    [예시]
      normalize_tree({"node_id": "a", "start_sec": 0, "end_sec": 10})
        → [{"id": "a", "title": "", "start": 0.0, "end": 10.0, "children": []}]
    """
    if raw_tree is None:
        return []
    if isinstance(raw_tree, dict):
        return [_normalize_node(raw_tree)]
    if isinstance(raw_tree, list):
        return [_normalize_node(n) for n in raw_tree]
    raise TypeError(f"지원하지 않는 트리 입력 타입: {type(raw_tree).__name__}")


# ---------------------------------------------------------------------------
# 트리 순회 유틸
# ---------------------------------------------------------------------------

def _iter_nodes(tree: List[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    """트리 전체를 DFS(깊이 우선)로 순회하면서 노드를 하나씩 돌려준다.

    [입력]  정규화된 루트 리스트
    [출력]  노드들을 하나씩 (제너레이터)
    [예시]  for node in _iter_nodes(tree): print(node["id"])
    """
    for root in tree:
        stack = [root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.get("children", []))


def _build_index(tree: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """id → node 사전을 만든다 (빠른 조회용).

    [입력]  정규화된 트리
    [출력]  {"intro-hook": {...}, "tip-2": {...}, ...}
    """
    return {n["id"]: n for n in _iter_nodes(tree) if n.get("id")}


def _build_parent_map(tree: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """id → 부모 id 사전을 만든다 (루트는 None).

    [왜 필요한가]
      calc_duration에서 "선택된 노드의 조상 중 선택된 게 있으면 중복으로
      치지 말자"를 판정하기 위해 부모를 거슬러 올라갈 때 쓴다.

    [예시]
      _build_parent_map(tree) → {"intro": None, "intro-hook": "intro", ...}
    """
    parent_map: Dict[str, Optional[str]] = {}
    for root in tree:
        parent_map[root["id"]] = None
        stack: List[Tuple[Dict[str, Any], Optional[str]]] = [(root, None)]
        while stack:
            node, _ = stack.pop()
            for child in node.get("children", []):
                parent_map[child["id"]] = node["id"]
                stack.append((child, node["id"]))
    return parent_map


def _node_duration(node: Dict[str, Any]) -> float:
    """단일 노드의 길이(초).

    [입력]  노드 하나 (내부 포맷)
    [출력]  end - start (음수면 0.0)
    [예시]  _node_duration({"start": 10, "end": 25}) → 15.0
    """
    try:
        return max(0.0, float(node.get("end", 0)) - float(node.get("start", 0)))
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# 길이 계산
# ---------------------------------------------------------------------------

def calc_duration(node_ids: Iterable[str], tree: Any) -> float:
    """선택된 노드들의 총 길이(초)를 계산한다.

    [규칙 - 부모/자식 중복 방지]
      부모와 자식이 함께 선택되면 부모만 세고 자식은 더하지 않는다
      (부모 구간이 자식 구간을 포함한다고 간주).

    [입력]
      node_ids : 선택된 id들 (문자열의 iterable)
      tree     : 트리 (정규화 전/후 모두 OK)
    [출력]
      총 길이 (float, 초)

    [예시]
      calc_duration(["body", "tip-1"], tree) → body의 길이만 돌려줌
    """
    normalized = _ensure_normalized(tree)
    index = _build_index(normalized)
    parent_map = _build_parent_map(normalized)

    # 트리에 실제로 존재하는 id만 걸러낸다.
    requested: Set[str] = {nid for nid in node_ids if nid in index}

    # 조상 중 하나라도 선택돼 있으면 그 자식은 제외한다.
    effective: Set[str] = set()
    for nid in requested:
        p = parent_map.get(nid)
        covered = False
        while p is not None:
            if p in requested:
                covered = True
                break
            p = parent_map.get(p)
        if not covered:
            effective.add(nid)

    total = 0.0
    for nid in effective:
        total += _node_duration(index[nid])
    return total


def _ensure_normalized(tree: Any) -> List[Dict[str, Any]]:
    """항상 normalize_tree를 한 번 돌려서 돌려준다.

    [왜 필요한가]
      normalize_tree는 멱등(같은 결과)이라 두 번 돌려도 안전하고,
      "실수로 정규화를 건너뛰어 깨지는" 사고를 완전히 막는다.
    """
    return normalize_tree(tree)


# ---------------------------------------------------------------------------
# 프롬프트 조립
# ---------------------------------------------------------------------------
# 지시문은 큰 블록 네 개로 구성된다:
#   1) [시스템 규칙]   : Gemini가 지켜야 할 공통 규칙
#   2) [제작자 프로필] : 사용자의 평소 편집 스타일
#   3) [이번 영상 요청]: 모드/목표분량/사용자 요청 글
#   4) [장면 트리 요약]: 어떤 장면들이 있는지 보여주는 리스트

_SCHEMA_LINE = (
    '{ "selected_ids": ["<node_id>", ...], '
    '"reasons": {"<node_id>": "<선택 이유 한 줄>", ...} }'
)

# Gemini가 지켜야 할 공통 규칙.
_BASE_RULES = [
    "반드시 아래 JSON 스키마로만 응답한다. 다른 텍스트, 주석, 코드블록 금지.\n   "
    + _SCHEMA_LINE,
    "selected_ids는 제공된 트리에 실제로 존재하는 id만 사용한다.",
    "목표 분량(target_minutes)에 최대한 가깝게 선택한다. 오차는 ±10% 이내.",
    "부모 노드를 선택하면 그 모든 자식 구간이 포함된다고 간주한다.",
]


def _system_rules() -> str:
    """시스템 규칙 블록 문자열을 만든다.

    [입력]  없음
    [출력]  "너는 영상 편집용 ... 1) ... 2) ..." 같은 번호 매긴 규칙 문자열
    """
    header = "너는 영상 편집용 장면 선택 어시스턴트다. 아래 규칙을 반드시 지켜라."
    numbered = [f"{i+1}) {r}" for i, r in enumerate(_BASE_RULES)]
    return header + "\n" + "\n".join(numbered)


def _fmt_keywords(items: List[Any]) -> str:
    """리스트를 '꿀팁, 레전드' 형태의 문자열로 만든다.

    [입력]  문자열 리스트
    [출력]  쉼표로 이어붙인 문자열. 비어있으면 "(없음)"
    [예시]  _fmt_keywords(["a", "b"]) → "a, b"
    """
    if not items:
        return "(없음)"
    return ", ".join(str(x) for x in items)


def _format_profile(profile: Dict[str, Any]) -> str:
    """제작자 프로필 블록 문자열을 만든다.

    [무엇을 하는지]
      사용자의 평소 편집 스타일을 Gemini가 참고할 수 있도록 블록 문자열로.

    [입력]  profile dict (예: {"cut_tempo": "빠름", "filler_removal": "강",
                              "frequent_words": ["꿀팁"]})
    [출력]  "[제작자 프로필]\\n- 컷 템포: ..." 형식의 문자열
    """
    lines = ["[제작자 프로필]"]
    lines.append(f"- 컷 템포: {profile.get('cut_tempo', '지정 없음')}")
    lines.append(f"- 군말 제거 강도: {profile.get('filler_removal', '지정 없음')}")
    freq = list(profile.get("frequent_words") or [])
    lines.append(f"- 자주 쓰는 단어: {_fmt_keywords(freq)}")
    return "\n".join(lines)


def _summarize_tree(
    tree: List[Dict[str, Any]],
    max_depth: int = 3,
) -> str:
    """장면 트리를 들여쓰기된 리스트 문자열로 만든다.

    [무엇을 하는지]
      Gemini가 "어떤 장면들이 있는지" 한눈에 볼 수 있도록 트리를 요약한다.
      기본은 3단계까지(루트 depth 0 포함).

    [입력]
      tree      : 정규화된 루트 리스트
      max_depth : 들여쓰기 깊이 상한 (3이면 손자까지 표시)
    [출력]  여러 줄 문자열

    [예시]
        - [intro] 오프닝 (0.0-30.0s, 30.0s)
          - [intro-hook] 훅 멘트 (0.0-10.0s, 10.0s)
    """
    out: List[str] = []

    def walk(node: Dict[str, Any], depth: int) -> None:
        indent = "  " * depth
        dur = _node_duration(node)
        head = (
            f"{indent}- [{node['id']}] {node.get('title','')} "
            f"({node['start']:.1f}-{node['end']:.1f}s, {dur:.1f}s)"
        )
        if node.get("summary"):
            head += f" :: {node['summary']}"
        if node.get("tags"):
            head += f" #{','.join(node['tags'])}"
        out.append(head)

        for child in node.get("children", []):
            next_depth = depth + 1
            if next_depth < max_depth:
                walk(child, next_depth)

    for root in tree:
        walk(root, 0)
    return "\n".join(out) if out else "(트리 비어있음)"


def _format_request_block(request: Dict[str, Any]) -> str:
    """이번 요청 블록 문자열을 만든다.

    [무엇을 하는지]
      사용자가 넘긴 "이번 영상 요청"을 Gemini가 읽을 블록으로 바꾼다.
      새 포맷에서는 purpose/tone/키워드가 없고, user_prompt(사용자 요청 글)만 쓴다.

    [입력]
      request : {"mode": "auto", "target_minutes": 3,
                 "user_prompt": "쇼츠용으로 재밌는 장면 위주로"}
    [출력]  "[이번 영상 요청]\\n- 모드: auto\\n- 목표 분량: 3분\\n..." 문자열
    """
    mode = request.get("mode", "auto")
    target = float(request.get("target_minutes", 0) or 0)
    user_prompt = str(request.get("user_prompt", "") or "").strip()

    lines = ["[이번 영상 요청]"]
    lines.append(f"- 모드: {mode}")
    lines.append(f"- 목표 분량: {target}분")
    if user_prompt:
        lines.append(f"- 사용자 요청: {user_prompt}")
    else:
        lines.append("- 사용자 요청: (명시 없음)")
    lines.append("- auto 모드: 위 사용자 요청과 목표 분량에 맞춰 전부 선택하라.")
    return "\n".join(lines)


def build_prompt(
    profile: Dict[str, Any],
    request: Dict[str, Any],
    tree: Any,
) -> Optional[str]:
    """Gemini에 보낼 지시문을 조립한다.

    [무엇을 하는지]
      - manual 모드: AI 호출이 필요 없으므로 None 반환.
      - auto 모드: 목표 분량과 사용자 요청 글(user_prompt)만으로 전부
                   선택하도록 지시문을 만든다.

    지시문은 [시스템 규칙] / [제작자 프로필] / [이번 영상 요청] + [장면 트리 요약]
    순서로 구성된다.

    [입력]
      profile : 사용자 편집 스타일 dict (예: {"cut_tempo": "빠름"})
      request : {"mode": "auto"|"manual", "target_minutes": 3,
                 "user_prompt": "...", "selected_nodes": [...]}
      tree    : 장면 트리 (정규화 전/후 모두 OK)

    [출력]
      Gemini용 프롬프트 문자열, 또는 None (manual 모드)
    """
    mode = (request or {}).get("mode", "auto")
    if mode == "manual":
        return None

    normalized = _ensure_normalized(tree)
    request_block = _format_request_block(request or {})

    parts: List[str] = []
    parts.append("[시스템 규칙]")
    parts.append(_system_rules())
    parts.append("")
    parts.append(_format_profile(profile or {}))
    parts.append("")
    parts.append(request_block)
    parts.append("")
    parts.append("[장면 트리 요약]")
    parts.append(_summarize_tree(normalized, max_depth=3))
    parts.append("")
    parts.append("위 조건에 맞게 selected_ids와 reasons를 JSON으로만 응답하라.")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 응답 검증
# ---------------------------------------------------------------------------

def validate_response(
    selected_ids: Iterable[str],
    request: Dict[str, Any],
    tree: Any,
) -> Dict[str, Any]:
    """AI가 돌려준 selected_ids가 요청/트리에 맞는지 검사한다.

    [무엇을 하는지]
      다음 두 가지를 확인한다:
        1) 존재하지 않는 id가 섞여 있지 않은지
        2) 총 길이가 목표 분량의 ±10% 안인지

    [입력]
      selected_ids : AI가 돌려준 id들
      request      : {"target_minutes": 3, ...}
      tree         : 장면 트리

    [출력] dict
      {
          "ok": bool,
          "errors": [str, ...],
          "warnings": [str, ...],
          "unknown_ids": [str, ...],
          "total_duration_sec": float,
          "target_sec": float,
          "duration_ratio": float,
          "within_tolerance": bool
      }

    [예시]
      validate_response(["intro-hook"], {"target_minutes": 2}, tree)
        → {"ok": False, "errors": ["총 길이 부족: ..."], ...}
    """
    normalized = _ensure_normalized(tree)
    index = _build_index(normalized)

    selected = list(selected_ids or [])

    # 1) 존재하지 않는 id
    unknown_ids = sorted([sid for sid in selected if sid not in index])

    # 2) 길이 검사 (±10%)
    target_minutes = float((request or {}).get("target_minutes", 0) or 0)
    target_sec = target_minutes * 60.0
    known_selected = [sid for sid in selected if sid in index]
    total_duration = calc_duration(known_selected, normalized)
    ratio = (total_duration / target_sec) if target_sec > 0 else 0.0
    within_tolerance = (0.9 <= ratio <= 1.1) if target_sec > 0 else True

    errors: List[str] = []
    warnings: List[str] = []
    if unknown_ids:
        errors.append(f"존재하지 않는 node id: {unknown_ids}")
    if target_sec > 0 and not within_tolerance:
        if ratio < 0.9:
            errors.append(
                f"총 길이 부족: {total_duration:.1f}s / 목표 {target_sec:.1f}s "
                f"(비율 {ratio:.2f}, 허용 0.90~1.10)"
            )
        else:
            errors.append(
                f"총 길이 초과: {total_duration:.1f}s / 목표 {target_sec:.1f}s "
                f"(비율 {ratio:.2f}, 허용 0.90~1.10)"
            )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "unknown_ids": unknown_ids,
        "total_duration_sec": round(total_duration, 2),
        "target_sec": round(target_sec, 2),
        "duration_ratio": round(ratio, 3),
        "within_tolerance": within_tolerance,
    }


# "from prompt_builder import *" 했을 때 바깥에 노출되는 이름 목록.
__all__ = [
    "normalize_tree",
    "calc_duration",
    "build_prompt",
    "validate_response",
]
