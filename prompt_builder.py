#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_builder.py
==================

[이 파일의 역할 - 큰 그림]
---------------------------
VIBECUT(영상 자동 편집) 서비스에서 "Gemini에게 어떤 장면을 고르라고 시킬지"
지시문(= 프롬프트)을 만들어 주는 모듈이야.

사용자가 영상을 올리면 미디어 엔진이 "장면 트리"를 뽑아내고, 사용자는 UI에서
"3분짜리 쇼츠로", "이 장면은 꼭 넣어줘" 같은 요청을 입력해. 이 모듈은 그
두 가지(장면 트리 + 요청)를 합쳐서 Gemini가 읽기 좋은 하나의 긴 문자열로
조립한다. 그리고 Gemini가 돌려준 답(selected_ids)이 요청에 맞는지도 여기서
검증한다.

[전체 서비스에서 이 파일이 하는 일 - 흐름]
------------------------------------------
    [미디어 엔진]              [사용자 UI 입력]
   (장면 트리 뽑기)         (목표 분량, 의도, 톤 등)
         │                           │
         └────────┬──────────────────┘
                  ▼
          [prompt_builder]
            build_prompt()  ← ★ 이 파일의 핵심
                  │
                  ▼
            [Gemini API] ── 긴 지시문을 보내면 selected_ids를 돌려줌
                  │
                  ▼
          [prompt_builder]
         validate_response() ← ★ Gemini 답이 올바른지 검사
                  │
                  ▼
        [미디어 엔진이 선택된 장면을 실제로 자름]


[이 파일 안에서의 데이터 흐름]
------------------------------
    외부 raw 트리 (팀마다 필드명이 다름)
             │
             ▼
       normalize_tree()  ── 내부 포맷으로 통일 (id/title/start/end/children)
             │
             ▼
    build_prompt(profile, request, tree)
             │  (내부에서 _format_request_block, _summarize_tree 호출)
             ▼
    Gemini에게 보낼 긴 문자열(prompt)
             │
             │  (Gemini가 selected_ids를 돌려줌)
             ▼
    validate_response(selected_ids, request, tree)
             │
             ▼
    { ok, errors, warnings, total_duration_sec, ... }


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

트리 형식은 아직 팀과 확정되지 않았으므로, 외부에서 어떤 이름(node_id, name,
start_sec 등)으로 와도 normalize_tree()가 흡수해서 위 포맷으로 바꾼다.
외부 포맷이 바뀌면 아래 _FIELD_ALIASES만 수정하면 돼.
"""

from __future__ import annotations

# json은 지금 당장은 쓰이지 않지만, 응답 파싱 유틸을 이 모듈에 다시 추가할
# 가능성이 있어 import만 유지해 둔다. (경고는 떠도 동작엔 영향 없음)
import json
# typing은 함수 시그니처에 타입 힌트를 적기 위한 import.
#   Any       = 아무 타입이나 가능
#   Dict      = 딕셔너리(사전)
#   Iterable  = 한 개씩 꺼낼 수 있는 것 (list/tuple/set 등)
#   List      = 리스트
#   Optional  = None도 될 수 있음
#   Set       = 집합(중복 없는 모음)
#   Tuple     = 튜플(길이 고정 모음)
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# 트리 정규화
# ---------------------------------------------------------------------------
# ★ 공부 포인트: 왜 "정규화"가 필요한가?
#   팀 A는 노드 id를 "id"라고 부르고, 팀 B는 "node_id"라고 부를 수 있다.
#   매번 코드에서 if "id" in n elif "node_id" in n ... 로 분기하면 금방
#   지저분해진다. 그래서 "데이터가 들어오자마자 한 번만" 우리 내부 포맷으로
#   바꾸고, 그 뒤의 모든 함수는 내부 포맷만 가정하도록 하면 깔끔해진다.
#   → 외부 포맷이 바뀌면 아래 _FIELD_ALIASES 표만 바꾸면 끝.

# 외부 포맷에서 받을 수 있는 필드명 후보. 팀에서 포맷을 바꾸면 여기만 수정한다.
# 예) 외부에서 "node_id"로 왔든 "uid"로 왔든 전부 내부의 "id"로 흡수된다.
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
      raw     : 노드 하나 (dict)
      key     : 내부 포맷 이름 (예: "id", "start")
      default : 어떤 별명으로도 못 찾았을 때 돌려줄 기본값

    [출력]
      찾은 값, 또는 default

    [왜 필요한가]
      _normalize_node 내부에서 "node_id or id or uid or key" 식으로 체크하는
      걸 깔끔하게 뽑아놓은 헬퍼 함수.
    """
    for alias in _FIELD_ALIASES[key]:
        if alias in raw:
            return raw[alias]
    return default


