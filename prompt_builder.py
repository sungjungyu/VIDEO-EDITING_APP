#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_builder.py

사용자 요청과 장면 트리를 Gemini용 지시문으로 조립하고, AI 응답을 검증하는 모듈.

트리 형식은 아직 팀과 확정되지 않았으므로, 내부적으로 쓸 형식을 정의하고
normalize_tree()에서 외부 포맷을 흡수한다. 외부 포맷이 바뀌면 normalize_tree만
고치면 되도록 분리해 두었다.

내부 트리 노드 스키마:
    {
        "id":       str,           # 고유 식별자
        "title":    str,           # 장면/구간 제목
        "start":    float,         # 시작 초
        "end":      float,         # 종료 초
        "summary":  str (optional),
        "tags":     list[str] (optional),
        "children": list[node]
    }
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# 트리 정규화
# ---------------------------------------------------------------------------

# 외부 포맷에서 받을 수 있는 필드명 후보. 팀에서 포맷을 바꾸면 여기만 수정한다.
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
    """raw 딕셔너리에서 key에 해당하는 값을 별칭들까지 포함해 찾는다."""
    for alias in _FIELD_ALIASES[key]:
        if alias in raw:
            return raw[alias]
    return default


def _normalize_node(raw: Dict[str, Any]) -> Dict[str, Any]:
    """한 노드를 내부 포맷으로 변환."""
    node_id = _pick(raw, "id")
    title = _pick(raw, "title", "")
    start = _pick(raw, "start", 0)
    end = _pick(raw, "end", 0)
    summary = _pick(raw, "summary")  # 없을 수 있음
    tags = _pick(raw, "tags")        # 없을 수 있음
    children = _pick(raw, "children", []) or []

    # 타입 보정 (문자열로 들어오는 경우 대비)
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
        # tags는 리스트가 아니어도 리스트로 통일
        if isinstance(tags, (list, tuple, set)):
            normalized["tags"] = [str(t) for t in tags]
        else:
            normalized["tags"] = [str(tags)]
    return normalized


