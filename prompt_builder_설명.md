# prompt_builder 공부 노트

이 문서는 `prompt_builder.py`와 그 짝인 `experiment.py`가 전체 서비스에서 어떤
역할을 하고, 데이터가 어떻게 흘러가는지를 "그림처럼" 정리한 공부용 노트다.

---

## 1. 큰 그림: 이 모듈이 서비스 안에서 하는 일

VIBECUT은 긴 영상을 짧게 자동으로 편집해 주는 서비스다. 핵심 질문은:

> "이 긴 영상에서 어떤 장면들을 뽑아내야 사용자가 원하는 결과물이 될까?"

이 질문의 **답을 Gemini에게 맡기는 다리 역할**이 `prompt_builder.py`다.

```
 ┌─────────────────┐         ┌─────────────────┐
 │  미디어 엔진     │         │  사용자 UI      │
 │  (영상 → 트리)   │         │ (목표/의도/톤)   │
 └────────┬────────┘         └────────┬────────┘
          │ 장면 트리                   │ request dict
          │                            │
          └──────────────┬─────────────┘
                         ▼
             ┌─────────────────────────┐
             │   prompt_builder.py     │
             │                         │
             │  build_prompt(          │  ◀── ★ 지시문 조립
             │    profile, request,    │
             │    tree)                │
             └───────────┬─────────────┘
                         │ 긴 문자열(prompt)
                         ▼
             ┌─────────────────────────┐
             │     Gemini API          │
             │  (gemini-3.5-flash)     │
             └───────────┬─────────────┘
                         │ selected_ids JSON
                         ▼
             ┌─────────────────────────┐
             │   prompt_builder.py     │
             │                         │
             │  validate_response(     │  ◀── ★ 응답 검증
             │    selected_ids, ...)   │
             └───────────┬─────────────┘
                         │ ok / errors 리포트
                         ▼
             ┌─────────────────────────┐
             │   미디어 엔진           │
             │   선택된 장면을 자름     │
             └─────────────────────────┘
```

---

## 2. 데이터 모양

### 2-1. 장면 트리(외부 raw 포맷)

미디어 엔진이 뽑아 주는 트리인데, 팀마다 필드명이 조금씩 다를 수 있다.

```json
[
  {
    "node_id": "intro",            // 어떤 팀은 "id", 어떤 팀은 "node_id"...
    "name": "오프닝",               // "title"로 올 때도 있음
    "start_sec": 0,                // "start"로 올 때도 있음
    "end_sec": 30,
    "children": [
      { "id": "intro-hook", "title": "훅", "start": 0, "end": 10 },
      ...
    ]
  }
]
```

### 2-2. 내부 포맷(정규화된 트리)

`normalize_tree()`를 통과하면 아래 모양으로 통일된다. 이후의 모든 함수는 이
포맷만 가정하면 되므로 코드가 단순해진다.

```json
{
  "id":       "intro",
  "title":    "오프닝",
  "start":    0.0,
  "end":      30.0,
  "children": [ ... ]
}
```

### 2-3. request dict (사용자 요청)

```python
{
    "mode": "partial",             # "manual" | "partial" | "auto"
    "locked_nodes": ["intro-hook", "tip-2"],
    "excluded_nodes": ["outro-next"],
    "purpose": "쇼츠용 핵심 요약",
    "target_minutes": 3,
    "tone": "경쾌하고 빠르게",
    "must_include": ["꿀팁"],
    "must_exclude": ["광고"],
}
```

### 2-4. Gemini 응답(바라는 모양)

```json
{
  "selected_ids": ["intro-hook", "tip-1-demo", "tip-2", "outro-cta"],
  "reasons": {
    "intro-hook": "임팩트 있는 10초 훅으로 초반 이탈 방지",
    ...
  }
}
```

### 2-5. validate_response 리턴

```python
{
    "ok": True,
    "errors": [],
    "warnings": [],
    "unknown_ids": [],
    "missing_locked": [],
    "included_excluded": [],
    "total_duration_sec": 180.0,
    "target_sec": 180.0,
    "duration_ratio": 1.0,
    "within_tolerance": True
}
```

---

## 3. 함수 호출 지도