def _normalize_node(raw: Dict[str, Any]) -> Dict[str, Any]:
    """한 노드를 내부 포맷으로 변환.

    [무엇을 하는지]
      외부 노드 하나를 받아 우리 내부 포맷(id/title/start/end/children)의
      "새 딕셔너리"를 만들어 돌려준다. children이 있으면 재귀적으로 각 자식도
      똑같이 변환한다. → 트리 전체가 내부 포맷으로 바뀜.

    [입력]  외부 포맷의 노드 하나 (dict)
    [출력]  내부 포맷의 노드 하나 (새로 만든 dict)

    [왜 필요한가]
      외부 포맷 흡수 + 타입 보정(문자열로 들어온 start/end를 float으로)을
      한 곳에서 처리하기 위해.

    [참고 - 파이썬 문법]
      - [_normalize_node(c) for c in children] 는 "리스트 컴프리헨션".
        for 반복문을 한 줄로 쓴 것 — children의 각 c에 대해 함수를 돌려
        그 결과들을 모아 새 리스트를 만든다.
      - 자기 자신을 호출하는 걸 "재귀"라고 한다. 트리처럼 "안에 또 같은
        모양이 들어있는" 구조를 다룰 때 자연스럽게 쓰인다.
    """
    # alias들을 순서대로 보면서 첫 번째로 발견되는 값을 꺼낸다.
    node_id = _pick(raw, "id")
    title = _pick(raw, "title", "")
    start = _pick(raw, "start", 0)
    end = _pick(raw, "end", 0)
    summary = _pick(raw, "summary")  # 없을 수 있음
    tags = _pick(raw, "tags")        # 없을 수 있음
    # "or []"는 왼쪽이 None/빈값이면 오른쪽을 쓰라는 뜻.
    # children이 None이어도 아래 for 반복이 터지지 않게 한다.
    children = _pick(raw, "children", []) or []

    # 타입 보정 (문자열로 들어오는 경우 대비)
    # 예: "30.5"라는 문자열이 들어오면 float("30.5") == 30.5로 바꾼다.
    # try/except는 "변환 실패하면 0.0으로 두자"는 안전장치.
    try:
        start = float(start) if start is not None else 0.0
    except (TypeError, ValueError):
        start = 0.0
    try:
        end = float(end) if end is not None else 0.0
    except (TypeError, ValueError):
        end = 0.0

    # 내부 포맷의 새 dict를 만들어 반환. (원본 raw는 건드리지 않음)
    # children은 재귀적으로 자식 노드들에 똑같은 변환을 적용.
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
        # (문자열 하나로 왔으면 ["문자열"]로 감싼다.)
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

    [출력]  루트 노드들의 리스트 (항상 list[dict])

    [왜 필요한가]
      - 외부 포맷이 바뀌어도 이 함수만 고치면 다른 코드는 그대로 쓸 수 있다.
      - "루트가 하나든 여러 개든" 상관없이 항상 리스트로 통일해 두면 뒤의
        for 루프가 간결해진다.

    [중요한 성질 - 멱등성]
      이 함수를 "이미 내부 포맷인 트리"에 또 돌려도 결과가 똑같다.
      (_pick이 "id"를 가장 먼저 찾고, 매번 새 dict를 만들기 때문)
      이 성질 덕분에 _ensure_normalized에서 안심하고 "항상 호출"할 수 있다.
    """
    if raw_tree is None:
        return []
    if isinstance(raw_tree, dict):
        # 노드가 하나만 들어오면 리스트에 담아서 반환.
        return [_normalize_node(raw_tree)]
    if isinstance(raw_tree, list):
        return [_normalize_node(n) for n in raw_tree]
    # 위 두 가지 외의 타입은 지원하지 않는다 → 명확히 에러로 알린다.
    raise TypeError(f"지원하지 않는 트리 입력 타입: {type(raw_tree).__name__}")


# ---------------------------------------------------------------------------
# 트리 순회 유틸
# ---------------------------------------------------------------------------
# 트리 안의 모든 노드를 돌아보고 싶을 때, id로 노드를 바로 찾고 싶을 때,
# 부모를 알고 싶을 때 쓰는 작은 도구들.

def _iter_nodes(tree: List[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    """트리 전체를 DFS로 순회.

    [무엇을 하는지]
      트리의 모든 노드를 하나씩 yield(= 반환)한다.
      "DFS"는 깊이 우선 탐색 — 자식 → 자식의 자식 순서로 깊이 내려간다.

    [참고 - 파이썬 문법]
      - yield가 있는 함수는 "제너레이터". for 문에서 하나씩 꺼낼 수 있다.
      - stack.pop()은 "가장 최근에 넣은 것부터" 꺼내므로 DFS가 된다.
    """
    for root in tree:
        # 각 루트마다 자체 스택을 돌린다.
        stack = [root]
        while stack:
            node = stack.pop()
            yield node
            # dict.get("children", [])는 "children 키가 없으면 빈 리스트".
            # 자식들을 스택에 쌓아두고 다음 while에서 하나씩 꺼낸다.
            stack.extend(node.get("children", []))


def _build_index(tree: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """id -> node 매핑.

    [무엇을 하는지]
      {"intro-hook": {...해당 노드...}, "tip-2": {...}} 같은 사전을 만든다.
      이렇게 두면 "id로 노드를 O(1)로 찾기"가 가능해서 매번 트리를 뒤지지
      않아도 된다.

    [참고 - 파이썬 문법]
      - {k: v for ... if ...} 는 "딕셔너리 컴프리헨션".
    """
    return {n["id"]: n for n in _iter_nodes(tree) if n.get("id")}


def _build_parent_map(tree: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """id -> parent_id 매핑 (루트는 None).

    [무엇을 하는지]
      "이 노드의 부모는 누구?"를 바로 조회할 수 있는 사전을 만든다.
      루트 노드는 부모가 없으니 None으로 둔다.

    [왜 필요한가]
      calc_duration에서 "선택된 노드의 조상 중 선택된 게 있으면 중복으로
      치지 말자"는 판정을 할 때, 부모를 거슬러 올라가는 데 쓰인다.
    """
    parent_map: Dict[str, Optional[str]] = {}
    for root in tree:
        # 루트의 부모는 없다.
        parent_map[root["id"]] = None
        # (현재 노드, 부모 id)를 stack에 쌓아 DFS로 내려간다.
        stack: List[Tuple[Dict[str, Any], Optional[str]]] = [(root, None)]
        while stack:
            node, _ = stack.pop()
            for child in node.get("children", []):
                parent_map[child["id"]] = node["id"]
                stack.append((child, node["id"]))
    return parent_map


def _descendants(node: Dict[str, Any]) -> Set[str]:
    """해당 노드의 모든 자손 id.

    [무엇을 하는지]
      node 아래 깊이에 상관없이 모든 자식/손자/증손자 id를 집합(set)으로 모은다.

    [왜 필요한가]
      "excluded_nodes에 outro를 넣었으면 그 아래의 outro-cta, outro-next도
      전부 제외해야 한다"를 검사하기 위해.
    """
    result: Set[str] = set()
    stack = list(node.get("children", []))
    while stack:
        c = stack.pop()
        result.add(c["id"])
        stack.extend(c.get("children", []))
    return result


def _node_duration(node: Dict[str, Any]) -> float:
    """단일 노드의 길이(초).

    end - start를 계산해서 노드 길이를 초로 돌려준다. 음수면 0으로.
    """
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

    [무엇을 하는지]
      Gemini가 "이 id들을 고르겠다"고 돌려줬을 때, 그 노드들의 총 재생 길이를
      초 단위로 계산한다.

    [중요 규칙 - 부모/자식 중복 방지 (쉬운 예)]
      "카페 가기(8분)" 아래에 "주문하기(2분)"라는 자식 노드가 있다고 하자.
      Gemini가 둘 다 골랐다면 → 그냥 "카페 가기 8분"만 센다. (10분이 아님!)
      주문하기는 카페 가기의 "일부"이기 때문에 이중으로 세면 안 된다.

    [입력]
      node_ids : 선택된 id들 (문자열의 iterable)
      tree     : 트리 (정규화 전/후 모두 OK)

    [출력]  총 길이 (float, 초)
    """
    normalized = _ensure_normalized(tree)
    index = _build_index(normalized)
    parent_map = _build_parent_map(normalized)

    # 트리에 실제로 존재하는 id만 걸러낸다.
    # (Gemini가 없는 id를 환각으로 뱉어도 여기서 제외됨)
    # {... for ... if ...} 는 "집합 컴프리헨션".
    requested: Set[str] = {nid for nid in node_ids if nid in index}

    # 선택된 id 중에서, 조상 중 하나라도 선택돼 있으면 그 자식은 제외한다.
    # ← 이게 "부모만 치고 자식은 안 세기" 로직의 핵심.
    effective: Set[str] = set()
    for nid in requested:
        p = parent_map.get(nid)
        covered = False
        # 부모 → 부모의 부모 → ... 루트까지 거슬러 올라가며,
        # 조상 중에 선택된 게 있는지 확인.
        while p is not None:
            if p in requested:
                covered = True
                break
            p = parent_map.get(p)
        if not covered:
            effective.add(nid)

    # 조상이 선택되지 않은 "진짜 셀 대상"들의 길이만 합산.
    total = 0.0
    for nid in effective:
        total += _node_duration(index[nid])
    return total


