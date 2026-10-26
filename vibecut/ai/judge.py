"""문장별 컷 판단: 자체 규칙 + Gemini.

규칙 (항상 먼저 계산, Gemini를 못 쓰면 이것만으로 판단)
    지시어   : "다시 할게", "처음부터", "편집해" 같은 촬영 신호
    NG       : 바로 뒤에 같은 말을 다시 한 앞부분 (글자 2개 묶음 겹침 60% 이상, 다시 찍은 마지막 것을 남김)
    군더더기 : "음", "어", "그니까"처럼 추임새만 있는 문장 (프로필의 '군말 제거 강도'를 따른다)
    강조     : 느낌표, 감탄 단어, 프로필의 '자주 쓰는 단어' → 펀치인 후보

Gemini에게는 문장 전체를 보내되 '자를 문장·강조할 문장·규칙 표시를 뒤집을 문장'만 id로 돌려받는다.
(출력이 짧아 토큰·한도를 아끼고, 응답이 잘려도 나머지는 규칙이 맡는다. 시각은 절대 돌려받지 않는다)
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel

from ..edit.validate import CUE_PATTERN
from ..models import Line, LineDecision, Scene
from .gemini import AIError, AIUnavailable, GeminiClient

log = logging.getLogger("vibecut.ai.judge")

CUT_REASONS = ("NG", "반복", "군더더기", "지시어")
KEEP_REASONS = ("핵심", "일반")
FILLERS = {"음", "어", "아", "에", "흠", "으", "엄", "저", "그", "음음", "어어", "아아", "그니까", "그러니까", "뭐지",
           "뭐랄까", "약간", "이제", "막", "뭐", "근데"}
_REPEAT = re.compile(r"^(음|어|아|으|흠|에|엄)\1*$")
_STRIP = re.compile(r"[\s.,!?…~\-\"'·]+")
EMPHASIS_WORDS = ("대박", "진짜", "완전", "최고", "헐", "미쳤", "레전드", "꿀팁", "핵심", "중요", "와!")
HARD_RULE = 0.75          # 이 확신 이상 규칙 컷은 Gemini가 따로 '남김'이라고 하지 않으면 자른다
BATCH = 400


def _tokens(text: str) -> list[str]:
    return [t for t in (_STRIP.sub("", tok) for tok in text.split()) if t]


def _norm(text: str) -> str:
    return _STRIP.sub("", text)


def _bigram_overlap(a: str, b: str) -> float:
    grams = [a[i:i + 2] for i in range(len(a) - 1)]
    if not grams:
        return 0.0
    ref = {b[i:i + 2] for i in range(len(b) - 1)}
    return sum(g in ref for g in grams) / len(grams)


def _filler_ratio(text: str) -> float:
    toks = _tokens(text)
    return sum(t in FILLERS for t in toks) / len(toks) if toks else 0.0


def filler_strength(profile: dict) -> str:
    value = str((profile or {}).get("filler_removal") or "")
    return "weak" if value.startswith("약") else "strong" if value.startswith("강") else "medium"


def is_filler_only(text: str, strength: str = "medium") -> bool:
    toks = _tokens(text)
    if not toks:
        return False
    if all(_REPEAT.match(t) for t in toks):
        return strength != "weak" or len("".join(toks)) >= 2
    return strength != "weak" and all(t in FILLERS or _REPEAT.match(t) for t in toks)


def is_retake(lines: list[Line], i: int, look: int = 3) -> bool:
    """i번 문장을 바로 뒤에서 다시 말했는가 (앞의 것이 NG)."""
    a = _norm(lines[i].text)
    if len(a) < 4:
        return False
    for j in range(i + 1, min(len(lines), i + 1 + look)):
        b = _norm(lines[j].text)
        if len(b) < max(4, 0.5 * len(a)):
            continue
        need = 0.6 if lines[j].clip_id == lines[i].clip_id else 0.7
        if _bigram_overlap(a, b) >= need or (len(a) <= 12 and b.startswith(a[:4]) and len(b) > len(a)):
            return True
    return False


def rule_decisions(lines: list[Line], profile: dict | None = None) -> dict[str, LineDecision]:
    profile = profile or {}
    strength = filler_strength(profile)
    frequent = [w for w in (profile.get("frequent_words") or []) if isinstance(w, str) and w.strip()]
    out: dict[str, LineDecision] = {}
    for i, line in enumerate(lines):
        text = line.text.strip()
        dur = line.end - line.start
        if not text:
            d = LineDecision(seg_id=line.seg_id, keep=True, reason="일반", note="받아쓰기 없음 (말소리 구간)",
                             confidence=0.3)
        elif CUE_PATTERN.search(text):
            d = LineDecision(seg_id=line.seg_id, keep=False, reason="지시어", note="촬영 지시·NG 신호", confidence=0.8)
        elif is_retake(lines, i):
            d = LineDecision(seg_id=line.seg_id, keep=False, reason="NG", note="바로 뒤에서 같은 말을 다시 했습니다",
                             confidence=0.7)
        elif is_filler_only(text, strength):
            d = LineDecision(seg_id=line.seg_id, keep=False, reason="군더더기", note="의미 없는 추임새",
                             confidence=0.75)
        elif strength == "strong" and dur < 1.5 and _filler_ratio(text) >= 0.5:
            d = LineDecision(seg_id=line.seg_id, keep=False, reason="군더더기", note="추임새가 대부분인 짧은 말",
                             confidence=0.6)
        else:
            emphasis = "!" in text or any(w in text for w in EMPHASIS_WORDS) or any(w in text for w in frequent)
            d = LineDecision(seg_id=line.seg_id, keep=True, reason="핵심" if emphasis else "일반",
                             emphasis=emphasis and dur >= 0.8, confidence=0.6 if emphasis else 0.5)
        out[line.seg_id] = d
    return out


class JudgeItem(BaseModel):
    id: str
    keep: bool
    reason: str
    confidence: float
    emphasis: bool
    note: str


class JudgeResponse(BaseModel):
    decisions: list[JudgeItem]


def _scene_label(line: Line, scenes_by_clip: dict[str, list[Scene]]) -> str:
    mid = (line.start + line.end) / 2
    for sc in scenes_by_clip.get(line.clip_id, []):
        if sc.start <= mid < sc.end:
            parts = [p for p in (sc.place, sc.activity) if p]
            return "/".join(parts)[:20]
    return ""


def build_prompt(lines: list[Line], rules: dict[str, LineDecision], scenes_by_clip: dict[str, list[Scene]],
                 profile: dict) -> str:
    labels = {"weak": "약 (크게 거슬리는 것만)", "medium": "중", "strong": "강 (추임새 전부)"}
    strength = labels[filler_strength(profile)]
    rows = []
    for line in lines:
        rule = rules[line.seg_id]
        flag = f" [규칙: {rule.reason}]" if not rule.keep else ""
        rows.append(f"{line.seg_id} | {line.start:.1f}s | {line.end - line.start:.1f}s | "
                    f"{_scene_label(line, scenes_by_clip)} | {line.text.strip() or '(받아쓰기 없음)'}{flag}")
    words = ", ".join(profile.get("frequent_words") or []) or "(없음)"
    return f"""당신은 한국어 브이로그·유튜브 영상 편집자다. 아래는 촬영 원본의 받아쓰기 문장 목록이다.