```
build_prompt(profile, request, tree)
  │
  ├─ _ensure_normalized(tree) ── normalize_tree(tree) → 내부 포맷
  │
  ├─ _format_request_block(request, 정규화된 트리)
  │     │
  │     └─ (partial 모드만) calc_duration(locked, 트리)   ← 고정 노드 길이 계산
  │           │
  │           ├─ _ensure_normalized(트리)
  │           ├─ _build_index(트리)
  │           ├─ _build_parent_map(트리)         ← 부모/자식 중복 방지에 사용
  │           └─ _node_duration(각 노드)
  │
  ├─ _system_rules(mode)       ← 모드별 시스템 규칙
  ├─ _format_profile(profile)  ← 사용자 편집 스타일
  └─ _summarize_tree(트리, max_depth=3, budget_sec=남은예산)
         └─ walk(node, depth)  (내부 재귀 함수)


validate_response(selected_ids, request, tree)
  │
  ├─ _ensure_normalized(tree)
  ├─ _build_index(트리)
  ├─ _descendants(index[excluded_id])   ← 제외 노드의 모든 자손 수집
  └─ calc_duration(선택된 id들, 트리)    ← 총 길이 계산
```

---

## 4. 어려운 부분 쉬운 예시

### 4-1. "부모와 자식 중복 계산 방지" (calc_duration)

트리가 이런 모양이라고 하자.

```
- 카페 가기      (8분)
  └─ 주문하기   (2분)   ← 카페 가기의 "일부"
```

사용자가 "카페 가기", "주문하기" 둘 다 골랐다면 총 길이는?

- ❌ 틀린 계산: 8 + 2 = **10분**
- ✅ 올바른 계산: **8분** (주문하기는 이미 카페 가기 안에 포함돼 있으니까)

`calc_duration`은 이 중복을 자동으로 걸러낸다. 어떻게?

1. `_build_parent_map`으로 "각 노드의 부모"를 미리 알아둔다.
2. 선택된 노드 하나하나에 대해, "조상 중에 선택된 애가 있는가?"를 확인.
3. 있으면 → 그 노드는 **더하지 않는다**. (조상이 이미 그 구간을 "덮고" 있음)

```
요청: ["카페", "주문"]
      │
      ▼
카페의 조상 선택됨? → 없음(루트) → 더함(+8분)
주문의 조상 선택됨? → "카페"가 선택돼 있음 → 안 더함
      │
      ▼
총 길이 = 8분
```

### 4-2. "남은 시간 예산" (_format_request_block)

partial 모드 예시:

```
목표 분량       = 3분 = 180초
locked_nodes    = ["intro-hook"(10초), "tip-2"(100초)]
고정 노드 길이 = 10 + 100 = 110초

남은 시간 예산 = 180 - 110 = 70초
```

Gemini는 "이미 110초는 확정이니, 남은 70초를 뭘로 채울지만 골라" 라는 명확한
목표를 받게 된다. 또한 이 70초가 `_summarize_tree`에도 넘어가서, 70초보다 긴
부모 노드는 "통째로 넣기엔 너무 크니까 자식까지 펼쳐 보여줘"라고 알려 준다.

### 4-3. "normalize_tree가 왜 필요한가?"

외부 포맷이 두 팀 사이에서 이렇게 다르다고 하자.

```
팀 A의 트리:  {"id": "intro", "title": "오프닝", "start": 0, "end": 30}
팀 B의 트리:  {"node_id": "intro", "name": "오프닝", "start_sec": 0, "end_sec": 30}
```

이 둘을 각자 다루려면 코드 곳곳에 `if "id" in n elif "node_id" in n ...` 가 생겨
금방 지저분해진다. 그래서 **"들어오자마자 한 번만" 내부 포맷으로 바꾸고**, 그
뒤의 모든 함수는 내부 포맷만 가정한다.

→ 외부 포맷이 또 바뀌면? 그냥 `_FIELD_ALIASES` 표에 새 별명 하나만 추가하면 됨.
   다른 코드는 전혀 건드릴 필요가 없다. (이게 "흡수 레이어"의 힘)