def _ensure_normalized(tree: Any) -> List[Dict[str, Any]]:
    """항상 normalize_tree를 돌려서 반환.

    normalize_tree는 멱등(이미 내부 포맷을 넣어도 같은 결과)이고 원본을 수정하지
    않으므로 두 번 돌려도 안전하다. 과거엔 "list of dict with children" 휴리스틱
    으로 재정규화를 건너뛰었는데, 외부 포맷이 루트 레벨에서 우연히 'children'을
    쓰면서도 하위 필드는 alias(예: node_id)를 쓰는 경우를 '정규화됨'으로 오판해
    _build_parent_map 등이 깨졌다.

    [공부용 보충]
      "항상 정규화"는 조금 손해(한 번 더 돌아감)지만 "실수로 안 돌아가 깨지는"
      사고를 완전히 막는다. 안정성이 미세한 성능보다 중요.
    """
    return normalize_tree(tree)


# ---------------------------------------------------------------------------
# 프롬프트 조립
# ---------------------------------------------------------------------------
# 여기서부터는 Gemini에게 보낼 문자열(= 프롬프트)을 조립하는 부분.
# 프롬프트는 큰 블록 네 개로 구성된다:
#   1) [시스템 규칙]   : "응답은 반드시 이런 JSON으로만" 같은 공통 규칙
#   2) [제작자 프로필] : 사용자의 평소 편집 스타일
#   3) [이번 영상 요청]: 이번에 뭘 만들고 싶은지 (모드/목표분량/톤/제외...)
#   4) [장면 트리 요약]: 어떤 장면들이 있는지 보여주는 리스트