각 문장을 결과 영상에 남길지 판단하라.

[자르는 이유]
- NG: 말실수, 다시 찍은 앞부분 (같은 말을 여러 번 했으면 가장 완성된 마지막 것만 남긴다)
- 반복: 앞에서 한 내용을 의미 없이 되풀이
- 군더더기: 의미 없는 추임새·머뭇거림 (군말 제거 강도: {strength})
- 지시어: "다시 할게", "이거 편집해" 같은 촬영 지시
[남기는 이유] 핵심(하이라이트·꼭 필요한 정보), 일반
[원칙]
- 확신이 없으면 남긴다. 뒤 문장과 의미가 이어지는 문장은 자르지 않는다.
- emphasis=true는 감정이 크거나 핵심 정보라 화면 줌인이 어울리는 문장 (전체의 10% 이하).
- 자주 쓰는 단어(강조 후보): {words}
- [규칙: …] 표시는 자동 규칙이 자르려는 문장이다. 남겨야 하면 keep=true로 돌려줘라.

[출력] 다음 문장만 decisions에 넣는다 (나머지는 남김으로 처리한다):
  ① 자를 문장  ② 강조할 문장  ③ [규칙] 표시가 있지만 남길 문장
  각 항목: id, keep, reason(위 이유 중 하나), confidence(0~1), emphasis, note(20자 이내 한국어 설명)
  시각은 출력하지 않는다.