```
외부 raw ──────────────────┐
                           │
                  [_FIELD_ALIASES]
                           │
                           ▼
         내부 포맷 (id, title, start, end, children)
                           │
                           ▼
       calc_duration, build_prompt, validate_response, ...
                 (전부 내부 포맷만 가정)
```

### 4-4. "트리 요약을 3단계까지만, 예산보다 긴 노드는 더 펼친다"

트리:

```
- body       (300초)
  - tip-1    (90초)
    - demo   (40초)
  - tip-2    (100초)
  - tip-3    (110초)
```

- 목표 2분(=120초) → 예산 120초. body(300초) > 예산이므로 자식까지 펼침:
  ```
  - body
    - tip-1
    - tip-2
    - tip-3
  ```
  (tip-1의 자식 demo는 depth 3이라 안 펼쳐짐. 다만 tip-1(90초) > 예산일 땐
  더 펼쳐질 수도 있음)

- 목표 10분(=600초) → body(300초) < 예산이므로 "body 통째로"만 보여도 충분.
  Gemini는 그냥 "body 하나" 고르면 됨.

**왜 이렇게 하냐?**
- 트리가 깊어질수록 프롬프트가 길어진다 → Gemini의 토큰 비용 ↑, 집중력 ↓.
- 그런데 "통으로 선택하기엔 너무 긴" 노드는 더 작은 단위로 쪼개 보여야
  Gemini가 그 중 일부만 고를 수 있다 → 그 경우에만 예외적으로 펼친다.

---

## 5. 모드별 차이

| 모드      | AI 호출 | locked/excluded | 특징                                                   |
| --------- | ------- | --------------- | ------------------------------------------------------ |
| `manual`  | ❌      | X               | `build_prompt`가 `None` 반환. 사용자가 전부 직접 편집. |
| `partial` | ✅      | O               | 고정/제외를 반영하고 "남은 예산"을 Gemini에 명시.      |
| `auto`    | ✅      | X               | 목표 분량과 의도만으로 Gemini가 전부 결정.             |

---

## 6. experiment.py와의 관계

`experiment.py`는 "prompt_builder가 실제 Gemini와 잘 통하는지" 확인하기 위한
단순 실험 스크립트다.

```
experiment.py
  │
  ├─ 조건 4개 정의 (partial 3분 / auto 2분·4분 임팩트 / auto 2분 차분)
  │
  └─ for 조건:
        prompt   = build_prompt(PROFILE, 조건, RAW_TREE)
        response = genai_client.generate_content(prompt)
        parsed   = JSON 파싱
        result   = validate_response(parsed["selected_ids"], 조건, RAW_TREE)
        결과 축적

  → 콘솔에 조건별 응답 원문/검증 결과 출력
  → 요약 표 출력
  → experiment_results.json 저장
```

실험을 통해 확인하려는 것:
- 같은 PROFILE/트리에 **목표 분량**만 바꿔도 Gemini가 다른 조합을 고르는가?
- 같은 분량이라도 **톤/목적**만 바꾸면 선택이 달라지는가?
- partial 모드에서 **locked/excluded**가 제대로 반영되는가?
- validate_response가 **잘못된 응답(길이 초과, 제외 노드 포함 등)을 잡아내는가?**

---

## 7. 공부 포인트 요약

| 개념                          | 핵심 아이디어                                                    |
| ----------------------------- | ---------------------------------------------------------------- |
| 흡수 레이어 (normalize_tree)  | 외부 포맷은 들어올 때 한 번만 통일. 뒤 코드는 내부 포맷만 안다.  |
| 멱등성 (idempotent)           | 두 번 돌려도 같은 결과. "실수로 또 호출돼도" 깨지지 않는다.      |
| 재귀 (_normalize_node, walk)  | 트리처럼 "안에 또 같은 모양"인 구조에 자연스럽다.                |
| 집합 연산 ( &, &#124;= )            | 중복 없이 "포함/합집합/교집합"을 빠르게 다룬다.                  |
| 부모 맵 (_build_parent_map)   | "조상이 선택됐나?"를 O(1)로 확인 → 중복 길이 계산 방지.          |
| 토큰 절약 (max_depth)         | 불필요한 깊은 자식을 안 보냄 → Gemini 비용 절감 + 집중력 유지.   |