_SCHEMA_LINE = (
    '{ "selected_ids": ["<node_id>", ...], '
    '"reasons": {"<node_id>": "<선택 이유 한 줄>", ...} }'
)

# ★ _BASE_RULES: 모든 모드에서 Gemini가 지켜야 할 공통 규칙.
_BASE_RULES = [
    "반드시 아래 JSON 스키마로만 응답한다. 다른 텍스트, 주석, 코드블록 금지.\n   "
    + _SCHEMA_LINE,
    "selected_ids는 제공된 트리에 실제로 존재하는 id만 사용한다.",
    "목표 분량(target_minutes)에 최대한 가깝게 선택한다. 오차는 ±10% 이내.",
    "부모 노드를 선택하면 그 모든 자식 구간이 포함된다고 간주한다.",
]

# ★ _PARTIAL_RULES: partial 모드에서만 추가로 지켜야 할 규칙.
# auto 모드엔 locked/excluded 개념이 없으므로 넣지 않는다.
_PARTIAL_RULES = [
    "고정 노드(locked_nodes)는 반드시 selected_ids에 포함한다.",
    "제외 노드(excluded_nodes)와 그 자손은 selected_ids에 포함하지 않는다.",
]


def _system_rules(mode: str) -> str:
    """모드별 시스템 규칙. auto는 고정/제외 규칙을 넣지 않는다.

    [무엇을 하는지]
      공통 규칙 + (partial이면) 추가 규칙을 번호 매긴 문자열로 만든다.

    [입력] mode : "auto" | "partial" | "manual"
    [출력] "너는 영상 편집용 ... 1) ... 2) ..." 형식의 문자열

    [참고 - 파이썬 문법]
      - enumerate(리스트) 는 (0, 첫값), (1, 둘째값), ... 식으로 번호와 값을
        한 쌍씩 돌려주는 함수.
    """
    rules = list(_BASE_RULES)
    if mode == "partial":
        rules.extend(_PARTIAL_RULES)
    header = "너는 영상 편집용 장면 선택 어시스턴트다. 아래 규칙을 반드시 지켜라."
    numbered = [f"{i+1}) {r}" for i, r in enumerate(rules)]
    return header + "\n" + "\n".join(numbered)