[문장 목록] id | 시작 | 길이 | 장면 | 내용
{chr(10).join(rows)}
"""


def judge_lines(lines: list[Line], scenes: list[Scene], profile: dict | None, client: GeminiClient | None
                ) -> tuple[dict[str, LineDecision], str, list[str]]:
    """(문장별 판단, 엔진 이름, 경고). 시각은 받아쓰기 그대로이고 판단만 바뀐다."""
    profile = profile or {}
    lines = sorted(lines, key=lambda x: x.seg_id)
    rules = rule_decisions(lines, profile)
    if not lines or client is None:
        return rules, "rule", []
    scenes_by_clip: dict[str, list[Scene]] = {}
    for sc in scenes:
        scenes_by_clip.setdefault(sc.clip_id, []).append(sc)
    warnings: list[str] = []
    decisions: dict[str, LineDecision] = {}
    used_ai = False
    for start in range(0, len(lines), BATCH):
        batch = lines[start:start + BATCH]
        try:
            data = client.generate_json(build_prompt(batch, rules, scenes_by_clip, profile), JudgeResponse,
                                        purpose="컷 판단", temperature=0.1)
        except AIUnavailable:
            return rules, "rule", []
        except AIError as error:
            warnings.append(f"AI 컷 판단 실패 → 규칙으로 판단했습니다: {str(error)[:150]}")
            decisions.update({line.seg_id: rules[line.seg_id] for line in batch})
            continue
        items = {}
        for item in data.get("decisions", []):
            if item["id"] in rules:
                items[item["id"]] = item
        cut_count = sum(1 for it in items.values() if not it["keep"])
        spoken = sum(1 for line in batch if line.text.strip())
        if spoken and cut_count > 0.7 * spoken:
            warnings.append("AI가 문장 대부분을 자르라고 해서 이 구간은 규칙 판단을 썼습니다.")
            decisions.update({line.seg_id: rules[line.seg_id] for line in batch})
            continue
        used_ai = True
        for line in batch:
            rule, item = rules[line.seg_id], items.get(line.seg_id)
            if item is not None:
                reason = item["reason"] if item["reason"] in CUT_REASONS + KEEP_REASONS else \
                    ("일반" if item["keep"] else "NG")
                if item["keep"] and reason in CUT_REASONS:
                    reason = "일반"
                if not item["keep"] and reason in KEEP_REASONS:
                    reason = "NG"
                decisions[line.seg_id] = LineDecision(
                    seg_id=line.seg_id, keep=bool(item["keep"]), reason=reason, note=str(item["note"])[:60],
                    confidence=max(0.0, min(1.0, float(item["confidence"]))),
                    emphasis=bool(item["emphasis"]) and line.end - line.start >= 0.8, source="ai")
            elif not rule.keep and rule.confidence >= HARD_RULE:
                decisions[line.seg_id] = rule
            else:
                decisions[line.seg_id] = LineDecision(seg_id=line.seg_id, keep=True, reason="일반", source="ai",
                                                      confidence=0.5, note=rule.note if not line.text.strip() else "")
    return decisions, ("ai" if used_ai else "rule"), warnings