def normalize_tree(raw_tree: Any) -> List[Dict[str, Any]]:
    """
    외부에서 받은 트리를 내부 포맷(루트 노드들의 리스트)으로 변환한다.

    입력은 노드 하나(dict)이거나, 노드들의 리스트일 수 있다.
    지금은 그대로 통과시키는 수준으로 매핑하지만, 외부 필드명이 바뀌면
    _FIELD_ALIASES만 수정하거나 _normalize_node를 손봐서 흡수한다.
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
    """트리 전체를 DFS로 순회."""
    for root in tree:
        stack = [root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.get("children", []))


def _build_index(tree: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """id -> node 매핑."""
    return {n["id"]: n for n in _iter_nodes(tree) if n.get("id")}


def _build_parent_map(tree: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """id -> parent_id 매핑 (루트는 None)."""
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


def _descendants(node: Dict[str, Any]) -> Set[str]:
    """해당 노드의 모든 자손 id."""
    result: Set[str] = set()
    stack = list(node.get("children", []))
    while stack:
        c = stack.pop()
        result.add(c["id"])
        stack.extend(c.get("children", []))
    return result


def _node_duration(node: Dict[str, Any]) -> float:
    """단일 노드의 길이(초)."""
    try:
        return max(0.0, float(node.get("end", 0)) - float(node.get("start", 0)))
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# 길이 계산
# ---------------------------------------------------------------------------

def calc_duration(node_ids: Iterable[str], tree: Any) -> float:
    """
    선택된 노드들의 총 길이(초)를 계산한다.

    부모와 자식이 함께 선택되면 부모만 치고 자식은 더하지 않는다
    (부모 구간이 자식 구간을 포함한다고 간주).
    """
    normalized = _ensure_normalized(tree)
    index = _build_index(normalized)
    parent_map = _build_parent_map(normalized)

    requested: Set[str] = {nid for nid in node_ids if nid in index}

    # 선택된 id 중에서, 조상 중 하나라도 선택돼 있으면 그 자식은 제외한다.
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
    """이미 내부 포맷이면 그대로, 아니면 normalize_tree를 돌려서 반환."""
    if isinstance(tree, list) and all(isinstance(n, dict) and "children" in n for n in tree):
        return tree
    return normalize_tree(tree)


# ---------------------------------------------------------------------------
# 프롬프트 조립
# ---------------------------------------------------------------------------

_SCHEMA_LINE = (
    '{ "selected_ids": ["<node_id>", ...], '
    '"reasons": {"<node_id>": "<선택 이유 한 줄>", ...} }'
)

_BASE_RULES = [
    "반드시 아래 JSON 스키마로만 응답한다. 다른 텍스트, 주석, 코드블록 금지.\n   "
    + _SCHEMA_LINE,
    "selected_ids는 제공된 트리에 실제로 존재하는 id만 사용한다.",
    "목표 분량(target_minutes)에 최대한 가깝게 선택한다. 오차는 ±10% 이내.",
    "부모 노드를 선택하면 그 모든 자식 구간이 포함된다고 간주한다.",
]

_PARTIAL_RULES = [
    "고정 노드(locked_nodes)는 반드시 selected_ids에 포함한다.",
    "제외 노드(excluded_nodes)와 그 자손은 selected_ids에 포함하지 않는다.",
]


def _system_rules(mode: str) -> str:
    """모드별 시스템 규칙. auto는 고정/제외 규칙을 넣지 않는다."""
    rules = list(_BASE_RULES)
    if mode == "partial":
        rules.extend(_PARTIAL_RULES)
    header = "너는 영상 편집용 장면 선택 어시스턴트다. 아래 규칙을 반드시 지켜라."
    numbered = [f"{i+1}) {r}" for i, r in enumerate(rules)]
    return header + "\n" + "\n".join(numbered)


def _fmt_keywords(items: List[Any]) -> str:
    """키워드 리스트를 '꿀팁, 레전드' 형태로. 비어있으면 '(없음)'."""
    if not items:
        return "(없음)"
    return ", ".join(str(x) for x in items)


def _format_profile(profile: Dict[str, Any]) -> str:
    """
    장면 선택 지시문용 프로필.
    자막 스타일/화면비는 렌더링 단계에서 쓰는 값이라 여기선 제외하고,
    컷 템포, 군말 제거 강도, 자주 쓰는 단어만 포함한다.
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
    budget_sec: Optional[float] = None,
) -> str:
    """
    트리를 요약해서 문자열로 만든다.
    기본은 3단계까지(루트 depth 0 포함) 표시.
    budget_sec가 주어지면, 그보다 긴 노드는 depth 상한을 넘어도
    자식까지 펼쳐서 보여준다 (AI가 더 작은 단위로 고를 수 있도록).
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
            elif budget_sec is not None and dur > budget_sec:
                # 예산보다 긴 부모는 상한을 넘어서도 자식까지 펼친다.
                walk(child, next_depth)

    for root in tree:
        walk(root, 0)
    return "\n".join(out) if out else "(트리 비어있음)"


def _format_request_block(
    request: Dict[str, Any],
    tree: List[Dict[str, Any]],
) -> Tuple[str, Optional[float]]:
    """
    요청 블록 문자열과, partial 모드일 때의 남은 시간 예산(초)을 함께 반환한다.
    budget_sec는 트리 요약 깊이 조절에 쓴다.
    """
    mode = request.get("mode", "auto")
    locked = list(request.get("locked_nodes") or [])
    excluded = list(request.get("excluded_nodes") or [])
    purpose = request.get("purpose", "")
    target = float(request.get("target_minutes", 0) or 0)
    tone = request.get("tone", "")
    must_include = list(request.get("must_include") or [])
    must_exclude = list(request.get("must_exclude") or [])

    lines = ["[이번 영상 요청]"]
    lines.append(f"- 모드: {mode}")
    lines.append(f"- 의도/목적: {purpose or '(명시 없음)'}")
    lines.append(f"- 목표 분량: {target}분")
    lines.append(f"- 톤: {tone or '(명시 없음)'}")
    lines.append(f"- 반드시 포함할 키워드: {_fmt_keywords(must_include)}")
    lines.append(f"- 반드시 제외할 키워드: {_fmt_keywords(must_exclude)}")

    budget_sec: Optional[float] = None
    if mode == "partial":
        locked_total = calc_duration(locked, tree)
        remaining_sec = max(0.0, target * 60.0 - locked_total)
        budget_sec = remaining_sec
        lines.append(f"- 고정(locked) 노드 id: {_fmt_keywords(locked)}")
        lines.append(f"- 제외(excluded) 노드 id: {_fmt_keywords(excluded)}")
        lines.append(f"- 고정 노드 총 길이: {locked_total:.1f}초")
        lines.append(
            f"- 남은 시간 예산: {remaining_sec:.1f}초 "
            f"(= {target}분 - 고정 노드 길이). 이 예산 안에서 추가 노드를 골라라."
        )
    elif mode == "auto":
        lines.append("- auto 모드: 위 의도와 목표 분량만으로 전부 선택하라.")

    return "\n".join(lines), budget_sec


def build_prompt(
    profile: Dict[str, Any],
    request: Dict[str, Any],
    tree: Any,
) -> Optional[str]:
    """
    Gemini에 보낼 지시문을 조립한다.

    - manual 모드: AI 호출이 필요 없으므로 None 반환.
    - partial 모드: 고정 노드는 포함, 제외 노드는 제외, 남은 시간 예산을 명시.
      트리 요약도 예산보다 긴 노드는 자식까지 펼친다.
    - auto 모드: 목표 분량과 의도만으로 전부 선택하도록 지시.

    지시문은 [시스템 규칙] / [제작자 프로필] / [이번 영상 요청] + [장면 트리 요약]
    순서로 구성된다.
    """
    mode = (request or {}).get("mode", "auto")
    if mode == "manual":
        return None

    normalized = _ensure_normalized(tree)
    request_block, budget_sec = _format_request_block(request or {}, normalized)

    parts: List[str] = []
    parts.append("[시스템 규칙]")
    parts.append(_system_rules(mode))
    parts.append("")
    parts.append(_format_profile(profile or {}))
    parts.append("")
    parts.append(request_block)
    parts.append("")
    parts.append("[장면 트리 요약]")
    parts.append(_summarize_tree(normalized, max_depth=3, budget_sec=budget_sec))
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
    """
    AI가 돌려준 selected_ids가 요청과 트리에 비추어 올바른지 검사한다.

    반환 형태:
        {
            "ok": bool,
            "errors": [str, ...],
            "warnings": [str, ...],
            "unknown_ids": [str, ...],
            "missing_locked": [str, ...],
            "included_excluded": [str, ...],
            "total_duration_sec": float,
            "target_sec": float,
            "duration_ratio": float,  # total / target
            "within_tolerance": bool  # ±10% 이내인지
        }
    """
    normalized = _ensure_normalized(tree)
    index = _build_index(normalized)

    selected = list(selected_ids or [])
    selected_set: Set[str] = set(selected)

    # 1) 존재하지 않는 id
    unknown_ids = sorted([sid for sid in selected if sid not in index])

    # 2) 고정 노드 누락
    locked = list((request or {}).get("locked_nodes") or [])
    missing_locked = sorted([lid for lid in locked if lid not in selected_set])

    # 3) 제외 노드(및 그 자손) 포함 여부
    excluded = list((request or {}).get("excluded_nodes") or [])
    excluded_universe: Set[str] = set()
    for eid in excluded:
        excluded_universe.add(eid)
        if eid in index:
            excluded_universe |= _descendants(index[eid])
    included_excluded = sorted(list(selected_set & excluded_universe))

    # 4) 길이 검사 (±10%)
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
    if missing_locked:
        errors.append(f"고정 노드 누락: {missing_locked}")
    if included_excluded:
        errors.append(f"제외 노드가 포함됨: {included_excluded}")
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
        "missing_locked": missing_locked,
        "included_excluded": included_excluded,
        "total_duration_sec": round(total_duration, 2),
        "target_sec": round(target_sec, 2),
        "duration_ratio": round(ratio, 3),
        "within_tolerance": within_tolerance,
    }


__all__ = [
    "normalize_tree",
    "calc_duration",
    "build_prompt",
    "validate_response",
]