def _fmt_keywords(items: List[Any]) -> str:
    """키워드 리스트를 '꿀팁, 레전드' 형태로. 비어있으면 '(없음)'.

    [무엇을 하는지]
      리스트를 사람이 읽기 좋게 쉼표로 이어붙인 문자열로 만든다.
      빈 리스트면 "(없음)"을 돌려줘서 Gemini가 혼동하지 않게 한다.
    """
    if not items:
        return "(없음)"
    return ", ".join(str(x) for x in items)


def _format_profile(profile: Dict[str, Any]) -> str:
    """
    장면 선택 지시문용 프로필.
    자막 스타일/화면비는 렌더링 단계에서 쓰는 값이라 여기선 제외하고,
    컷 템포, 군말 제거 강도, 자주 쓰는 단어만 포함한다.

    [무엇을 하는지]
      사용자의 평소 편집 스타일을 Gemini가 참고할 수 있도록 깔끔한
      블록 문자열로 만든다.

    [왜 자막 스타일/화면비는 뺐는가?]
      그 값들은 "실제 영상을 렌더링"할 때 쓰는 값이지, "어떤 장면을 고를지"에는
      영향을 주지 않는다. 쓸데없는 정보를 넣으면 토큰만 낭비되고 Gemini가
      혼동할 수도 있다.

    [참고 - 파이썬 문법]
      - dict.get("key", "default") 는 "key가 있으면 그 값, 없으면 default"를
        돌려준다. 안전하게 꺼낼 때 많이 쓴다.
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

    [무엇을 하는지]
      장면 트리를 들여쓰기된 리스트 형태의 문자열로 바꾼다. 예:

        - [intro] 오프닝 (0.0-30.0s, 30.0s)
          - [intro-hook] 훅 멘트 (0.0-10.0s, 10.0s)
          - [intro-topic] 오늘 주제 (10.0-30.0s, 20.0s)

    [왜 3단계까지만?]
      너무 깊은 자식까지 모두 넣으면 프롬프트가 쓸데없이 길어진다
      (= 토큰 비용↑, Gemini의 집중력↓). 보통 3단계면 사람이 보기에도
      충분한 수준의 "장면 지도"가 된다.

    [왜 "예산보다 긴 노드"는 더 펼치는가?]
      예: 목표 3분(=180초)인데 "본론(body)"이 혼자 300초짜리라면,
      body를 통째로 고르면 분량이 넘친다. 그래서 body 아래의 더 작은
      장면(tip-1, tip-2, ...)까지 보여줘야 Gemini가 "그 중 일부만" 고를
      수 있다. 작은 노드만 봐도 충분한 경우엔 굳이 안 펼친다.

    [입력]
      tree       : 정규화된 루트 리스트
      max_depth  : 들여쓰기 깊이 상한 (3이면 루트가 depth 0, 손자까지 표시)
      budget_sec : partial 모드에서 "아직 남은 시간 예산".
                   이 값보다 긴 노드만 depth 상한을 넘어 자식까지 펼친다.
    """
    out: List[str] = []

    def walk(node: Dict[str, Any], depth: int) -> None:
        # 내부 함수(= 클로저). out 리스트를 공유해서 결과를 쌓는다.
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
                # 아직 상한에 안 닿았으면 그냥 더 내려간다.
                walk(child, next_depth)
            elif budget_sec is not None and dur > budget_sec:
                # 예산보다 긴 부모는 상한을 넘어서도 자식까지 펼친다.
                walk(child, next_depth)

    for root in tree:
        walk(root, 0)
    # 트리가 완전히 비어 있으면 "(트리 비어있음)"을 돌려준다.
    return "\n".join(out) if out else "(트리 비어있음)"


def _format_request_block(
    request: Dict[str, Any],
    tree: List[Dict[str, Any]],
) -> Tuple[str, Optional[float]]:
    """
    요청 블록 문자열과, partial 모드일 때의 남은 시간 예산(초)을 함께 반환한다.
    budget_sec는 트리 요약 깊이 조절에 쓴다.

    [무엇을 하는지]
      사용자가 넘긴 "이번 영상 요청"을 Gemini가 읽을 블록 형태로 바꾼다.
      partial 모드라면 "고정 노드 길이를 뺀 남은 시간 예산"을 계산해서
      함께 적어 준다.

    [남은 시간 예산 - 쉬운 예시]
      목표 3분 = 180초
      고정 노드(꼭 넣어야 할 장면)들의 길이 합 = 110초
      → 남은 시간 예산 = 180 - 110 = 70초
      → Gemini는 "나머지 70초를 뭘로 채울지" 고르는 역할.

      이 budget_sec는 _summarize_tree에도 넘긴다. 70초보다 긴 부모 노드는
      "통째로 넣기엔 너무 커서" 자식까지 펼쳐 보여준다.

    [출력]
      (요청 블록 문자열, budget_sec)
      budget_sec은 auto/manual일 때 None.
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
        # partial 모드에서만 "고정 길이 / 남은 예산"을 계산.
        locked_total = calc_duration(locked, tree)
        # max(0, ...): 음수가 되는 상황(고정만으로 이미 넘침)에서는 0으로.
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

    [이 함수가 이 모듈의 "메인 입구"다.]

    [무엇을 하는지]
      profile(사용자 편집 스타일) + request(이번 요청) + tree(장면 트리)를
      받아, Gemini가 바로 읽을 수 있는 하나의 긴 문자열을 만들어 돌려준다.

    [입력]
      profile : 사용자 편집 스타일 dict
      request : 이번 요청 dict (mode/target_minutes/locked_nodes/...)
      tree    : 장면 트리 (정규화 전/후 모두 OK)

    [출력]
      Gemini용 프롬프트 문자열, 또는 None (manual 모드)
    """
    mode = (request or {}).get("mode", "auto")
    if mode == "manual":
        # manual은 AI를 안 쓰므로 아예 프롬프트를 안 만든다.
        return None

    # 트리를 내부 포맷으로 통일.
    normalized = _ensure_normalized(tree)
    # 요청 블록 + partial 모드일 때 "남은 예산" 계산.
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
    # 모든 블록을 줄바꿈으로 이어 하나의 문자열로.
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

    [무엇을 하는지]
      Gemini의 selected_ids가 다음을 지키는지 모두 확인한다:
        1) 존재하지 않는 id가 섞여 있지 않은지
        2) 반드시 넣어야 할 고정 노드가 빠지지 않았는지
        3) 제외하라고 한 노드(및 그 자손)가 포함되지 않았는지
        4) 총 길이가 목표 분량의 ±10% 안인지

    [왜 필요한가]
      Gemini는 가끔 환각(없는 id 생성)이나 지시 위반을 한다. 그걸 믿고
      바로 영상을 자르면 사고가 난다. 그래서 "자르기 전에" 한 번 검사한다.
    """
    normalized = _ensure_normalized(tree)
    index = _build_index(normalized)

    selected = list(selected_ids or [])
    # set으로 바꿔두면 "포함 여부" 체크가 빠르다 (O(1)).
    selected_set: Set[str] = set(selected)

    # 1) 존재하지 않는 id
    #    (리스트 컴프리헨션 + sorted: 결과를 정렬된 리스트로 돌려줌)
    unknown_ids = sorted([sid for sid in selected if sid not in index])

    # 2) 고정 노드 누락
    locked = list((request or {}).get("locked_nodes") or [])
    missing_locked = sorted([lid for lid in locked if lid not in selected_set])

    # 3) 제외 노드(및 그 자손) 포함 여부
    #    예: excluded_nodes=["outro"] 라면 outro뿐 아니라 outro-cta, outro-next도
    #    "제외 대상"에 들어가야 한다. _descendants로 자손을 다 모은다.
    excluded = list((request or {}).get("excluded_nodes") or [])
    excluded_universe: Set[str] = set()
    for eid in excluded:
        excluded_universe.add(eid)
        if eid in index:
            # |= 는 집합의 "합집합 대입". a |= b는 "a에 b를 보태라"는 뜻.
            excluded_universe |= _descendants(index[eid])
    # & 는 집합의 "교집합" → 선택된 것 중에서 제외 대상에 들어있는 것들.
    included_excluded = sorted(list(selected_set & excluded_universe))

    # 4) 길이 검사 (±10%)
    target_minutes = float((request or {}).get("target_minutes", 0) or 0)
    target_sec = target_minutes * 60.0
    # 없는 id는 길이 계산에서 뺀다 (unknown으로 따로 보고됨).
    known_selected = [sid for sid in selected if sid in index]
    total_duration = calc_duration(known_selected, normalized)
    # 0으로 나누기 방지: target_sec > 0일 때만 비율 계산.
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
        # errors가 비어 있을 때만 통과.
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


# __all__ : "from prompt_builder import *" 했을 때 바깥에 노출되는 이름 목록.
# 즉 이 모듈의 "공개 API"를 명시한다. 다른 함수들은 내부 전용(_로 시작).
__all__ = [
    "normalize_tree",
    "calc_duration",
    "build_prompt",
    "validate_response",
]
